from pathlib import Path

from scripts.review_backtest_challenger_learning import _load_contracts


def test_cross_repo_loader_does_not_confuse_duplicate_app_packages(tmp_path: Path) -> None:
    manager = tmp_path / "Manager_Agent"
    manager.mkdir()

    backtest_app = tmp_path / "Backtest_Agent" / "app"
    backtest_app.mkdir(parents=True)
    (backtest_app / "challenger_evidence.py").write_text(
        "def build_challenger_evidence(value):\n    return {'source': 'backtest'}\n",
        encoding="utf-8",
    )

    performance_app = tmp_path / "Performance_Agent" / "app"
    performance_app.mkdir(parents=True)
    (performance_app / "forward_evidence.py").write_text(
        "def build_forward_evidence(value):\n    return {'source': 'performance'}\n",
        encoding="utf-8",
    )

    learning = tmp_path / "Learning_Agent" / "learning_agent"
    learning.mkdir(parents=True)
    (learning / "__init__.py").write_text("", encoding="utf-8")
    (learning / "backtest_shadow_feedback.py").write_text(
        "class BacktestShadowFeedbackRequest:\n"
        "    def __init__(self, **kwargs):\n        self.kwargs = kwargs\n\n"
        "def evaluate_backtest_shadow_feedback(value):\n    return {'source': 'learning'}\n",
        encoding="utf-8",
    )

    build_backtest, build_forward, request_type, evaluate = _load_contracts(manager)

    assert build_backtest({}) == {"source": "backtest"}
    assert build_forward({}) == {"source": "performance"}
    assert request_type(symbol="TCOM", strategy_id="s", backtest_evidence={}, forward_evidence={}).kwargs["symbol"] == "TCOM"
    assert evaluate(None) == {"source": "learning"}
