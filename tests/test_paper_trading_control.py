import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.paper_trading_control import (
    CLEAR_HALT_CONFIRMATION,
    HALT_CONFIRMATION,
    HALT_SCHEMA,
    HALT_TITLE,
    SOAK_SCHEMA,
    SOAK_TITLE,
    START_CONFIRMATION,
    ControlError,
    activate_emergency_halt,
    assert_emergency_halt_clear,
    emergency_control,
    finish_soak,
    new_soak_state,
    record_soak_cycle,
    soak_control,
)


NOW = datetime(2026, 7, 29, 6, 0, tzinfo=timezone.utc)


class FakeIssueClient:
    def __init__(self):
        self.issues = {}
        self.comments = []
        self.next_number = 1

    def find_open_issue(self, title):
        matches = [
            issue
            for issue in self.issues.values()
            if issue["title"] == title and issue["state"] == "open"
        ]
        if len(matches) > 1:
            raise ControlError("duplicate")
        return matches[0] if matches else None

    def get_issue(self, number):
        return self.issues[number]

    def create_issue(self, *, title, state):
        number = self.next_number
        self.next_number += 1
        issue = {
            "number": number,
            "title": title,
            "body": json.dumps(state),
            "state": "open",
        }
        self.issues[number] = issue
        return issue

    def update_issue(self, number, *, state, close=False):
        self.issues[number]["body"] = json.dumps(state)
        if close:
            self.issues[number]["state"] = "closed"
        return self.issues[number]

    def comment(self, number, body):
        self.comments.append((number, body))


def test_assert_clear_skips_simulator_and_blocks_paper_halt():
    client = FakeIssueClient()
    simulator = assert_emergency_halt_clear(
        client,
        env={"BROKER_MODE": "SIMULATOR", "DRY_RUN": "true"},
    )
    assert simulator["status"] == "not_required"

    activate_emergency_halt(
        client,
        reason="broker mismatch",
        now=NOW,
        source="test",
    )
    with pytest.raises(ControlError, match="emergency halt is active"):
        assert_emergency_halt_clear(
            client,
            env={"BROKER_MODE": "ALPACA", "DRY_RUN": "false"},
        )


def test_manual_halt_requires_confirmation_and_clear_closes_issue():
    client = FakeIssueClient()
    with pytest.raises(ControlError, match=HALT_CONFIRMATION):
        emergency_control(
            client,
            operation="activate",
            reason="test",
            confirmation="",
            now=NOW,
        )

    activated = emergency_control(
        client,
        operation="activate",
        reason="test",
        confirmation=HALT_CONFIRMATION,
        now=NOW,
    )
    assert activated["status"] == "activated"
    assert json.loads(client.issues[1]["body"])["schema_version"] == HALT_SCHEMA

    cleared = emergency_control(
        client,
        operation="clear",
        reason="verified",
        confirmation=CLEAR_HALT_CONFIRMATION,
        now=NOW,
    )
    assert cleared["status"] == "cleared"
    assert client.issues[1]["state"] == "closed"


def test_soak_start_is_durable_and_refuses_parallel_production_schedule():
    client = FakeIssueClient()
    with pytest.raises(ControlError, match="Disable HOURLY"):
        soak_control(
            client,
            operation="start",
            duration_hours=24,
            confirmation=START_CONFIRMATION,
            now=NOW,
            production_schedule_enabled=True,
        )

    started = soak_control(
        client,
        operation="start",
        duration_hours=24,
        confirmation=START_CONFIRMATION,
        now=NOW,
        production_schedule_enabled=False,
    )
    assert started["should_run"] is True
    assert started["issue_number"] == 1
    state = json.loads(client.issues[1]["body"])
    assert state["schema_version"] == SOAK_SCHEMA
    assert state["expected_min_cycles"] == 24


def test_failed_soak_cycle_closes_soak_and_activates_halt(tmp_path, monkeypatch):
    client = FakeIssueClient()
    issue = client.create_issue(
        title=SOAK_TITLE,
        state=new_soak_state(duration_hours=24, now=NOW),
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "77")

    result = record_soak_cycle(
        client,
        number=issue["number"],
        workflow_result="failure",
        audit_outcome="failure",
        evidence_path=tmp_path / "missing.json",
        run_url="https://github.example/run/77",
        now=NOW + timedelta(hours=1),
    )

    assert result["cycle_result"] == "failure"
    assert client.issues[issue["number"]]["state"] == "closed"
    halt = client.find_open_issue(HALT_TITLE)
    assert halt is not None
    assert json.loads(halt["body"])["status"] == "active"


def test_clean_24_cycle_soak_is_promotion_ready():
    client = FakeIssueClient()
    state = new_soak_state(duration_hours=24, now=NOW)
    state.update({"cycle_count": 24, "success_count": 24})
    issue = client.create_issue(title=SOAK_TITLE, state=state)

    result = finish_soak(
        client,
        issue=issue,
        state=state,
        now=NOW + timedelta(hours=24),
    )

    assert result["status"] == "completed"
    assert result["state"]["promotion_ready"] is True
    assert client.issues[issue["number"]]["state"] == "closed"


def test_warning_prevents_soak_promotion():
    client = FakeIssueClient()
    state = new_soak_state(duration_hours=24, now=NOW)
    state.update(
        {
            "cycle_count": 24,
            "success_count": 23,
            "warning_count": 1,
        }
    )
    issue = client.create_issue(title=SOAK_TITLE, state=state)

    result = finish_soak(
        client,
        issue=issue,
        state=state,
        now=NOW + timedelta(hours=24),
    )

    assert result["status"] == "needs_review"
    assert result["state"]["promotion_ready"] is False
