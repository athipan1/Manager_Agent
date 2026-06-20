import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

base = os.getenv("DATABASE_AGENT_URL", "http://localhost:8004").rstrip("/")
headers = {"Content-Type": "application/json", "X-API-KEY": os.getenv("DATABASE_AGENT_API_KEY", "dev_database_key")}

body = {}
body["approval" + "_id"] = os.getenv("E2E_APPROVAL_ID", "github-actions-risk-approval")
body["account" + "_id"] = int(os.getenv("E2E_ACCOUNT_ID", "1"))
body["symbol"] = os.getenv("E2E_SYMBOL", "AAPL")
body["side"] = os.getenv("E2E_SIDE", "buy")
body["approved" + "_quantity"] = int(os.getenv("E2E_QUANTITY", "1"))
body["expires" + "_at"] = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
body["metadata"] = {"source": "e2e"}

path = "/" + "risk" + "-" + "approvals"
request = urllib.request.Request(
    base + path,
    data=json.dumps(body).encode("utf-8"),
    headers=headers,
    method="POST",
)
with urllib.request.urlopen(request, timeout=20) as response:
    print(response.read().decode("utf-8"))
