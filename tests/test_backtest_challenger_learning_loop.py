from scripts.review_backtest_challenger_learning import build_learning_report


class Decision:
    def __init__(self, decision: str):
        self.decision = decision

    def model_dump(self, mode="json"):
        return {
            "decision": self.decision,
            "broker_order_authorized": False,
            "auto_promote": False,
        }


def _backtest_evidence(selection):
    return {
        "strategy_id": "sma-crossover-balanced-v1",
        "strategy_name": "sma_crossover",
        "observation_candidate": selection.get("near_miss") is True,
        "failed_candidate_oos_gates": ["candidate_oos_median_sharpe_ratio"],
    }


def _forward_evidence(summary):
    count = int(summary.get("observation_count") or 0)
    ready = (
        count >= 100
        and summary.get("profit_factor", 0) >= 1.1
        and summary.get("max_drawdown_pct", 1) <= 0.1
        and summary.get("average_cost_pct") is not None
    )
    return {
        "forward_review_ready": ready,
        "failed_gates": [] if ready else ["minimum_observations"],
    }


def _request(**kwargs):
    return kwargs


def _learn(request):
    return Decision(
        "request_human_promotion_review"
        if request["forward_evidence"]["forward_review_ready"]
        else "continue_shadow"
    )


def test_near_miss_without_forward_sample_stays_shadow_only():
    result = build_learning_report(
        {
            "data": {
                "items": [
                    {
                        "symbol": "TCOM",
                        "status": "no_eligible_strategy",
                        "selection": {"near_miss": True},
                    }
                ]
            }
        },
        {"performance": {"data": {"by_strategy": {}}}},
        build_backtest_evidence=_backtest_evidence,
        build_forward_evidence=_forward_evidence,
        build_learning_request=_request,
        evaluate_learning=_learn,
    )
    assert result["review_count"] == 1
    assert result["reviews"][0]["learning"]["decision"] == "continue_shadow"
    assert result["safety"]["broker_order_authorized"] is False


def test_single_strategy_100_observations_can_only_request_human_review():
    result = build_learning_report(
        {
            "data": {
                "items": [
                    {
                        "symbol": "TCOM",
                        "status": "no_eligible_strategy",
                        "selection": {"near_miss": True},
                    }
                ]
            }
        },
        {
            "performance": {
                "data": {
                    "by_strategy": {
                        "sma-crossover-balanced-v1": {
                            "observation_count": 100,
                            "profit_factor": 1.25,
                        }
                    },
                    "max_drawdown_pct": 0.05,
                    "average_cost_pct": 0.0005,
                }
            }
        },
        build_backtest_evidence=_backtest_evidence,
        build_forward_evidence=_forward_evidence,
        build_learning_request=_request,
        evaluate_learning=_learn,
    )
    review = result["reviews"][0]
    assert review["learning"]["decision"] == "request_human_promotion_review"
    assert review["learning"]["broker_order_authorized"] is False
