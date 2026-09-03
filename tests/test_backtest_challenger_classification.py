from scripts.classify_backtest_challengers import build_report


def item(symbol: str, *, failed: set[str], status: str = "no_eligible_strategy") -> dict:
    candidate_gates = {
        "candidate_oos_kill_switch_safety": True,
        "candidate_oos_window_count": True,
        "candidate_oos_worst_max_drawdown": True,
        "candidate_oos_median_profit_factor": True,
        "candidate_oos_profitable_window_rate": True,
        "candidate_oos_median_sharpe_ratio": True,
    }
    for gate in failed:
        candidate_gates[gate] = False
    return {
        "symbol": symbol,
        "status": status,
        "selected_strategy_id": "s1" if status == "eligible_strategy_found" else None,
        "published": status == "eligible_strategy_found",
        "selection": {
            "best_overall": {
                "gates": candidate_gates,
                "disqualification_reasons": sorted(failed),
            }
        },
    }


def report(*items: dict) -> dict:
    return {
        "data": {
            "all_succeeded": True,
            "selection_complete": True,
            "items": list(items),
        }
    }


def test_single_sharpe_near_miss_becomes_observation_only_challenger() -> None:
    result = build_report(
        report(item("BSX", failed={"candidate_oos_median_sharpe_ratio"}))
    )
    assert result["challenger_symbols"] == ["BSX"]
    row = result["items"][0]
    assert row["classification"] == "promising_not_robust"
    assert row["challenger_observation_enabled"] is True
    assert row["broker_eligible"] is False
    assert row["safety"]["risk_execution_authorized"] is False
    assert result["safety"]["may_submit_broker_order"] is False


def test_multiple_quality_failures_remain_clearly_not_ready() -> None:
    result = build_report(
        report(
            item(
                "SAFT",
                failed={
                    "candidate_oos_median_sharpe_ratio",
                    "candidate_oos_median_profit_factor",
                    "candidate_oos_profitable_window_rate",
                },
            )
        )
    )
    assert result["challenger_symbols"] == []
    assert result["clearly_not_ready_symbols"] == ["SAFT"]
    assert result["items"][0]["classification"] == "clearly_not_ready"


def test_safety_gate_failure_cannot_enter_challenger_lane() -> None:
    result = build_report(
        report(item("XYZ", failed={"candidate_oos_worst_max_drawdown"}))
    )
    assert result["challenger_symbols"] == []
    assert result["items"][0]["challenger_observation_enabled"] is False


def test_production_eligible_stays_out_of_challenger_lane() -> None:
    result = build_report(report(item("NVDA", failed=set(), status="eligible_strategy_found")))
    assert result["production_eligible_symbols"] == ["NVDA"]
    assert result["challenger_symbols"] == []
    assert result["items"][0]["broker_eligible"] is True
