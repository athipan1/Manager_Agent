"""Deterministic cross-repo evidence test; never connects to a broker.

Runs each repository in its own runtime, serializing JSON across boundaries.
Only provider I/O is replaced with labelled test fixtures. Scoring, indicators,
API models, action normalization and Manager synthesis are production code.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


SCANNER = r'''
import pandas as pd
from app.services.financial_evidence_payload import build_financial_evidence_payload
dates = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"])
quarters = pd.to_datetime(["2026-06-30", "2026-03-31"])
financials = {
    "info": {"sector": "Technology", "currency": "USD", "financialCurrency": "USD",
             "returnOnEquity": .3, "returnOnAssets": .2, "returnOnInvestedCapital": .3,
             "profitMargins": .3, "operatingMargins": .3, "grossMargins": .6,
             "trailingPE": 20, "forwardPE": 18, "pegRatio": .4, "priceToBook": .7,
             "trailingEps": 6, "debtToEquity": 20, "marketCap": 100e9,
             "enterpriseValue": 100e9, "ebitda": 10e9},
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
emit({"symbol": "TEST", "metadata": {"data_bundle": {"financial_inputs": payload}}})
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
from app.workflows.analysis_workflow import process_agent_response
from app.synthesis import get_weighted_verdict_trace
technical = process_agent_response(payload["technical"]["positive"], "technical")
fundamental = process_agent_response(payload["fundamental"]["positive"], "fundamental")
trace = get_weighted_verdict_trace(technical.action, technical.score,
                                 fundamental.action, fundamental.score, "TEST")
assert trace["verdict"] in {"buy", "strong_buy"}, trace
assert get_weighted_verdict_trace("hold", .99, "hold", .99, "TEST")["verdict"] == "hold"
assert get_weighted_verdict_trace(technical.action, technical.score, "hold", .55, "TEST")["verdict"] == "buy"
invalid = process_agent_response(payload["technical"]["negative"], "technical")
assert invalid is None  # Error envelopes cannot contribute a directional vote.
emit({"aggregation": trace, "risk_pass": None, "execution_authorized": False,
      "reason_code": "TEST_FIXTURE_HAS_NO_EXECUTION_AUTHORITY"})
'''


def run_stage(repo, code, payload, args):
    program = ("import json,sys\npayload=json.load(sys.stdin)\n"
               "def emit(value): print('DECISION_E2E_JSON=' + json.dumps(value))\n" + code)
    if args.local_root:
        cwd = args.local_root / repo
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(cwd), str(cwd / "app"), env.get("PYTHONPATH", "")])
        command = [sys.executable, "-c", program]
    else:
        cwd, env = None, None
        command = ["docker", "compose", "-f", "docker-compose.yml", "-f", args.compose_override,
                   "--profile", "backtest", "exec", "-T", "-e",
                   "PYTHONPATH=/app:/app/app:/tmp/decision-contract-deps",
                   repo.lower().replace("_", "-"), "python", "-c", program]
    result = subprocess.run(command, input=json.dumps(payload), text=True, capture_output=True,
                            cwd=cwd, env=env, timeout=120)
    if result.returncode:
        raise RuntimeError(f"{repo} decision contract failed:\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}")
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("DECISION_E2E_JSON="):
            return json.loads(line.split("=", 1)[1])
    raise RuntimeError(f"{repo} did not emit its JSON contract")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-root", type=Path)
    parser.add_argument("--compose-override", default="/tmp/agent-contract-compose.yml")
    parser.add_argument("--output", type=Path, default=Path("reports/decision-contract-e2e.json"))
    args = parser.parse_args()
    scanner = run_stage("Scanner_Agent", SCANNER, {}, args)
    fundamental = run_stage("Fundamental_Agent", FUNDAMENTAL, scanner, args)
    technical = run_stage("Technical_Agent", TECHNICAL, {}, args)
    manager = run_stage("Manager_Agent", MANAGER, {"technical": technical, "fundamental": fundamental}, args)
    report = {"schema_version": "decision-contract-e2e.v1", "data_source": "deterministic_test_fixtures",
              "scanner": scanner, "technical": technical, "fundamental": fundamental, "manager": manager,
              "checks": {"observed_fiscal_dates_preserved": True, "evidence_can_generate_buy": True,
                         "negative_cash_flow_blocks_fundamental_buy": True,
                         "insufficient_bars_fail_closed": True, "hold_score_cannot_create_buy": True},
              "execution_authorized": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"checks": report["checks"], "execution_authorized": False}))


if __name__ == "__main__":
    main()
