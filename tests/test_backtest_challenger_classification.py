from scripts.classify_backtest_challengers import build_report


def _strategy(
    strategy_id: str,
    *,
    score: float,
    failed: set[str],
) -> dict:
    gates = {
        "candidate_oos_kill_switch_safety": True,
        "candidate_oos_window_count": True,
        "candidate_oos_worst_max_drawdown": True,
        "candidate_oos_median_profit_factor": True,
        "candidate_oos_profitable_window_rate": True,
        "candidate_oos_median_sharpe_ratio": True,
    }
    for gate in failed:
        gates[gate] = False
    return {
        "strategy_id": strategy_id,
        "strategy": "sma_crossover",
        "score": score,
        "eligible": False,
        "gates": gates,
        "candidate_oos": {
            "median_sharpe_ratio": 0.45,
            "median_profit_factor": 1.25,
            "profitable_window_rate": 0.67,
            "worst_max_drawdown": -0.08,
            "evaluated_windows": 6,
        },
        "disqualification_reasons": sorted(failed),
    }


def item(symbol: str, *, failed: set[str], status: str = "no_eligible_strategy") -> dict:
    best = _strategy("sma-crossover-balanced-v1", score=0.30, failed=failed)
    ranked = [best]
    if status == "no_eligible_strategy" and failed == {"candidate_oos_median_sharpe_ratio"}:
        ranked.extend(
            [
                _strategy(
                    "sma-crossover-fast-v1",
                    score=0.28,
                    failed={"candidate_oos_median_sharpe_ratio"},
                ),
                _strategy(
                    "mean-reversion-fast-v1",
                    score=0.26,
                    failed={"candidate_oos_median_sharpe_ratio"},
                ),
                _strategy(
                    "weak-strategy-v1",
                    score=0.25,
                    failed={"candidate_oos_median_profit_factor"},
                ),
            ]
        )
    return {
        "symbol": symbol,
        "status": status,
        "selected_strategy_id": "s1" if status == "eligible_strategy_found" else None,
        "published": status == "eligible_strategy_found",
        "selection": {
            "best_overall": best,
            "ranked_results": ranked,
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


def test_challenger_exposes_up_to_three_observation_safe_strategy_configs() -> None:
    result = build_report(
        report(item("BSX", failed={"candidate_oos_median_sharpe_ratio"}))
    )
    row = result["items"][0]
    assert row["shadow_strategy_candidate_count"] == 3
    assert [entry["strategy_id"] for entry in row["shadow_strategy_candidates"]] == [
        "sma-crossover-balanced-v1",
        "sma-crossover-fast-v1",
        "mean-reversion-fast-v1",
    ]
    assert result["shadow_strategy_observation_count"] == 3
    assert all(
        entry["broker_order_authorized"] is False
        and entry["production_promotion_authorized"] is False
        for entry in row["shadow_strategy_candidates"]
    )


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
    assert result["items"][0]["shadow_strategy_candidates"] == []


def test_safety_gate_failure_cannot_enter_challenger_lane() -> None:
    result = build_report(
        report(item("XYZ", failed={"candidate_oos_worst_max_drawdown"}))
    )
    assert result["challenger_symbols"] == []
    assert result["items"][0]["challenger_observation_enabled"] is False
    assert result["items"][0]["shadow_strategy_candidates"] == []


def test_production_eligible_stays_out_of_challenger_lane() -> None:
    result = build_report(report(item("NVDA", failed=set(), status="eligible_strategy_found")))
    assert result["production_eligible_symbols"] == ["NVDA"]
    assert result["challenger_symbols"] == []
    assert result["items"][0]["broker_eligible"] is True
    assert result["items"][0]["shadow_strategy_candidates"] == []
