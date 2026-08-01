from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


CURATOR_AGENT_URL = os.getenv("CURATOR_AGENT_URL", "http://localhost:8010").rstrip("/")
CURATOR_AGENT_API_KEY = os.getenv("CURATOR_AGENT_API_KEY", "").strip()
CURATOR_ADMIN_API_KEY = (
    os.getenv("CURATOR_ADMIN_API_KEY", "").strip() or CURATOR_AGENT_API_KEY
)


def _auth_headers(*, admin: bool = False) -> dict[str, str]:
    api_key = CURATOR_ADMIN_API_KEY if admin else CURATOR_AGENT_API_KEY
    return {"X-API-KEY": api_key} if api_key else {}


def request_json(
    path: str,
    *,
    payload: dict | None = None,
    admin: bool = False,
) -> dict:
    data = None
    headers = _auth_headers(admin=admin)
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    req = urllib.request.Request(
        f"{CURATOR_AGENT_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def main() -> int:
    try:
        health = request_json("/health")
        if health.get("status") != "success":
            print(json.dumps({"ok": False, "stage": "health", "response": health}, indent=2))
            return 1

        register = request_json(
            "/skills/register",
            admin=True,
            payload={
                "name": "Curator Runtime Smoke Skill",
                "description": "Harmless smoke-test skill for Manager_Agent runtime integration.",
                "tags": ["technical", "smoke-test"],
                "code": "def smoke_signal(symbol, analysis, ticker):\n    return {\"signal\": \"hold\", \"confidence\": 0.5, \"reason\": \"runtime smoke test\"}",
            },
        )
        skill_id = (register.get("data") or {}).get("skill_id")
        if not skill_id:
            print(json.dumps({"ok": False, "stage": "register", "response": register}, indent=2))
            return 1

        approve = request_json(
            f"/skills/{skill_id}/approve",
            admin=True,
            payload={"approved_by": "runtime-smoke-check", "reason": "connectivity test"},
        )
        if (approve.get("data") or {}).get("approval_status") != "approved":
            print(json.dumps({"ok": False, "stage": "approve", "response": approve}, indent=2))
            return 1

        execute = request_json(
            f"/skills/{skill_id}/execute",
            payload={"inputs": {"symbol": "TEST", "ticker": "TEST", "analysis": {}}, "timeout_seconds": 1.0},
        )
        data = execute.get("data") or {}
        if data.get("execution_status") != "success":
            print(json.dumps({"ok": False, "stage": "execute", "response": execute}, indent=2))
            return 1

        print(json.dumps({"ok": True, "skill_id": skill_id, "execute": data}, indent=2))
        return 0
    except urllib.error.URLError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
