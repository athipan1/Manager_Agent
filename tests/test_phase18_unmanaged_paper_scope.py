"""Phase 18 contract tests for strict external / AI-managed Paper separation."""
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from app.hourly_paper_runtime import RuntimeSafetyError
from app.services.order_builder import OrderBuildError, order_request_from_decision
from app.unmanaged_broker_holdings import approved_unmanaged_symbols, require_matching_database_scope
from scripts.hourly_portfolio_cycle import finalize_cycle, protection_gaps
from scripts.reconcile_paper_protection import _attention_rows, _protection_summary


EXTERNAL = {
    "AGCO", "CEG", "DE", "FDX", "NVDA", "PFE",
    "PSQ", "REGN", "SH", "SMCI", "OXY", "VST",
}


def test_operator_policy_is_paper_only_and_exactly_account_scoped():
    assert approved_unmanaged_symbols(1) == EXTERNAL
    assert approved_unmanaged_symbols(2) == set()


def test_manager_and_database_must_agree_on_full_external_scope():
    db = {
        "mismatch": {
            "diagnostics": {
                "strategy_buckets": {"configured_unmanaged_symbols": sorted(EXTERNAL)}
            }
        }
    }
    assert require_matching_database_scope(db, 1) == EXTERNAL
    db["mismatch"]["diagnostics"]["strategy_buckets"]["configured_unmanaged_symbols"] = ["AGCO"]
    with pytest.raises(RuntimeSafetyError, match="not identical"):
        require_matching_database_scope(db, 1)


def test_unmanaged_protection_does_not_block_managed_protection():
    diagnostics = {
        "data": {
            "positions": [
                {"symbol": "NVDA", "protection_status": "unprotected", "unprotected_quantity": 2},
                {"symbol": "AAPL", "protection_status": "unprotected", "unprotected_quantity": 1},
            ]
        }
    }
    gaps = protection_gaps(diagnostics, excluded_symbols=EXTERNAL)
    assert [row["symbol"] for row in gaps] == ["AAPL"]
    assert [row["symbol"] for row in _attention_rows(diagnostics["data"])] == ["AAPL"]
    summary = _protection_summary(diagnostics["data"])
    assert summary["position_count"] == 1
    assert summary["unmanaged_read_only_count"] == 1


@pytest.mark.parametrize("symbol", ["NVDA", "AGCO", "OXY"])
def test_manager_never_builds_ai_execution_order_for_external_stock(symbol):
    with pytest.raises(OrderBuildError, match="unmanaged"):
        order_request_from_decision(
            {"symbol": symbol, "action": "buy", "risk_approval_id": "fake"},
            1,
        )


def test_other_accounts_do_not_inherit_account_one_external_allowlist():
    # Account scope is explicit; the ordinary risk/quantity guards still apply.
    with pytest.raises(OrderBuildError) as exc:
        order_request_from_decision(
            {"symbol": "NVDA", "action": "buy", "risk_approval_id": "fake"},
            2,
        )
    assert "unmanaged" not in str(exc.value)


def _finalize_with_positions(rows, *, account_id="1"):
    operations = []
    client = SimpleNamespace(
        execution="execution",
        database="database",
        post=lambda target, route, payload: operations.append((target, route)) or {},
        get=lambda target, route: {"data": {"positions": rows}}
            if route == "/broker/protection-diagnostics"
            else {"data": {}},
    )
    preflight = {"portfolio_cycle_id": "paper-contract-test", "runtime": {"paper_automation": True}}
    report = {"candidate_cycle": {"manager_response": {"data": {"execution": {"created": []}}}}}
    with patch("scripts.hourly_portfolio_cycle._reconcile", return_value={"status": "synced"}):
        result = finalize_cycle(
            client, preflight=preflight, account_id=account_id, report=report
        )
    return result, operations


def test_final_protection_ignores_only_reviewed_manual_paper_positions():
    # All 12 manual holdings may lack AI-managed TP/SL, but they remain in
    # broker reconciliation. A new AI-owned or unknown symbol may not bypass.
    rows = [
        {"symbol": sym, "protection_status": "unprotected", "unprotected_quantity": 1}
        for sym in sorted(EXTERNAL)
    ]
    result, calls = _finalize_with_positions(rows)
    assert result["status"] == "completed"
    assert any(route.startswith("/reconciliation/run-once") for _, route in calls)
    assert any(route == "/review-history" for _, route in calls)
    assert len(result["post_execution_protection"]["positions"]) == len(EXTERNAL)


@pytest.mark.parametrize("symbol", ["AAPL", "VRT"])
def test_final_protection_never_exempts_unknown_or_ai_managed(symbol):
    rows = [
        {"symbol": "OXY", "protection_status": "unprotected", "unprotected_quantity": 1},
        {"symbol": symbol, "protection_status": "unprotected", "unprotected_quantity": 1},
    ]
    with pytest.raises(RuntimeSafetyError, match="unsafe gap"):
        _finalize_with_positions(rows)


def test_other_accounts_cannot_borrow_account_one_manual_protection_exemption():
    with pytest.raises(RuntimeSafetyError, match="unsafe gap"):
        _finalize_with_positions([
            {"symbol": "OXY", "protection_status": "unprotected", "unprotected_quantity": 1}
        ], account_id="2")
