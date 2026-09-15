"""Deterministic cross-repo evidence test; never connects to a broker.

Runs each repository in its own runtime, serializing JSON across boundaries.
Only provider I/O is replaced with labelled test fixtures. Scoring, indicators,
API models, action normalization and Manager synthesis are production code.
"""

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    from . import paper_path_fixture
except ImportError:
    import paper_path_fixture


SCANNER = r'''
import pandas as pd
from app.services.financial_evidence_payload import build_financial_evidence_payload
dates = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"])
quarters = pd.to_datetime(["2026-06-30", "2026-03-31"])
financials = {
    "info": {"sector": "Technology", "currency": "USD", "financialCurrency": "USD",
             "returnOnEquity": .3, "returnOnAssets": .2, "returnOnInvestedCapital": .3,
             "profitMargins": .3, "operatingMargins": .3, "grossMargins": .6,
             "trailingPE": 40, "forwardPE": 35, "pegRatio": 1.5, "priceToBook": 8,
             "trailingEps": 6, "debtToEquity": 20, "marketCap": 200e9,
             "enterpriseValue": 200e9, "ebitda": 10e9},
    "annual_income_statement": pd.DataFrame(
        [[40e9,30e9,22e9,16e9], [6,4,3,2], [10e9,7e9,5e9,3e9]],
        index=["Total Revenue", "Diluted EPS", "Net Income"], columns=dates),
    "annual_cash_flow": pd.DataFrame(
        [[12e9,8e9,5e9,3e9], [10e9,6e9,4e9,2e9]],
        index=["Operating Cash Flow", "Free Cash Flow"], columns=dates),
    "quarterly_income_statement": pd.DataFrame(
        [[12e9,10e9], [2,1.5]], index=["Total Revenue", "Diluted EPS"], columns=quarters),
    "quarterly_cash_flow": pd.DataFrame(
        [[4e9,3e9], [3e9,2e9]], index=["Operating Cash Flow", "Free Cash Flow"], columns=quarters),
}
payload = build_financial_evidence_payload("TEST", financials)
from app.services.bucket_hints import build_strategy_bucket_hints
from app.services.opportunity_profile import build_opportunity_profile
from app.data_sources.market_data import classify_quote_quality
from datetime import datetime, timezone
now = datetime(2026,9,9,14,tzinfo=timezone.utc)
quality = classify_quote_quality(requested_exchange='NASDAQ', observed_at=now,
    quote_timestamp=now, broker_clock={'source':'alpaca_paper_clock',
    'timestamp':now.isoformat(), 'is_open':True, 'next_close':'2026-09-09T20:00:00Z',
    'next_open':'2026-09-10T13:30:00Z'},
    require_broker_clock=True)
profile = build_opportunity_profile({'market_snapshot':{
    'currentPrice':100, 'averageVolume':1e6, 'alpacaBidPrice':99.98, 'alpacaAskPrice':100.02,
    'alpacaSpreadBps':4, 'alpacaQuoteTimestamp':now.isoformat(), 'quote_quality':quality},
    'technical':{'indicator_values':{'rsi':58, 'atr_pct':.025, 'volume_ratio':1.7}},
    'market_rank':{'price':100, 'return_20d':.08, 'return_60d':.18,
                   'volume_ratio':1.7, 'atr_pct':.025, 'trend_score':.9},
    'data_quality':{'coverage_ratio':.9}})
assert profile['status'] == 'qualified', profile
hints = build_strategy_bucket_hints({'growth_score':1, 'momentum_score':.9,
    'technical_vote_score':.8, 'volume_ratio':1.7, 'revenue_growth':.35},
    {'sector':'Technology'})
emit({"symbol": "TEST", "metadata": {**hints, "data_bundle": {
    "financial_inputs": payload, 'opportunity_profile':profile}}})
'''

FUNDAMENTAL = r'''
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
with patch("app.main.run_analysis", return_value={"error": "fixture_primary_unavailable"}):
    response = client.post("/analyze", json={"ticker": "TEST", "prefetched_data": payload},
                           headers={"X-Correlation-ID": "decision-contract-fixture"})
    assert response.status_code == 200, response.text
    positive = response.json()
    payload["metadata"]["data_bundle"]["financial_inputs"]["values"]["Operating Cash Flow"] = -1
    rejected = client.post("/analyze", json={"ticker": "TEST", "prefetched_data": payload}).json()
assert positive["data"]["action"] == "buy", positive
assert rejected["data"]["action"] != "buy", rejected
assert "negative_operating_cash_flow" in rejected["data"]["risk_flags"]
emit({"positive": positive, "negative": rejected})
'''

TECHNICAL = r'''
import numpy as np
import pandas as pd
from unittest.mock import patch
from fastapi.testclient import TestClient
try:
    from app.main import app
    service_module = "app.service"
except ModuleNotFoundError:
    # Technical's existing Docker image copies app/ directly into /app.
    from main import app
    service_module = "service"
close = np.r_[np.linspace(50,100,230), np.linspace(100,160,15),
              np.linspace(160,105,12), np.repeat(105.,15)]
frame = pd.DataFrame({"Open":close, "High":close+1, "Low":close-1,
                      "Close":close, "Volume":1e6},
                     index=pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=len(close), freq="D"))
with patch(service_module + ".get_stock_data", return_value=frame):
    response = TestClient(app).post("/analyze", json={"ticker": "TEST", "timeframe": "1d"},
                                    headers={"X-Correlation-ID": "decision-contract-fixture"})
    assert response.status_code == 200, response.text
    positive = response.json()
assert positive["correlation_id"] == "decision-contract-fixture"
assert positive["data"]["action"] == "buy", positive
assert all(row["passed"] for row in positive["data"]["decision_trace"]["buy_conditions"])
short = frame.tail(50)
with patch(service_module + ".get_stock_data", return_value=short):
    rejected = TestClient(app).post("/analyze", json={"ticker": "TEST", "timeframe": "1d"}).json()
assert rejected["status"] == "error" and rejected["data"]["action"] == "hold"
emit({"positive": positive, "negative": rejected})
'''

MANAGER = r'''
from decimal import Decimal
from app.discover_allocation import build_discover_allocation_plan, enrich_ranked_candidates_with_buckets, select_candidates_by_bucket
from app.discover_report_builder import build_selected_positions
from app.workflows.analysis_workflow import process_agent_response
from app.synthesis import get_weighted_verdict_trace
from app.services.scanner_opportunity_service import evaluate_scanner_candidate_opportunity
scanner_gate = evaluate_scanner_candidate_opportunity(payload['scanner'],
    profile_required=True, live_spread_required=True)
assert scanner_gate['allowed'], scanner_gate
technical = process_agent_response(payload["technical"]["positive"], "technical")
fundamental = process_agent_response(payload["fundamental"]["positive"], "fundamental")
trace = get_weighted_verdict_trace(technical.action, technical.score,
                                 fundamental.action, fundamental.score, "TEST")
assert trace["verdict"] in {"buy", "strong_buy"}, trace
assert get_weighted_verdict_trace("hold", .99, "hold", .99, "TEST")["verdict"] == "hold"
assert get_weighted_verdict_trace(technical.action, technical.score, "hold", .55, "TEST")["verdict"] == "buy"
invalid = process_agent_response(payload["technical"]["negative"], "technical")
assert invalid is None  # Error envelopes cannot contribute a directional vote.
ranked = enrich_ranked_candidates_with_buckets([{
    "symbol": "TEST", "analysis": {"ticker": "TEST", "final_verdict": trace["verdict"],
        "raw_data": {"technical": payload["technical"]["positive"], "fundamental": payload["fundamental"]["positive"]},
        "status": "complete", "details": {"technical": payload["technical"]["positive"],
        "fundamental": payload["fundamental"]["positive"]}},
    "scanner_candidate": payload['scanner'],
    "score_breakdown": {"final_opportunity_score": .8}}])
snapshot = payload["portfolio"]["positive"]["data"]
plan = build_discover_allocation_plan(ranked, Decimal(str(snapshot["equity"])))
selection = select_candidates_by_bucket(ranked)
positions = build_selected_positions(ranked=ranked, allocation_plan=plan, bucket_selection=selection)
assert len(positions) == 1, selection
for position in positions:
    assert position["allocation_weight"] == position["target_value"] / snapshot["equity"]
assert ranked[0]["evidence_summary"]["classification_rule_trace"]["schema_version"] == "bucket-classification-trace.v1"
emit({"aggregation": trace, "risk_pass": None, "execution_authorized": False,
      "portfolio_selection": selection, "selected_positions": positions,
      "ranked": ranked,
      "scanner_gate": scanner_gate,
      "reason_code": "TEST_FIXTURE_HAS_NO_EXECUTION_AUTHORITY"})
'''

PORTFOLIO = r'''
import os
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
headers = {"X-API-KEY": os.getenv("PORTFOLIO_AGENT_API_KEY", "dev_portfolio_key"),
           "X-Correlation-ID": "decision-contract-fixture"}
response = client.post("/portfolio/allocation", json={"equity": 100000, "cash": 100000, "positions": []}, headers=headers)
assert response.status_code == 200, response.text
positive = response.json()
assert positive["correlation_id"] == headers["X-Correlation-ID"]
rejected = client.post("/portfolio/allocation", json={"equity": 100000, "cash": 100000,
    "target_bucket_weights": {"core_dividend": "Infinity"}}, headers=headers)
assert rejected.status_code == 422, rejected.text
assert rejected.json()["correlation_id"] == headers["X-Correlation-ID"]
emit({"positive": positive, "invalid_snapshot": rejected.json()})
'''


def run_stage(repo, code, payload, args, rpc=None):
    read_payload = "json.loads(sys.stdin.readline())" if rpc else "json.load(sys.stdin)"
    program = ("import json,sys,os,socket\n"
               "def deny_network(*a, **k): raise AssertionError('Fixture forbids real network I/O')\n"
               "socket.socket.connect=deny_network\n"
               "os.environ.update(TRADING_MODE='PAPER', ALLOW_LIVE_TRADING='false')\n"
               f"payload={read_payload}\n"
               "def emit(value): print('DECISION_E2E_JSON=' + json.dumps(value))\n" + code)
    if args.local_root:
        cwd = args.local_root / repo
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(cwd), str(cwd / "src"), str(cwd / "app"), env.get("PYTHONPATH", "")])
        python_root = getattr(args, "python_root", None)
        interpreter = str(python_root / repo / "bin" / "python") if python_root else sys.executable
        command = [interpreter, "-c", program]
    else:
        cwd, env = None, None
        command = ["docker", "compose", "-f", "docker-compose.yml", "-f", args.compose_override,
                   "--profile", "backtest", "exec", "-T", "-e",
                   "PYTHONPATH=/app:/app/app:/tmp/decision-contract-deps",
                   repo.lower().replace("_", "-"),
                   "/opt/venv/bin/python" if repo == "Execution_Agent" else "python",
                   "-c", program]
    if rpc:
        return run_rpc(command, cwd, env, payload, rpc)
    result = subprocess.run(command, input=json.dumps(payload), text=True, capture_output=True,
                            cwd=cwd, env=env, timeout=120, check=False)
    if result.returncode:
        raise RuntimeError(f"{repo} decision contract failed (exit {result.returncode}):\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}")
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("DECISION_E2E_JSON="):
            return json.loads(line.split("=", 1)[1])
    raise RuntimeError(f"{repo} did not emit its JSON contract")


def run_rpc(command, cwd, env, payload, rpc):
    """Bounded JSON transport between isolated repository runtimes, not agents."""
    with tempfile.TemporaryFile(mode="w+t") as errors:
        process = subprocess.Popen(command, cwd=cwd, env=env, text=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, bufsize=1)
        messages = queue.Queue()
        def read_lines():
            for line in process.stdout:
                messages.put(line)
            messages.put(None)
        threading.Thread(target=read_lines, daemon=True).start()
        deadline = time.monotonic() + 120
        try:
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
            result = None
            while True:
                line = messages.get(timeout=max(.01, deadline - time.monotonic()))
                if line is None:
                    break
                if line.startswith("DECISION_E2E_RPC="):
                    answer = rpc(json.loads(line.split("=", 1)[1]))
                    process.stdin.write(json.dumps(answer) + "\n")
                    process.stdin.flush()
                elif line.startswith("DECISION_E2E_JSON="):
                    result = json.loads(line.split("=", 1)[1])
            process.wait(timeout=5)
            if process.returncode or result is None:
                errors.seek(0)
                raise RuntimeError("Paper path failed: " + errors.read()[-6000:])
            return result
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-root", type=Path)
    parser.add_argument("--python-root", type=Path, help="Isolated local environments named after each repository")
    parser.add_argument("--compose-override", default="/tmp/agent-contract-compose.yml")
    parser.add_argument("--output", type=Path, default=Path("reports/decision-contract-e2e.json"))
    args = parser.parse_args()
    scanner = run_stage("Scanner_Agent", SCANNER, {}, args)
    fundamental = run_stage("Fundamental_Agent", FUNDAMENTAL, scanner, args)
    technical = run_stage("Technical_Agent", TECHNICAL, {}, args)
    portfolio = run_stage("Portfolio_Agent", PORTFOLIO, {}, args)
    manager = run_stage("Manager_Agent", MANAGER, {"scanner": scanner, "technical": technical, "fundamental": fundamental, "portfolio": portfolio}, args)
    backtest = run_stage("Backtest_Agent", paper_path_fixture.BACKTEST, {}, args)
    execution_packets = []
    def route(packet):
        repo = packet["service"]
        if repo == "Execution_Agent" and packet['request']['path'] == '/execute/batch':
            execution_packets.append(packet)
        code = {"Risk_Agent": paper_path_fixture.RISK, "Execution_Agent": paper_path_fixture.EXECUTION}[repo]
        return run_stage(repo, code, packet, args)
    paper = run_stage("Manager_Agent", paper_path_fixture.MANAGER,
                      {"manager": manager, "backtest": backtest}, args, rpc=route)
    assert len(execution_packets) == 1, execution_packets
    scenarios = {name: run_stage('Execution_Agent', paper_path_fixture.EXECUTION,
        {**execution_packets[0], 'scenario':name}, args)
        for name in ('stale_session', 'malformed_clock', 'partial_fill', 'timeout')}
    report = {"schema_version": "decision-contract-e2e.v1", "data_source": "deterministic_test_fixtures",
              "scanner": scanner, "technical": technical, "fundamental": fundamental, "manager": manager, "portfolio": portfolio,
              "synthetic_backtest": backtest, "paper_adapter_integration": paper,
              "execution_scenarios": scenarios,
              "scenario_coverage": {
                  "HOLD": "Manager production synthesis: HOLD votes stay HOLD",
                  "candidate_oos_rejection": "Actual flat-price synthetic backtest and VALIDATED promotion rejected",
                  "nested_oos_rejection": "OOS_PASSED-only promotion denied; no robustness authority inferred",
                  "portfolio_rejection": "Actual Portfolio API rejects non-finite target weights (422)",
                  "risk_rejection": "Actual Risk API rejects excessive portfolio exposure",
                  "emergency_halt": "Actual Risk API mandatory veto",
                  "valid_buy": "Fresh Scanner/Technical/Fundamental/Manager fixture integration",
                  "execution_authorization": "Manager persisted Risk approval consumed by Execution; fixture authority denied separately",
                  "broker_accepted": "Actual Alpaca adapter against HTTP mock only",
                  "same_decision_replay": "Same persisted order: one mock submission",
                  "workflow_retry": "New ExecutionService with same database: one mock submission",
                  "stale_session": "Zero mock submissions; session_unverified",
                  "malformed_broker_clock": "Zero mock submissions; session_unverified",
                  "partial_fill": "Persisted partial fill identity; replay and retry submission count one",
                  "execution_timeout": "Response lost after submission; retry blocked pending reconciliation"
              },
              "checks": {"observed_fiscal_dates_preserved": True, "evidence_can_generate_buy": True,
                         "negative_cash_flow_blocks_fundamental_buy": True,
                         "insufficient_bars_fail_closed": True, "hold_score_cannot_create_buy": True,
                         "portfolio_snapshot_contract": True, "bucket_selection_from_agent_evidence": True,
                         "passing_candidate_reaches_paper_adapter_mock": True,
                         "risk_emergency_halt_blocks": True, "manager_and_execution_replay_safe": True,
                         "real_network_forbidden": True},
              "execution_authorized": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"checks": report["checks"], "execution_authorized": False}))


if __name__ == "__main__":
    main()
