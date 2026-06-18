import os
from typing import Any, Dict

import httpx


RISK_AGENT_URL = os.getenv("RISK_AGENT_URL", "http://risk-agent:8007")
RISK_AGENT_TIMEOUT = float(os.getenv("RISK_AGENT_TIMEOUT", "10"))


def evaluate_risk(payload: Dict[str, Any]) -> Dict[str, Any]:
    with httpx.Client(base_url=RISK_AGENT_URL, timeout=RISK_AGENT_TIMEOUT) as client:
        sizing_payload = {
            "symbol": payload["symbol"],
            "side": payload["side"],
            "entry_price": payload["entry_price"],
            "protection_price": payload["protection_price"],
            "equity": payload["equity"],
        }
        sizing_response = client.post("/risk/position-size", json=sizing_payload)
        sizing_response.raise_for_status()
        sizing = sizing_response.json()
        if sizing.get("status") != "success":
            return sizing

        safe_quantity = int((sizing.get("data") or {}).get("approved_quantity") or 0)
        requested_quantity = int(payload.get("requested_quantity") or 0)
        payload["requested_quantity"] = min(requested_quantity, safe_quantity) if requested_quantity else safe_quantity

        check_response = client.post("/risk/check", json=payload)
        check_response.raise_for_status()
        return check_response.json()
