from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/hourly-auto-trading.yml")


def test_dependencies_are_reconfirmed_after_drill_before_reconciliation():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    initial_wait = workflow.index("- name: Wait for required services")
    drill = workflow.index("- name: Exercise Risk emergency halt fail-closed drill")
    reconfirm = workflow.index(
        "- name: Reconfirm required services before portfolio reconciliation"
    )
    review = workflow.index(
        "- name: Review existing positions, orders, regime, exposure and protection"
    )

    assert initial_wait < drill < reconfirm < review

    step = workflow[reconfirm:review]
    assert "DATABASE_AGENT_URL: ${{ env.RUNTIME_DATABASE_AGENT_URL }}" in step
    assert "EXECUTION_AGENT_URL: http://localhost:8006" in step
    assert "python scripts/hourly_portfolio_cycle.py wait" in step


def test_hourly_workflow_has_two_bounded_dependency_readiness_barriers():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow.count("python scripts/hourly_portfolio_cycle.py wait") == 2
