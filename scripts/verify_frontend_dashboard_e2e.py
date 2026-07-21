from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any, Dict


FORBIDDEN_KEY_PARTS = (
    "api_key",
    "secret",
    "token",
    "database_url",
    "connection_string",
    "broker_order_id",
    "client_order_id",
    "account_id",
)
FORBIDDEN_VALUE_MARKERS = (
    "postgresql://",
    "paper-api.alpaca.markets",
    "dashboard-e2e-secret-must-not-leak",
)


def request(url: str) -> tuple[int, str, Dict[str, str]]:
    with urllib.request.urlopen(url, timeout=15) as response:
        return response.status, response.read().decode("utf-8"), dict(response.headers.items())


def assert_safe(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                raise AssertionError(f"Sensitive key exposed at {path}.{key}")
            assert_safe(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_safe(item, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in FORBIDDEN_VALUE_MARKERS):
            raise AssertionError(f"Sensitive value exposed at {path}")


def validate_snapshot(payload: Dict[str, Any]) -> None:
    if payload.get("schemaVersion") != "dashboard-snapshot.v1":
        raise AssertionError("Manager did not return dashboard-snapshot.v1")
    if payload.get("mode") != "PAPER":
        raise AssertionError(f"Expected PAPER mode, got {payload.get('mode')}")
    if payload.get("brokerMode") != "SIMULATOR":
        raise AssertionError(f"Expected SIMULATOR broker mode, got {payload.get('brokerMode')}")
    for field in ("positions", "openOrders", "curatorSignals"):
        if not isinstance(payload.get(field), list):
            raise AssertionError(f"{field} must be an array")
    if not isinstance(payload.get("account"), dict) or not isinstance(payload.get("summary"), dict):
        raise AssertionError("account and summary must be objects")
    assert_safe(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the real Manager-to-Frontend dashboard E2E contract.")
    parser.add_argument("--manager-url", default="http://127.0.0.1:8000")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:5173")
    parser.add_argument("--output", default="dashboard-e2e-artifacts")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    last_payload = None
    for _ in range(2):
        status, body, headers = request(f"{args.manager_url.rstrip('/')}/dashboard/snapshot")
        if status != 200:
            raise AssertionError(f"Manager snapshot returned HTTP {status}")
        if "no-store" not in headers.get("Cache-Control", ""):
            raise AssertionError("Manager snapshot must be no-store")
        payload = json.loads(body)
        validate_snapshot(payload)
        last_payload = payload

    frontend_status, frontend_html, _ = request(args.frontend_url)
    if frontend_status != 200 or 'id="root"' not in frontend_html:
        raise AssertionError("Frontend HTML did not load")

    # Persist only a non-sensitive attestation, never balances/positions/orders.
    (output / "verification.json").write_text(
        json.dumps(
            {
                "verified": True,
                "schemaVersion": last_payload["schemaVersion"],
                "mode": last_payload["mode"],
                "brokerMode": last_payload["brokerMode"],
                "refreshResponsesVerified": 2,
                "frontendHtmlVerified": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("Manager/Frontend HTTP E2E contract passed twice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
