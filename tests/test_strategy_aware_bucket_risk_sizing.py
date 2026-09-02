from decimal import Decimal

from app import bucket_risk_bridge as bridge


def _candidate(score: float, *, mode: str = "strategy_aware"):
    return {
        "metadata": {
            "data_bundle": {
                "opportunity_profile": {
                    "status": "qualified",
                    "opportunity_score": score,
                    "qualification_policy": {
                        "mode": mode,
                        "generic_score": score,
                        "hard_execution_safe": True,
                        "hard_execution_thresholds_relaxed": False,
                    },
                }
            }
        }
    }


def _ranked(score: float, *, mode: str = "strategy_aware"):
    return [
        {
            "symbol": "ABC",
            "analysis": {
                "final_verdict": "buy",
                "raw_data": {
                    "technical": {
                        "data": {
                            "current_price": 100.0,
                            "indicators": {"stop_loss": 95.0},
                        }
                    }
                },
            },
            "scanner_candidate": _candidate(score, mode=mode),
        }
    ]


def _install_selection_and_gate(monkeypatch):
    selection = {
        "core_dividend": {"selected": []},
        "value_rebound": {
            "selected": [{"symbol": "ABC", "final_verdict": "buy"}]
        },
        "news_momentum": {"selected": []},
    }
    monkeypatch.setattr(bridge, "select_candidates_by_bucket", lambda *a, **k: selection)
    monkeypatch.setattr(
        bridge,
        "build_exposure_snapshot",
        lambda **kwargs: {"unprotected_positions": []},
    )
    monkeypatch.setattr(
        bridge,
        "evaluate_exposure_aware_trade_gate",
        lambda *a, **k: {
            "allowed": True,
            "rejection_codes": [],
            "maximum_order_value": 10_000.0,
        },
    )
    monkeypatch.setattr(bridge, "build_stock_risk_context", lambda *a, **k: {})


def test_half_size_strategy_aware_cap_reaches_assess_trade(monkeypatch):
    _install_selection_and_gate(monkeypatch)
    captured = {}

    def assess_trade(**kwargs):
        captured.update(kwargs)
        return {"approved": True, "action": "buy", "position_size": 10}

    result = bridge.build_bucket_risk_decisions(
        ranked=_ranked(0.65),
        portfolio_value=Decimal("100000"),
        positions=[],
        open_orders_exposure=Decimal("0"),
        session_context={},
        min_final_score=0.55,
        assess_trade_fn=assess_trade,
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.20"),
        margin_multiplier=Decimal("1"),
    )

    assert captured["max_position_pct"] == Decimal("0.100")
    assert captured["stock_risk_context"]["scanner_opportunity_size_multiplier"] == 0.5
    decision = result["bucket_risk_decisions"]["value_rebound"][0]
    assert decision["scanner_opportunity_size_multiplier"] == 0.5
    assert decision["base_max_position_pct"] == 0.2
    assert decision["effective_max_position_pct"] == 0.1


def test_quarter_size_strategy_aware_cap_reaches_assess_trade(monkeypatch):
    _install_selection_and_gate(monkeypatch)
    captured = {}

    def assess_trade(**kwargs):
        captured.update(kwargs)
        return {"approved": True, "action": "buy", "position_size": 5}

    bridge.build_bucket_risk_decisions(
        ranked=_ranked(0.58),
        portfolio_value=Decimal("100000"),
        positions=[],
        open_orders_exposure=Decimal("0"),
        session_context={},
        min_final_score=0.55,
        assess_trade_fn=assess_trade,
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.20"),
        margin_multiplier=Decimal("1"),
    )

    assert captured["max_position_pct"] == Decimal("0.0500")
    assert captured["stock_risk_context"]["scanner_opportunity_size_multiplier"] == 0.25


def test_generic_qualified_candidate_keeps_original_risk_cap(monkeypatch):
    _install_selection_and_gate(monkeypatch)
    captured = {}

    def assess_trade(**kwargs):
        captured.update(kwargs)
        return {"approved": True, "action": "buy", "position_size": 20}

    bridge.build_bucket_risk_decisions(
        ranked=_ranked(0.82, mode="generic"),
        portfolio_value=Decimal("100000"),
        positions=[],
        open_orders_exposure=Decimal("0"),
        session_context={},
        min_final_score=0.55,
        assess_trade_fn=assess_trade,
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.20"),
        margin_multiplier=Decimal("1"),
    )

    assert captured["max_position_pct"] == Decimal("0.20")
    assert captured["stock_risk_context"]["scanner_opportunity_size_multiplier"] == 1.0


def test_unverified_hard_safety_never_receives_a_reduced_risk_cap(monkeypatch):
    _install_selection_and_gate(monkeypatch)
    ranked = _ranked(0.65)
    profile = ranked[0]["scanner_candidate"]["metadata"]["data_bundle"]["opportunity_profile"]
    profile["qualification_policy"]["hard_execution_safe"] = False
    captured = {}

    def assess_trade(**kwargs):
        captured.update(kwargs)
        return {"approved": True, "action": "buy", "position_size": 20}

    bridge.build_bucket_risk_decisions(
        ranked=ranked,
        portfolio_value=Decimal("100000"),
        positions=[],
        open_orders_exposure=Decimal("0"),
        session_context={},
        min_final_score=0.55,
        assess_trade_fn=assess_trade,
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.20"),
        margin_multiplier=Decimal("1"),
    )

    assert captured["max_position_pct"] == Decimal("0.20")
