"""Phase 18 contract tests for strict external / AI-managed Paper separation."""
import pytest

from app.hourly_paper_runtime import RuntimeSafetyError
from app.services.order_builder import OrderBuildError, order_request_from_decision
from app.unmanaged_broker_holdings import approved_unmanaged_symbols, require_matching_database_scope
from scripts.hourly_portfolio_cycle import protection_gaps
from scripts.reconcile_paper_protection import _attention_rows, _protection_summary


EXTERNAL = {
    "AGCO", "CEG", "DE", "FDX", "NVDA", "PFE",
    "PSQ", "REGN", "SH", "SMCI", "VRT", "VST",
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


@pytest.mark.parametrize("symbol", ["NVDA", "AGCO", "VRT"])
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
