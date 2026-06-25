import datetime
import uuid
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from .alerts import alert_service
from .config_manager import config_manager
from .contracts import StandardAgentResponse
from .database_client import DatabaseAgentClient
from .execution_client import ExecutionAgentClient

router = APIRouter(tags=["Thai Trading Dashboard"])


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _safe_status(value: Any) -> str:
    return str(value or "").lower()


def _is_open_order(order: Dict[str, Any]) -> bool:
    status = _safe_status(order.get("status") or order.get("order_status"))
    return status in {"new", "pending", "placed", "submitted", "accepted", "open", "partially_filled"}


def _response(data: Dict[str, Any]) -> StandardAgentResponse:
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=_now(),
        data=data,
    )


def _broker_state_from_response(response: Any) -> Dict[str, Any]:
    payload = response.data if hasattr(response, "data") else None
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    return payload if isinstance(payload, dict) else {}


def _balance_from_broker_account(account: Dict[str, Any], account_id: Union[int, str]) -> Dict[str, Any]:
    return {
        "account_id": account_id,
        "cash_balance": account.get("cash"),
        "cash": account.get("cash"),
        "buying_power": account.get("buying_power"),
        "equity": account.get("equity"),
        "portfolio_value": account.get("portfolio_value"),
        "source": "broker_fallback",
    }


def _db_context_looks_stale(balance: Any, positions: List[Any], orders: List[Dict[str, Any]], broker_state: Dict[str, Any], database_sync: Dict[str, Any]) -> bool:
    mismatch = database_sync.get("mismatch") if isinstance(database_sync, dict) else {}
    summary = mismatch.get("summary") if isinstance(mismatch, dict) else {}
    if summary.get("status") == "mismatch":
        return True
    if not broker_state:
        return False
    broker_positions = broker_state.get("positions") or []
    broker_orders = broker_state.get("open_orders") or []
    broker_account = broker_state.get("account") or {}
    db_balance = _jsonable(balance) or {}
    if broker_positions and not positions:
        return True
    if broker_orders and not orders:
        return True
    broker_cash = str(broker_account.get("cash") or "")
    db_cash = str(db_balance.get("cash_balance") or db_balance.get("cash") or "")
    return bool(broker_cash and db_cash and broker_cash != db_cash)


async def _load_broker_state(account_id: Union[int, str], correlation_id: str) -> Dict[str, Any]:
    try:
        async with ExecutionAgentClient() as exec_client:
            reconcile = await exec_client.reconcile_broker_state(account_id, correlation_id)
            reconcile_payload = _broker_state_from_response(reconcile)
            broker_state = reconcile_payload.get("broker_state") or {}
            if broker_state:
                return {"status": "success", "mode": "reconcile", "payload": reconcile_payload, "broker_state": broker_state}
            state = await exec_client.broker_state(account_id, correlation_id)
            state_payload = _broker_state_from_response(state)
            return {"status": "success", "mode": "state", "payload": state_payload, "broker_state": state_payload}
    except Exception as exc:
        return {"status": "failed", "error": str(exc), "payload": {}, "broker_state": {}}


async def _load_database_sync_status(db_client: DatabaseAgentClient, account_id: Union[int, str], correlation_id: str, data_errors: List[str]) -> Dict[str, Any]:
    getter = getattr(db_client, "get_broker_sync_status", None)
    if getter is None:
        return {}
    try:
        return await getter(account_id, correlation_id)
    except Exception as exc:
        data_errors.append(f"ดึงสถานะ Broker/Database sync ไม่สำเร็จ: {exc}")
        return {}


def _broker_fallback_alert(broker_sync: Dict[str, Any], database_sync: Dict[str, Any]) -> Dict[str, Any]:
    mismatch = database_sync.get("mismatch") if isinstance(database_sync, dict) else {}
    summary = mismatch.get("summary") if isinstance(mismatch, dict) else {}
    diagnostics = mismatch.get("diagnostics") if isinstance(mismatch, dict) else {}
    recommended_action = summary.get("recommended_action") or "refresh_broker_sync"
    return {
        "alert_type": "dashboard_broker_fallback",
        "severity": summary.get("severity") or "warning",
        "message": f"Dashboard ใช้ข้อมูล broker โดยตรง เพราะ Database context ยังไม่ตรงกับ broker: {recommended_action}",
        "created_at": _now().isoformat(),
        "metadata": {
            "source": "dashboard",
            "broker_sync_status": broker_sync.get("status"),
            "database_sync_summary": summary,
            "database_sync_diagnostics": diagnostics,
        },
    }


async def _dashboard_payload(account_id: Optional[Union[int, str]], correlation_id: str) -> Dict[str, Any]:
    account_id = account_id if account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")
    problems = alert_service.list_events(limit=50)
    balance = None
    positions: List[Any] = []
    orders: List[Dict[str, Any]] = []
    trade_history: List[Any] = []
    data_errors: List[str] = []
    database_sync: Dict[str, Any] = {}

    broker_sync = await _load_broker_state(account_id, correlation_id)
    broker_state = broker_sync.get("broker_state") or {}

    try:
        async with DatabaseAgentClient() as db_client:
            database_sync = await _load_database_sync_status(db_client, account_id, correlation_id, data_errors)
            try:
                balance = await db_client.get_account_balance(account_id, correlation_id)
            except Exception as exc:
                data_errors.append(f"ดึงยอดเงินคงเหลือไม่สำเร็จ: {exc}")
            try:
                positions = await db_client.get_positions(account_id, correlation_id)
            except Exception as exc:
                data_errors.append(f"ดึงหุ้นที่ถืออยู่ไม่สำเร็จ: {exc}")
            try:
                orders = await db_client.get_orders(account_id, correlation_id)
            except Exception as exc:
                data_errors.append(f"ดึงออเดอร์ที่เปิดอยู่ไม่สำเร็จ: {exc}")
            try:
                trade_history = await db_client.get_trade_history(account_id, correlation_id)
            except Exception as exc:
                data_errors.append(f"ดึงประวัติการซื้อขายไม่สำเร็จ: {exc}")
    except Exception as exc:
        data_errors.append(f"เชื่อมต่อ Database Agent ไม่สำเร็จ: {exc}")

    data_source = "database"
    if _db_context_looks_stale(balance, positions, orders, broker_state, database_sync):
        account = broker_state.get("account") or {}
        balance = _balance_from_broker_account(account, account_id)
        positions = broker_state.get("positions") or []
        orders = broker_state.get("open_orders") or []
        data_source = "broker_fallback"
        problems = [_broker_fallback_alert(broker_sync, database_sync)] + problems

    open_orders = [order for order in orders if _is_open_order(order)]
    if data_errors:
        data_error_alerts = [
            {
                "alert_type": "dashboard_data_error",
                "severity": "warning",
                "message": error,
                "created_at": _now().isoformat(),
                "metadata": {"source": "dashboard"},
            }
            for error in data_errors
        ]
        problems = problems + data_error_alerts if data_source == "broker_fallback" else data_error_alerts + problems

    return {
        "account_id": str(account_id),
        "generated_at": _now().isoformat(),
        "data_source": data_source,
        "broker_sync": _jsonable(broker_sync.get("payload") or {"status": broker_sync.get("status"), "error": broker_sync.get("error")}),
        "database_sync": _jsonable(database_sync),
        "problems": _jsonable(problems),
        "balance": _jsonable(balance),
        "positions": _jsonable(positions),
        "open_orders": _jsonable(open_orders),
        "trade_history": _jsonable(trade_history),
        "summary": {
            "problem_count": len(problems),
            "position_count": len(positions),
            "open_order_count": len(open_orders),
            "trade_count": len(trade_history),
            "database_sync_status": ((database_sync.get("mismatch") or {}).get("summary") or {}).get("status"),
        },
    }


@router.get("/dashboard/data", response_model=StandardAgentResponse)
async def dashboard_data(account_id: Optional[str] = Query(default=None)):
    correlation_id = str(uuid.uuid4())
    return _response(await _dashboard_payload(account_id, correlation_id))


@router.get("/dashboard", response_class=HTMLResponse)
async def thai_dashboard():
    return HTMLResponse(DASHBOARD_HTML)


DASHBOARD_HTML = """
<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>แดชบอร์ดระบบเทรด</title>
  <style>
    :root { color-scheme: dark; --bg:#0f172a; --card:#111827; --muted:#94a3b8; --text:#e5e7eb; --border:#263244; }
    body { margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#0f172a; color:#e5e7eb; }
    header, main { padding:24px; }
    .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr)); gap:14px; }
    .card { background:#111827; border:1px solid #263244; border-radius:18px; padding:18px; margin-bottom:14px; }
    .metric { font-size:30px; font-weight:800; }
    .muted { color:#94a3b8; font-size:13px; }
    table { width:100%; border-collapse:collapse; }
    th, td { text-align:left; border-bottom:1px solid #263244; padding:10px 8px; font-size:14px; vertical-align:top; }
    .badge { border-radius:999px; padding:4px 8px; font-size:12px; font-weight:700; background:#1e293b; }
    .warning { color:#fde68a; } .critical,.error { color:#fecaca; } .success,.ok { color:#bbf7d0; }
    .empty { padding:18px; color:#94a3b8; border:1px dashed #263244; border-radius:14px; }
  </style>
</head>
<body>
  <header>
    <h1>แดชบอร์ดระบบเทรด</h1>
    <div class="muted">แสดงปัญหา ยอดเงินคงเหลือ หุ้นที่ถือ ออเดอร์เปิด และประวัติการซื้อขาย</div>
    <input id="accountId" placeholder="Account ID" />
    <button onclick="loadDashboard()">รีเฟรชข้อมูล</button>
    <span id="updated" class="muted"></span>
  </header>
  <main>
    <section class="grid">
      <div class="card"><h2>ปัญหาระบบ</h2><div id="problemCount" class="metric">-</div></div>
      <div class="card"><h2>ยอดเงินคงเหลือ</h2><div id="cashBalance" class="metric">-</div><div id="accountMeta" class="muted"></div></div>
      <div class="card"><h2>หุ้นที่ถืออยู่</h2><div id="positionCount" class="metric">-</div></div>
      <div class="card"><h2>ออเดอร์ที่เปิดอยู่</h2><div id="openOrderCount" class="metric">-</div></div>
      <div class="card"><h2>Database Sync</h2><div id="syncStatus" class="metric">-</div><div id="syncAction" class="muted"></div></div>
    </section>
    <section class="card"><h2>ปัญหา / Alert</h2><div id="problems"></div></section>
    <section class="card"><h2>หุ้นที่ถืออยู่</h2><div id="positions"></div></section>
    <section class="card"><h2>หุ้นที่กำลังเปิดออเดอร์</h2><div id="openOrders"></div></section>
    <section class="card"><h2>ประวัติการซื้อขาย</h2><div id="trades"></div></section>
  </main>
<script>
const fmtMoney = (v) => {
  if (v === null || v === undefined || v === '') return '-';
  const n = Number(v); return Number.isFinite(n) ? n.toLocaleString('th-TH', { style:'currency', currency:'USD' }) : String(v);
};
const pick = (obj, keys) => keys.map(k => obj?.[k]).find(v => v !== undefined && v !== null && v !== '') ?? '-';
const badge = (text) => `<span class="badge ${String(text).toLowerCase()}">${text || '-'}</span>`;
function table(rows, cols) {
  if (!rows || rows.length === 0) return '<div class="empty">ยังไม่มีข้อมูล</div>';
  return `<table><thead><tr>${cols.map(c=>`<th>${c.label}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${c.render ? c.render(r) : pick(r,c.keys)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
async function loadDashboard() {
  const account = document.getElementById('accountId').value.trim();
  const url = account ? `/dashboard/data?account_id=${encodeURIComponent(account)}` : '/dashboard/data';
  const res = await fetch(url);
  const body = await res.json();
  const data = body.data || {};
  const syncSummary = data.database_sync?.mismatch?.summary || {};
  document.getElementById('updated').textContent = `อัปเดต: ${new Date(data.generated_at || Date.now()).toLocaleString('th-TH')} | Source: ${data.data_source || '-'}`;
  document.getElementById('problemCount').textContent = data.summary?.problem_count ?? 0;
  document.getElementById('positionCount').textContent = data.summary?.position_count ?? 0;
  document.getElementById('openOrderCount').textContent = data.summary?.open_order_count ?? 0;
  document.getElementById('syncStatus').textContent = syncSummary.status || data.summary?.database_sync_status || '-';
  document.getElementById('syncAction').textContent = syncSummary.recommended_action || '';
  const bal = data.balance || {};
  document.getElementById('cashBalance').textContent = fmtMoney(pick(bal, ['cash_balance','cash','available_cash','buying_power']));
  document.getElementById('accountMeta').textContent = `Account: ${data.account_id || '-'} | Trades: ${data.summary?.trade_count ?? 0}`;
  document.getElementById('problems').innerHTML = table(data.problems, [
    {label:'ระดับ', render:r=>badge(pick(r,['severity']))}, {label:'ประเภท', keys:['alert_type']}, {label:'ข้อความ', keys:['message']}, {label:'เวลา', render:r=> pick(r,['created_at'])}
  ]);
  document.getElementById('positions').innerHTML = table(data.positions, [
    {label:'หุ้น', keys:['symbol']}, {label:'จำนวน', keys:['quantity','qty']}, {label:'ราคาเฉลี่ย', render:r=>fmtMoney(pick(r,['average_cost','avg_entry_price']))}, {label:'ราคาปัจจุบัน', render:r=>fmtMoney(pick(r,['current_market_price','current_price']))}, {label:'มูลค่า', render:r=>fmtMoney(pick(r,['market_value','value']))}
  ]);
  document.getElementById('openOrders').innerHTML = table(data.open_orders, [
    {label:'Order ID', keys:['order_id','id']}, {label:'หุ้น', keys:['symbol']}, {label:'ฝั่ง', keys:['side']}, {label:'จำนวน', keys:['quantity','qty']}, {label:'สถานะ', render:r=>badge(pick(r,['status','order_status']))}, {label:'เวลา', keys:['created_at','submitted_at']}
  ]);
  document.getElementById('trades').innerHTML = table(data.trade_history, [
    {label:'Trade ID', keys:['trade_id','id']}, {label:'หุ้น', keys:['symbol']}, {label:'ฝั่ง', keys:['side']}, {label:'จำนวน', keys:['quantity','qty']}, {label:'ราคา', render:r=>fmtMoney(pick(r,['price','fill_price','entry_price']))}, {label:'เวลา', keys:['executed_at','filled_at','timestamp']}
  ]);
}
loadDashboard();
</script>
</body>
</html>
"""
