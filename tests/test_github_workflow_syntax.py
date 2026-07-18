from pathlib import Path

import yaml


WORKFLOW_DIR = Path(".github/workflows")


def test_all_github_workflows_are_valid_yaml():
    workflow_paths = sorted(WORKFLOW_DIR.glob("*.yml"))

    assert workflow_paths
    for path in workflow_paths:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict), path
        assert "jobs" in parsed, path
