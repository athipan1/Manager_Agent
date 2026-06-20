import datetime
import uuid
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from .alerts import alert_service
from .config_manager import config_manager
from .contracts import StandardAgentResponse
from .database_client import DatabaseAgentClient

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


async def _dashboard_payload(account_id: Optional[Union[int, str]], correlation_id: str) -> Dict[str, Any]:
    account_id = account_id if account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")
    problems = alert_service.list_events(limit=50)
    balance = None
    positions: List[Any] = []
    orders: List[Dict[str, Any]] = []
    trade_history: List[Any] = []
    data_errors: List[str] = []

    try:
        async with DatabaseAgentClient() as db_client:
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

    open_orders = [order for order in orders if _is_open_order(order)]
    if data_errors:
        problems = [
            {
                "alert_type": "dashboard_data_error",
                "severity": "warning",
                "message": error,
                "created_at": _now().isoformat(),
                "metadata": {"source": "dashboard"},
            }
            for error in data_errors
        ] + problems

    return {
        "account_id": str(account_id),
        "generated_at": _now().isoformat(),
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
    :root { color-scheme: dark; --bg:#0f172a; --card:#111827; --muted:#94a3b8; --text:#e5e7eb; --border:#263244; --good:#22c55e; --warn:#f59e0b; --bad:#ef4444; --accent:#38bdf8; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: radial-gradient(circle at top, #1e293b, var(--bg)); color:var(--text); }
    header { padding:24px; border-bottom:1px solid var(--border); position:sticky; top:0; background:rgba(15,23,42,.9); backdrop-filter: blur(10px); z-index:2; }
    h1 { margin:0 0 8px; font-size:28px; }
    .sub { color:var(--muted); font-size:14px; }
    .controls { margin-top:16px; display:flex; gap:10px; flex-wrap:wrap; }
    input, button { border:1px solid var(--border); border-radius:12px; padding:10px 12px; background:#0b1220; color:var(--text); }
    button { cursor:pointer; background:linear-gradient(135deg,#0284c7,#0369a1); border:none; font-weight:700; }
    main { padding:24px; display:grid; gap:18px; }
    .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr)); gap:14px; }
    .card { background:rgba(17,24,39,.88); border:1px solid var(--border); border-radius:18px; padding:18px; box-shadow:0 10px 30px rgba(0,0,0,.2); }
    .card h2 { margin:0 0 12px; font-size:18px; }
    .metric { font-size:30px; font-weight:800; margin:6px 0; }
    .muted { color:var(--muted); font-size:13px; }
    table { width:100%; border-collapse:collapse; overflow:hidden; }
    th, td { text-align:left; border-bottom:1px solid var(--border); padding:10px 8px; font-size:14px; vertical-align:top; }
    th { color:#cbd5e1; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
    .badge { display:inline-flex; border-radius:999px; padding:4px 8px; font-size:12px; font-weight:700; }
    .critical,.error { background:rgba(239,68,68,.16); color:#fecaca; }
    .warning { background:rgba(245,158,11,.16); color:#fde68a; }
    .success { background:rgba(34,197,94,.16); color:#bbf7d0; }
    .empty { padding:18px; color:var(--muted); border:1px dashed var(--border); border-radius:14px; }
    .section { display:grid; gap:14px; }
    @media (max-width: 640px) { header, main { padding:16px; } .metric { font-size:24px; } th,td { font-size:12px; } }
  </style>
</head>
<body>
  <header>
    <h1>แดชบอร์ดระบบเทรด</h1>
    <div class="sub">แสดงปัญหา ยอดเงินคงเหลือ หุ้นที่ถือ ออเดอร์เปิด และประวัติการซื้อขาย</div>
    <div class="controls">
      <input id="accountId" placeholder="Account ID" />
      <button onclick="loadDashboard()">รีเฟรชข้อมูล</button>
      <span id="updated" class="sub"></span>
    </div>
  </header>
  <main>
    <section class="grid">
      <div class="card"><h2>ปัญหาระบบ</h2><div id="problemCount" class="metric">-</div><div class="muted">Alert ล่าสุดจาก Manager</div></div>
      <div class="card"><h2>ยอดเงินคงเหลือ</h2><div id="cashBalance" class="metric">-</div><div id="accountMeta" class="muted"></div></div>
      <div class="card"><h2>หุ้นที่ถืออยู่</h2><div id="positionCount" class="metric">-</div><div class="muted">จำนวน position</div></div>
      <div class="card"><h2>ออเดอร์ที่เปิดอยู่</h2><div id="openOrderCount" class="metric">-</div><div class="muted">ยังไม่ปิด/ยังไม่ fill ทั้งหมด</div></div>
    </section>

    <section class="card section"><h2>ปัญหา / Alert</h2><div id="problems"></div></section>
    <section class="card section"><h2>หุ้นที่ถืออยู่</h2><div id="positions"></div></section>
    <section class="card section"><h2>หุ้นที่กำลังเปิดออเดอร์</h2><div id="openOrders"></div></section>
    <section class="card section"><h2>ประวัติการซื้อขาย</h2><div id="trades"></div></section>
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
  document.getElementById('updated').textContent = `อัปเดต: ${new Date(data.generated_at || Date.now()).toLocaleString('th-TH')}`;
  document.getElementById('problemCount').textContent = data.summary?.problem_count ?? 0;
  document.getElementById('positionCount').textContent = data.summary?.position_count ?? 0;
  document.getElementById('openOrderCount').textContent = data.summary?.open_order_count ?? 0;
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
    {label:'Trade ID', keys:['trade_id','id']}, {label:'หุ้น', keys:['symbol']}, {label:'ฝั่ง', keys:['side']}, {label:'จำนวน', keys:['quantity','qty']}, {label:'ราคา', render:r=>fmtMoney(pick(r,['price','fill_price','entry_price']))}, {label:'เวลา', keys:['executed_at','created_at','timestamp']}
  ]);
}
loadDashboard();
setInterval(loadDashboard, 30000);
</script>
</body>
</html>
"""
