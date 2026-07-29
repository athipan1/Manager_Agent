#!/usr/bin/env python3
"""Durable GitHub control plane for Alpaca Paper soak and emergency halt.

The state is stored in repository issues so it survives ephemeral GitHub runners.
Issue bodies contain operational metadata only; broker credentials and account IDs
must never be written to this control plane.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


SOAK_TITLE = "[control] Alpaca Paper soak active"
HALT_TITLE = "[control] Alpaca Paper emergency halt"
ALERT_TITLE = "[alert] Alpaca Paper operator review required"
SOAK_SCHEMA = "alpaca-paper-soak.v1"
HALT_SCHEMA = "alpaca-paper-emergency-halt.v1"
ALLOWED_DURATIONS = {24, 48, 72}
START_CONFIRMATION = "START_ALPACA_PAPER_SOAK"
STOP_CONFIRMATION = "STOP_ALPACA_PAPER_SOAK"
HALT_CONFIRMATION = "HALT_ALPACA_PAPER"
CLEAR_HALT_CONFIRMATION = "CLEAR_ALPACA_PAPER_HALT"


class ControlError(RuntimeError):
    """Raised when the durable Paper control state cannot be proven safe."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ControlError("Paper control state contains an invalid timestamp.") from exc
    if parsed.tzinfo is None:
        raise ControlError("Paper control timestamp must include a timezone.")
    return parsed.astimezone(timezone.utc)


def write_github_output(values: Mapping[str, Any]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            if isinstance(value, bool):
                rendered = str(value).lower()
            elif isinstance(value, (dict, list)):
                rendered = json.dumps(value, separators=(",", ":"), sort_keys=True)
            else:
                rendered = str(value)
            handle.write(f"{key}={rendered}\n")


class GitHubIssueClient:
    """Minimal GitHub Issues REST client with bounded, non-secret errors."""

    def __init__(
        self,
        *,
        repository: str,
        token: str,
        api_url: str = "https://api.github.com",
    ) -> None:
        if "/" not in repository:
            raise ControlError("GITHUB_REPOSITORY is missing or invalid.")
        if not token:
            raise ControlError("GITHUB_TOKEN is required for Paper control checks.")
        self.repository = repository
        self.token = token
        self.api_url = api_url.rstrip("/")

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "manager-agent-paper-control",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise ControlError(
                f"GitHub Paper control request failed with HTTP {exc.code}."
            ) from exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ControlError(
                "GitHub Paper control request returned an invalid response."
            ) from exc

    def find_open_issue(self, title: str) -> dict[str, Any] | None:
        query = urllib.parse.urlencode(
            {"state": "open", "per_page": 100, "sort": "created", "direction": "desc"}
        )
        rows = self.request(f"/repos/{self.repository}/issues?{query}")
        if not isinstance(rows, list):
            raise ControlError("GitHub Issues list response is invalid.")
        matches = [
            row
            for row in rows
            if isinstance(row, dict)
            and "pull_request" not in row
            and str(row.get("title") or "") == title
        ]
        if len(matches) > 1:
            raise ControlError(f"Multiple open control issues found for {title}.")
        return matches[0] if matches else None

    def get_issue(self, number: int) -> dict[str, Any]:
        issue = self.request(f"/repos/{self.repository}/issues/{number}")
        if not isinstance(issue, dict) or int(issue.get("number") or 0) != number:
            raise ControlError("GitHub control issue response is invalid.")
        return issue

    def create_issue(self, *, title: str, state: Mapping[str, Any]) -> dict[str, Any]:
        issue = self.request(
            f"/repos/{self.repository}/issues",
            method="POST",
            payload={"title": title, "body": encode_state(state)},
        )
        if not isinstance(issue, dict) or not issue.get("number"):
            raise ControlError("GitHub did not create the Paper control issue.")
        return issue

    def update_issue(
        self,
        number: int,
        *,
        state: Mapping[str, Any],
        close: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"body": encode_state(state)}
        if close:
            payload["state"] = "closed"
        issue = self.request(
            f"/repos/{self.repository}/issues/{number}",
            method="PATCH",
            payload=payload,
        )
        if not isinstance(issue, dict):
            raise ControlError("GitHub did not update the Paper control issue.")
        return issue

    def comment(self, number: int, body: str) -> None:
        self.request(
            f"/repos/{self.repository}/issues/{number}/comments",
            method="POST",
            payload={"body": body},
        )


def encode_state(state: Mapping[str, Any]) -> str:
    return json.dumps(dict(state), ensure_ascii=False, indent=2, sort_keys=True)


def decode_state(issue: Mapping[str, Any], *, schema: str) -> dict[str, Any]:
    try:
        state = json.loads(str(issue.get("body") or ""))
    except json.JSONDecodeError as exc:
        raise ControlError("Paper control issue body is not valid JSON.") from exc
    if not isinstance(state, dict) or state.get("schema_version") != schema:
        raise ControlError("Paper control issue schema is invalid.")
    return state


def issue_number(issue: Mapping[str, Any]) -> int:
    try:
        number = int(issue.get("number"))
    except (TypeError, ValueError) as exc:
        raise ControlError("Paper control issue number is invalid.") from exc
    if number < 1:
        raise ControlError("Paper control issue number is invalid.")
    return number


def client_from_env() -> GitHubIssueClient:
    return GitHubIssueClient(
        repository=os.getenv("GITHUB_REPOSITORY", ""),
        token=os.getenv("GITHUB_TOKEN", ""),
        api_url=os.getenv("GITHUB_API_URL", "https://api.github.com"),
    )


def run_metadata() -> dict[str, str]:
    return {
        "actor": os.getenv("GITHUB_ACTOR", "unknown"),
        "run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "1"),
        "run_url": os.getenv("GITHUB_RUN_URL", ""),
    }


def paper_mutation_requested(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    return (
        str(values.get("BROKER_MODE") or "").strip().upper() == "ALPACA"
        and str(values.get("DRY_RUN") or "true").strip().lower() == "false"
    )


def assert_emergency_halt_clear(
    client: GitHubIssueClient,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not paper_mutation_requested(env):
        return {"status": "not_required", "paper_mutation_requested": False}
    issue = client.find_open_issue(HALT_TITLE)
    if issue is not None:
        state = decode_state(issue, schema=HALT_SCHEMA)
        raise ControlError(
            "Durable Alpaca Paper emergency halt is active: "
            f"issue #{issue_number(issue)}, reason={state.get('reason') or 'unspecified'}."
        )
    return {"status": "clear", "paper_mutation_requested": True}


def activate_emergency_halt(
    client: GitHubIssueClient,
    *,
    reason: str,
    now: datetime,
    source: str,
) -> dict[str, Any]:
    clean_reason = reason.strip()
    if not clean_reason:
        raise ControlError("Emergency halt reason is required.")
    existing = client.find_open_issue(HALT_TITLE)
    if existing is not None:
        return {
            "status": "already_active",
            "issue_number": issue_number(existing),
            "state": decode_state(existing, schema=HALT_SCHEMA),
        }
    state = {
        "schema_version": HALT_SCHEMA,
        "status": "active",
        "reason": clean_reason,
        "activated_at": timestamp(now),
        "source": source,
        **run_metadata(),
    }
    issue = client.create_issue(title=HALT_TITLE, state=state)
    return {
        "status": "activated",
        "issue_number": issue_number(issue),
        "state": state,
    }


def clear_emergency_halt(
    client: GitHubIssueClient,
    *,
    reason: str,
    now: datetime,
) -> dict[str, Any]:
    clean_reason = reason.strip()
    if not clean_reason:
        raise ControlError("Emergency halt clear reason is required.")
    issue = client.find_open_issue(HALT_TITLE)
    if issue is None:
        return {"status": "already_clear", "issue_number": ""}
    state = decode_state(issue, schema=HALT_SCHEMA)
    state.update(
        {
            "status": "cleared",
            "cleared_at": timestamp(now),
            "clear_reason": clean_reason,
            "cleared_by": os.getenv("GITHUB_ACTOR", "unknown"),
            "clear_run_id": os.getenv("GITHUB_RUN_ID", "local"),
        }
    )
    number = issue_number(issue)
    client.update_issue(number, state=state, close=True)
    return {"status": "cleared", "issue_number": number, "state": state}


def emergency_control(
    client: GitHubIssueClient,
    *,
    operation: str,
    reason: str,
    confirmation: str,
    now: datetime,
) -> dict[str, Any]:
    if operation == "activate":
        if confirmation != HALT_CONFIRMATION:
            raise ControlError(f"Enter {HALT_CONFIRMATION} to activate the halt.")
        return activate_emergency_halt(
            client,
            reason=reason,
            now=now,
            source="manual_operator",
        )
    if operation == "clear":
        if confirmation != CLEAR_HALT_CONFIRMATION:
            raise ControlError(
                f"Enter {CLEAR_HALT_CONFIRMATION} to clear the halt."
            )
        return clear_emergency_halt(client, reason=reason, now=now)
    issue = client.find_open_issue(HALT_TITLE)
    if issue is None:
        return {"status": "clear", "issue_number": ""}
    return {
        "status": "active",
        "issue_number": issue_number(issue),
        "state": decode_state(issue, schema=HALT_SCHEMA),
    }


def new_soak_state(*, duration_hours: int, now: datetime) -> dict[str, Any]:
    metadata = run_metadata()
    return {
        "schema_version": SOAK_SCHEMA,
        "status": "active",
        "started_at": timestamp(now),
        "ends_at": timestamp(now + timedelta(hours=duration_hours)),
        "duration_hours": duration_hours,
        "expected_min_cycles": duration_hours,
        "cycle_count": 0,
        "success_count": 0,
        "warning_count": 0,
        "failure_count": 0,
        "last_cycle_at": None,
        "last_cycle_result": None,
        "last_cycle_run_id": None,
        "requested_by": metadata["actor"],
        "start_run_id": metadata["run_id"],
        "start_run_url": metadata["run_url"],
    }


def finish_soak(
    client: GitHubIssueClient,
    *,
    issue: Mapping[str, Any],
    state: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    expected = int(state.get("expected_min_cycles") or state.get("duration_hours") or 0)
    success = int(state.get("success_count") or 0)
    warnings = int(state.get("warning_count") or 0)
    failures = int(state.get("failure_count") or 0)
    clean = failures == 0 and warnings == 0 and success >= expected
    state.update(
        {
            "status": "completed" if clean else "needs_review",
            "completed_at": timestamp(now),
            "promotion_ready": clean,
        }
    )
    number = issue_number(issue)
    client.update_issue(number, state=state, close=True)
    client.comment(
        number,
        (
            f"Soak window closed: status={state['status']}, cycles={state['cycle_count']}, "
            f"success={success}, warning={warnings}, failure={failures}, "
            f"promotion_ready={str(clean).lower()}."
        ),
    )
    return {
        "status": state["status"],
        "should_run": False,
        "issue_number": number,
        "state": state,
    }


def soak_control(
    client: GitHubIssueClient,
    *,
    operation: str,
    duration_hours: int,
    confirmation: str,
    now: datetime,
    production_schedule_enabled: bool,
) -> dict[str, Any]:
    issue = client.find_open_issue(SOAK_TITLE)
    if operation == "start":
        if confirmation != START_CONFIRMATION:
            raise ControlError(f"Enter {START_CONFIRMATION} to start the soak.")
        if duration_hours not in ALLOWED_DURATIONS:
            raise ControlError("Soak duration must be 24, 48 or 72 hours.")
        if production_schedule_enabled:
            raise ControlError(
                "Disable HOURLY_PAPER_SCHEDULE_ENABLED before starting a soak."
            )
        if client.find_open_issue(HALT_TITLE) is not None:
            raise ControlError("Clear the Alpaca Paper emergency halt before a soak.")
        if issue is not None:
            raise ControlError(
                f"An Alpaca Paper soak is already active in issue #{issue_number(issue)}."
            )
        state = new_soak_state(duration_hours=duration_hours, now=now)
        issue = client.create_issue(title=SOAK_TITLE, state=state)
        return {
            "status": "started",
            "should_run": True,
            "issue_number": issue_number(issue),
            "state": state,
        }

    if operation == "stop":
        if confirmation != STOP_CONFIRMATION:
            raise ControlError(f"Enter {STOP_CONFIRMATION} to stop the soak.")
        if issue is None:
            return {"status": "not_active", "should_run": False, "issue_number": ""}
        state = decode_state(issue, schema=SOAK_SCHEMA)
        state.update(
            {
                "status": "stopped",
                "stopped_at": timestamp(now),
                "stopped_by": os.getenv("GITHUB_ACTOR", "unknown"),
            }
        )
        number = issue_number(issue)
        client.update_issue(number, state=state, close=True)
        return {
            "status": "stopped",
            "should_run": False,
            "issue_number": number,
            "state": state,
        }

    if issue is None:
        return {"status": "not_active", "should_run": False, "issue_number": ""}
    state = decode_state(issue, schema=SOAK_SCHEMA)
    number = issue_number(issue)
    if operation == "status":
        return {
            "status": state.get("status", "active"),
            "should_run": False,
            "issue_number": number,
            "state": state,
        }
    if client.find_open_issue(HALT_TITLE) is not None:
        state.update(
            {
                "status": "halted",
                "halted_at": timestamp(now),
                "promotion_ready": False,
            }
        )
        client.update_issue(number, state=state, close=True)
        return {
            "status": "halted",
            "should_run": False,
            "issue_number": number,
            "state": state,
        }
    if now >= parse_timestamp(state.get("ends_at")):
        return finish_soak(client, issue=issue, state=state, now=now)
    return {
        "status": "active",
        "should_run": True,
        "issue_number": number,
        "state": state,
    }


def load_evidence(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlError("Paper cycle evidence is missing or invalid.") from exc
    if not isinstance(payload, dict):
        raise ControlError("Paper cycle evidence must be a JSON object.")
    return payload


def resolve_cycle_result(
    *,
    workflow_result: str,
    audit_outcome: str,
    evidence_path: Path,
) -> tuple[str, dict[str, Any]]:
    if workflow_result != "success" or audit_outcome != "success":
        return "failure", {}
    evidence = load_evidence(evidence_path)
    result = str(evidence.get("result") or "").lower()
    if result not in {"success", "warning", "failure"}:
        raise ControlError("Paper cycle evidence result is invalid.")
    return result, evidence


def record_soak_cycle(
    client: GitHubIssueClient,
    *,
    number: int,
    workflow_result: str,
    audit_outcome: str,
    evidence_path: Path,
    run_url: str,
    now: datetime,
) -> dict[str, Any]:
    issue = client.get_issue(number)
    if str(issue.get("title") or "") != SOAK_TITLE:
        raise ControlError("The supplied issue is not the active Paper soak control.")
    state = decode_state(issue, schema=SOAK_SCHEMA)
    result, evidence = resolve_cycle_result(
        workflow_result=workflow_result,
        audit_outcome=audit_outcome,
        evidence_path=evidence_path,
    )
    state["cycle_count"] = int(state.get("cycle_count") or 0) + 1
    counter = f"{result}_count"
    state[counter] = int(state.get(counter) or 0) + 1
    state["last_cycle_at"] = timestamp(now)
    state["last_cycle_result"] = result
    state["last_cycle_run_id"] = os.getenv("GITHUB_RUN_ID", "local")
    state["last_cycle_run_url"] = run_url
    state["last_evidence_summary"] = {
        "check_count": evidence.get("check_count"),
        "warning_count": evidence.get("warning_count"),
        "submitted_order_count": evidence.get("submitted_order_count"),
    }

    if result == "failure":
        state.update(
            {
                "status": "halted",
                "halted_at": timestamp(now),
                "promotion_ready": False,
            }
        )
        client.update_issue(number, state=state, close=True)
        halt = activate_emergency_halt(
            client,
            reason=f"Alpaca Paper soak cycle failed: {run_url or 'run unavailable'}",
            now=now,
            source="soak_failure",
        )
    else:
        client.update_issue(number, state=state)
        halt = {"status": "not_required"}

    client.comment(
        number,
        (
            f"Cycle result: **{result}** · run: {run_url or 'unavailable'} · "
            f"totals: success={state.get('success_count', 0)}, "
            f"warning={state.get('warning_count', 0)}, "
            f"failure={state.get('failure_count', 0)}."
        ),
    )
    if result != "failure" and now >= parse_timestamp(state.get("ends_at")):
        finished = finish_soak(client, issue=issue, state=state, now=now)
        finished["cycle_result"] = result
        finished["halt"] = halt
        return finished
    return {
        "status": state["status"],
        "cycle_result": result,
        "issue_number": number,
        "state": state,
        "halt": halt,
    }


def create_or_update_alert(
    client: GitHubIssueClient,
    *,
    result: str,
    run_url: str,
    now: datetime,
) -> dict[str, Any]:
    if result == "success":
        return {"status": "not_required", "result": result}
    alert = client.find_open_issue(ALERT_TITLE)
    message = (
        f"Alpaca Paper cycle result: **{result}** at {timestamp(now)}. "
        f"Run: {run_url or 'unavailable'}."
    )
    if alert is None:
        alert = client.create_issue(
            title=ALERT_TITLE,
            state={
                "schema_version": "alpaca-paper-alert.v1",
                "status": "open",
                "latest_result": result,
                "latest_run_url": run_url,
                "updated_at": timestamp(now),
            },
        )
    client.comment(issue_number(alert), message)
    return {
        "status": "alerted",
        "result": result,
        "issue_number": issue_number(alert),
    }


def alert_manual_cycle(
    client: GitHubIssueClient,
    *,
    workflow_result: str,
    audit_outcome: str,
    evidence_path: Path,
    run_url: str,
    now: datetime,
) -> dict[str, Any]:
    result, _ = resolve_cycle_result(
        workflow_result=workflow_result,
        audit_outcome=audit_outcome,
        evidence_path=evidence_path,
    )
    alert = create_or_update_alert(
        client,
        result=result,
        run_url=run_url,
        now=now,
    )
    halt = {"status": "not_required"}
    if result == "failure":
        halt = activate_emergency_halt(
            client,
            reason=f"Manual Alpaca Paper cycle failed: {run_url or 'run unavailable'}",
            now=now,
            source="manual_cycle_failure",
        )
    return {"status": result, "alert": alert, "halt": halt}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("assert-clear")

    emergency = subparsers.add_parser("emergency")
    emergency.add_argument(
        "--operation", choices=("activate", "status", "clear"), required=True
    )
    emergency.add_argument("--reason", default="")
    emergency.add_argument("--confirmation", default="")

    soak = subparsers.add_parser("soak")
    soak.add_argument(
        "--operation", choices=("start", "status", "stop", "tick"), required=True
    )
    soak.add_argument("--duration-hours", type=int, default=24)
    soak.add_argument("--confirmation", default="")

    record = subparsers.add_parser("record")
    record.add_argument("--issue-number", type=int, required=True)
    record.add_argument("--workflow-result", required=True)
    record.add_argument("--audit-outcome", required=True)
    record.add_argument("--evidence", type=Path, required=True)
    record.add_argument("--run-url", default="")

    alert = subparsers.add_parser("alert")
    alert.add_argument("--workflow-result", required=True)
    alert.add_argument("--audit-outcome", required=True)
    alert.add_argument("--evidence", type=Path, required=True)
    alert.add_argument("--run-url", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now = utc_now()
    try:
        client = client_from_env()
        if args.command == "assert-clear":
            result = assert_emergency_halt_clear(client)
        elif args.command == "emergency":
            result = emergency_control(
                client,
                operation=args.operation,
                reason=args.reason,
                confirmation=args.confirmation,
                now=now,
            )
        elif args.command == "soak":
            result = soak_control(
                client,
                operation=args.operation,
                duration_hours=args.duration_hours,
                confirmation=args.confirmation,
                now=now,
                production_schedule_enabled=(
                    os.getenv("HOURLY_PAPER_SCHEDULE_ENABLED", "").lower()
                    == "true"
                ),
            )
        elif args.command == "record":
            result = record_soak_cycle(
                client,
                number=args.issue_number,
                workflow_result=args.workflow_result,
                audit_outcome=args.audit_outcome,
                evidence_path=args.evidence,
                run_url=args.run_url,
                now=now,
            )
        else:
            result = alert_manual_cycle(
                client,
                workflow_result=args.workflow_result,
                audit_outcome=args.audit_outcome,
                evidence_path=args.evidence,
                run_url=args.run_url,
                now=now,
            )
    except ControlError as exc:
        print(f"Alpaca Paper control failed closed: {exc}", file=sys.stderr)
        return 1

    write_github_output(
        {
            "status": result.get("status", ""),
            "should_run": result.get("should_run", False),
            "issue_number": result.get("issue_number", ""),
            "cycle_result": result.get("cycle_result", result.get("status", "")),
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
