from __future__ import annotations

from decimal import Decimal

from app.discover_report_builder import (
    build_position_analysis_payloads,
    build_selected_positions,
)
from app.services.exposure_service import (
    clear_position_snapshot,
    current_position_snapshot,
    total_position_exposure,
)
from app.services.pre_risk_capacity_service import (
    CAPACITY_POLICY_VERSION,
    apply_pre_risk_capacity_selection,
)


def _analysis(symbol: str, sector: str = "Industrials"):
    return {
        "ticker": symbol,
        "final_verdict": "buy",
        "status": "complete",
        "raw_data": {
            "fundamental": {
                "data": {
                    "sector": sector,
                    "current_price": 100.0,
                }
            },
            "technical": {
                "data": {
                    "current_price": 100.0,
                    "sector": sector,
                }
            },
        },
    }


def _ranked(symbols):
    return [
        {
            "symbol": symbol,
            "strategy_bucket": "value_rebound",
            "bucket_confidence": 0.80,
            "bucket_classification_status": "classified",
            "bucket_classification_reasons": ["test"],
            "bucket_classifier_version": "manager-strategy-bucket-v3",
            "strategy_bucket_classification": {
                "bucket": "value_rebound",
                "status": "classified",
                "confidence": 0.80,
                "evidence_gate_passed": True,
            },
            "evidence_gate_passed": True,
            "evidence_summary": {
                "evidence_versions": {},
                "evidence_statuses": {},
                "source_conflicts": [],
            },
            "analysis": _analysis(symbol),
            "scanner_candidate": {},
            "score_breakdown": {
                "final_opportunity_score": 0.80 - index * 0.01,
                "strategy_bucket": "value_rebound",
            },
        }
        for index, symbol in enumerate(symbols)
    ]


def _allocation_plan(symbols, *, portfolio_value=100_000):
    return {
        "buckets": {
            "core_dividend": {
                "target_value": portfolio_value * 0.50,
                "max_symbol_value": portfolio_value * 0.10,
                "candidates": [],
            },
            "value_rebound": {
                "target_weight": 0.30,
                "target_value": portfolio_value * 0.30,
                "max_symbol_value": portfolio_value * 0.07,
                "candidates": [
                    {
                        "symbol": symbol,
                        "suggested_max_value": portfolio_value * 0.07,
                        "suggested_equal_weight_value": portfolio_value * 0.30,
                    }
                    for symbol in symbols
                ],
            },
            "news_momentum": {
                "target_value": portfolio_value * 0.20,
                "max_symbol_value": portfolio_value * 0.03,
                "candidates": [],
            },
        }
    }


def _selection(selected, overflow=(), *, limit=1):
    def row(symbol):
        return {
            "symbol": symbol,
            "strategy_bucket": "value_rebound",
            "bucket_confidence": 0.80,
            "bucket_classification_status": "classified",
            "evidence_gate_passed": True,
            "final_verdict": "buy",
            "score_breakdown": {"final_opportunity_score": 0.80},
        }

    return {
        "core_dividend": {
            "limit": 0,
            "eligible_count": 0,
            "selected_count": 0,
            "selected": [],
            "overflow": [],
        },
        "value_rebound": {
            "limit": limit,
            "eligible_count": len(selected) + len(overflow),
            "selected_count": len(selected),
            "selected": [row(symbol) for symbol in selected],
            "overflow": [row(symbol) for symbol in overflow],
        },
        "news_momentum": {
            "limit": 0,
            "eligible_count": 0,
            "selected_count": 0,
            "selected": [],
            "overflow": [],
        },
        "summary": {"total_selected": len(selected)},
    }


def _position(
    symbol,
    market_value,
    *,
    bucket="value_rebound",
    sector=None,
):
    result = {
        "symbol": symbol,
        "quantity": 1,
        "current_market_price": market_value,
        "market_value": market_value,
        "strategy_bucket": bucket,
    }
    if sector:
        result["sector"] = sector
    return result


def test_overweight_existing_symbol_is_skipped_and_overflow_is_promoted():
    ranked = _ranked(["ADBE", "AMSC"])
    result = apply_pre_risk_capacity_selection(
        ranked=ranked,
        allocation_plan=_allocation_plan(["ADBE", "AMSC"]),
        bucket_selection=_selection(["ADBE"], ["AMSC"]),
        positions=[_position("ADBE", 22_000)],
        portfolio_value=100_000,
    )

    value = result["bucket_selection"]["value_rebound"]
    assert [row["symbol"] for row in value["selected"]] == ["AMSC"]
    assert value["selected"][0]["capacity_fallback_promoted"] is True
    assert value["selected"][0]["target_value"] == 7_000.0
    assert value["selected"][0]["capacity_incremental_value"] == 7_000.0
    assert value["capacity_skipped"][0]["symbol"] == "ADBE"
    assert value["capacity_skipped"][0]["capacity_skip_reason"] == (
        "current_symbol_exposure_at_or_above_limit"
    )
    assert result["summary"] == {
        "considered_count": 2,
        "selected_count": 1,
        "skipped_count": 1,
        "promoted_count": 1,
    }


def test_existing_symbol_below_cap_is_resized_to_remaining_capacity():
    result = apply_pre_risk_capacity_selection(
        ranked=_ranked(["VALUE"]),
        allocation_plan=_allocation_plan(["VALUE"]),
        bucket_selection=_selection(["VALUE"]),
        positions=[_position("VALUE", 5_000)],
        portfolio_value=100_000,
    )

    selected = result["bucket_selection"]["value_rebound"]["selected"][0]
    assert selected["target_value"] == 7_000.0
    assert selected["capacity_incremental_value"] == 2_000.0
    assert selected["pre_risk_capacity"]["current_symbol_exposure"] == 5_000.0
    assert selected["pre_risk_capacity"]["max_symbol_exposure"] == 7_000.0


def test_remaining_capacity_below_minimum_trade_is_skipped():
    result = apply_pre_risk_capacity_selection(
        ranked=_ranked(["VALUE"]),
        allocation_plan=_allocation_plan(["VALUE"]),
        bucket_selection=_selection(["VALUE"]),
        positions=[_position("VALUE", 6_700)],
        portfolio_value=100_000,
        minimum_incremental_value=500,
    )

    value = result["bucket_selection"]["value_rebound"]
    assert value["selected"] == []
    assert value["capacity_skipped"][0]["capacity_skip_reason"] == (
        "remaining_capacity_below_minimum_trade_value"
    )
    assert value["capacity_skipped"][0]["pre_risk_capacity"][
        "allowed_incremental_value"
    ] == 300.0


def test_bucket_capacity_is_applied_across_provisional_new_buys(monkeypatch):
    monkeypatch.setenv("MAX_VALUE_REBOUND_BUCKET_PCT", "0.10")
    monkeypatch.setenv("MAX_VALUE_REBOUND_SYMBOL_PCT", "0.07")
    result = apply_pre_risk_capacity_selection(
        ranked=_ranked(["ONE", "TWO"]),
        allocation_plan=_allocation_plan(["ONE", "TWO"]),
        bucket_selection=_selection(["ONE", "TWO"], limit=2),
        positions=[],
        portfolio_value=100_000,
    )

    selected = result["bucket_selection"]["value_rebound"]["selected"]
    assert [row["symbol"] for row in selected] == ["ONE", "TWO"]
    assert selected[0]["capacity_incremental_value"] == 7_000.0
    assert selected[1]["capacity_incremental_value"] == 3_000.0
    assert selected[1]["target_value"] == 3_000.0


def test_sector_capacity_can_block_new_candidate(monkeypatch):
    monkeypatch.setenv("MAX_SECTOR_EXPOSURE_PCT", "0.25")
    ranked = _ranked(["TECH2"])
    ranked[0]["analysis"] = _analysis("TECH2", sector="Technology")
    result = apply_pre_risk_capacity_selection(
        ranked=ranked,
        allocation_plan=_allocation_plan(["TECH2"]),
        bucket_selection=_selection(["TECH2"]),
        positions=[
            _position(
                "TECH1",
                25_000,
                bucket="core_dividend",
                sector="Technology",
            )
        ],
        portfolio_value=100_000,
    )

    skip = result["bucket_selection"]["value_rebound"][
        "capacity_skipped"
    ][0]
    assert skip["capacity_skip_reason"] == "sector_capacity_exhausted"
    assert skip["pre_risk_capacity"]["remaining_sector_capacity"] == 0.0


def test_position_snapshot_is_request_local_and_used_when_positions_omitted():
    clear_position_snapshot()
    exposure = total_position_exposure([_position("ADBE", 22_000)])
    assert exposure == Decimal("22000")
    assert len(current_position_snapshot()) == 1

    result = apply_pre_risk_capacity_selection(
        ranked=_ranked(["ADBE"]),
        allocation_plan=_allocation_plan(["ADBE"]),
        bucket_selection=_selection(["ADBE"]),
        positions=None,
        portfolio_value=100_000,
    )

    assert result["position_snapshot_source"] == "request_context"
    assert result["position_snapshot_count"] == 1
    assert result["bucket_selection"]["value_rebound"]["selected"] == []


def test_selected_position_uses_symbol_target_not_whole_bucket_target():
    ranked = _ranked(["NEW"])
    allocation_plan = _allocation_plan(["NEW"])
    capacity = apply_pre_risk_capacity_selection(
        ranked=ranked,
        allocation_plan=allocation_plan,
        bucket_selection=_selection(["NEW"]),
        positions=[],
        portfolio_value=100_000,
    )
    selected_positions = build_selected_positions(
        ranked=ranked,
        allocation_plan=allocation_plan,
        bucket_selection=capacity["bucket_selection"],
    )

    assert selected_positions[0]["bucket_target_value"] == 30_000.0
    assert selected_positions[0]["target_value"] == 7_000.0
    assert selected_positions[0]["target_value"] != selected_positions[0][
        "bucket_target_value"
    ]

    payload = build_position_analysis_payloads(
        ranked=ranked,
        selected_positions=selected_positions,
    )[0]
    assert payload["portfolio_context"]["target_value"] == 7_000.0
    assert payload["portfolio_context"]["bucket_target_value"] == 30_000.0
    assert payload["portfolio_context"]["capacity_policy_version"] == (
        CAPACITY_POLICY_VERSION
    )


def test_no_symbol_specific_rules_are_used():
    result = apply_pre_risk_capacity_selection(
        ranked=_ranked(["XYZQ"]),
        allocation_plan=_allocation_plan(["XYZQ"]),
        bucket_selection=_selection(["XYZQ"]),
        positions=[_position("XYZQ", 22_000)],
        portfolio_value=100_000,
    )

    skip = result["bucket_selection"]["value_rebound"][
        "capacity_skipped"
    ][0]
    assert skip["symbol"] == "XYZQ"
    assert skip["capacity_skip_reason"] == (
        "current_symbol_exposure_at_or_above_limit"
    )
