from pathlib import Path


WORKFLOW = Path(".github/workflows/hourly-auto-trading.yml")


def test_hourly_checks_out_learning_for_paper_and_reviews_after_trade_gate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    checkout = "- name: Checkout Learning_Agent for challenger advisory review"
    review = "- name: Review Backtest challengers with Forward Performance and Learning"
    gate = "- name: Resolve controlled no-trade gate"
    risk = "- name: Recheck durable emergency halt before broker mutation"

    assert checkout in text
    checkout_block = text[text.index(checkout) : text.index(checkout) + 320]
    assert "paper_automation != 'true'" not in checkout_block
    assert "repository: athipan1/Learning_Agent" in checkout_block

    assert gate in text
    assert review in text
    assert risk in text
    assert text.index(gate) < text.index(review) < text.index(risk)
    assert "run: python scripts/review_backtest_challenger_learning.py" in text


def test_challenger_learning_remains_advisory_before_execution() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    review_index = text.index(
        "- name: Review Backtest challengers with Forward Performance and Learning"
    )
    execution_index = text.index(
        "- name: Run Manager candidate, Risk and guarded Execution cycle"
    )
    assert review_index < execution_index
