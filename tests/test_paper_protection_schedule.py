from pathlib import Path


def test_paper_protection_workflow_has_weekday_retry_schedule():
    workflow = Path('.github/workflows/paper-protection-reconciliation.yml').read_text(encoding='utf-8')
    assert 'schedule:' in workflow
    assert "cron: '15 * * * 1-5'" in workflow
    assert "github.event_name == 'schedule'" in workflow
    assert "github.event_name == 'schedule' && 'true'" in workflow
