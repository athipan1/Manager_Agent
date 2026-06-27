from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict


CURATOR_AGENT_URL = os.getenv("CURATOR_AGENT_URL", "http://localhost:8010").rstrip("/")
SKILL_NAME = "Manager Advisory Score Signal"

SKILL_CODE = """def manager_advisory_score_signal(symbol, analysis, ticker):
    score_breakdown = analysis.get("score_breakdown") or {}
    score = score_breakdown.get("final_opportunity_score") or analysis.get("final_opportunity_score") or 0.5
    try:
        confidence = float(score)
    except Exception:
        confidence = 0.5
    if confidence < 0:
        confidence = 0.0
    if confidence > 1:
        confidence = 1.0
    if confidence >= 0.7:
        signal = "buy"
    elif confidence <= 0.45:
        signal = "sell"
    else:
        signal = "hold"
    return {
        "signal": signal,
        "confidence": confidence,
        "reason": "Advisory-only score signal from Manager payload; Risk_Agent and Execution_Agent remain authoritative"
    }
"""


def request_json(path: str, *, payload: Dict[str, Any] | None = None, method: str | None = None) -> Dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{CURATOR_AGENT_URL}{path}",
        data=data,
        headers=headers,
        method=method or ("POST" if payload is not None else "GET"),
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def approved_skill_exists() -> bool:
    query = urllib.parse.quote(SKILL_NAME)
    response = request_json(f"/skills/search?q={query}&approval_status=approved")
    skills = response.get("data") or []
    if not isinstance(skills, list):
        return False
    return any((skill or {}).get("name") == SKILL_NAME for skill in skills if isinstance(skill, dict))


def main() -> int:
    try:
        health = request_json("/health")
        if health.get("status") != "success":
            print(json.dumps({"ok": False, "stage": "health", "response": health}, indent=2))
            return 1

        if approved_skill_exists():
            print(json.dumps({"ok": True, "status": "already_seeded", "skill_name": SKILL_NAME}, indent=2))
            return 0

        register_response = request_json(
            "/skills/register",
            payload={
                "name": SKILL_NAME,
                "description": "Advisory-only score signal for Manager_Agent payloads. Does not approve, size, or submit orders.",
                "tags": ["technical", "manager", "advisory", "score"],
                "source_agent": "manager-agent",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "ticker": {"type": "string"},
                        "analysis": {"type": "object"},
                    },
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "signal": {"type": "string"},
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                },
                "code": SKILL_CODE,
            },
        )
        skill = register_response.get("data") or {}
        skill_id = skill.get("skill_id")
        if not skill_id:
            print(json.dumps({"ok": False, "stage": "register", "response": register_response}, indent=2))
            return 1
        if skill.get("validation_status") != "validated":
            print(json.dumps({"ok": False, "stage": "validate", "response": register_response}, indent=2))
            return 1

        approve_response = request_json(
            f"/skills/{skill_id}/approve",
            payload={
                "approved_by": "hourly-auto-trading-workflow",
                "reason": "Advisory-only runtime signal; does not approve, size, or submit orders.",
            },
        )
        approved = approve_response.get("data") or {}
        if approved.get("approval_status") != "approved":
            print(json.dumps({"ok": False, "stage": "approve", "response": approve_response}, indent=2))
            return 1

        execute_response = request_json(
            f"/skills/{skill_id}/execute",
            payload={
                "inputs": {
                    "symbol": "TEST",
                    "ticker": "TEST",
                    "analysis": {"score_breakdown": {"final_opportunity_score": 0.5}},
                },
                "timeout_seconds": 1.0,
            },
        )
        execution = execute_response.get("data") or {}
        if execution.get("execution_status") != "success":
            print(json.dumps({"ok": False, "stage": "execute", "response": execute_response}, indent=2))
            return 1

        print(json.dumps({"ok": True, "status": "seeded", "skill_id": skill_id, "execution": execution}, indent=2))
        return 0
    except urllib.error.URLError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
