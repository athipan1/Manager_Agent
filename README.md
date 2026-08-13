# Multi-Agent Trading Orchestrator

ระบบนี้เป็นศูนย์กลางการสั่งการ (Orchestrator) สำหรับระบบเทรดอัตโนมัติที่ใช้สถาปัตยกรรม Multi-Agent โดยทำหน้าที่ประสานงานระหว่าง Agent ต่างๆ เพื่อวิเคราะห์ จัดการความเสี่ยง และดำเนินการเทรดอย่างมีประสิทธิภาพ

---

## 🤖 บทบาทของแต่ละ Agent ในระบบ

ระบบประกอบด้วย Agent เฉพาะทางหลายตัวที่ทำงานร่วมกัน:

1.  **Manager Agent (Orchestrator)**: ทำหน้าที่เป็นส่วนกลางในการรับ Request, ประสานงานเรียก Agent อื่นๆ, สังเคราะห์ผลลัพธ์ (Synthesis), และตัดสินใจในขั้นตอนสุดท้าย
2.  **Database Agent**: จัดการการเชื่อมต่อกับฐานข้อมูลเพื่อเก็บและดึงข้อมูลยอดเงินในบัญชี (Balance), รายการสินทรัพย์ที่ถือครอง (Positions), ประวัติคำสั่งซื้อขาย (Orders), และข้อมูลราคาประวัติ (Price History)
3.  **Technical Agent**: วิเคราะห์สัญญาณทางเทคนิคโดยใช้ตัวบ่งชี้ต่างๆ เช่น RSI, MACD เพื่อประเมินทิศทางราคา
4.  **Fundamental Agent**: วิเคราะห์ปัจจัยพื้นฐานและสุขภาพทางการเงินของสินทรัพย์
5.  **Scanner Agent**: สแกนหาตลาดเพื่อระบุสินทรัพย์ที่มีรูปแบบน่าสนใจ (เช่น Bullish Trend หรือคะแนนพื้นฐานสูง)
6.  **Execution Agent**: รับผิดชอบการส่งคำสั่งซื้อขายไปยังตลาดหรือโบรกเกอร์จริง
7.  **Learning Agent**: วิเคราะห์ผลลัพธ์จากการเทรดในอดีตเพื่อแนะนำการปรับปรุงนโยบาย (Policy) เช่น การปรับน้ำหนักของ Agent หรือการปรับค่าความเสี่ยง
8.  **Market Regime Agent**: วิเคราะห์ว่าสภาพตลาดเป็น bull, bear, sideways หรือ volatile เพื่อกำหนดโหมดความเสี่ยง
9.  **Portfolio Agent**: วิเคราะห์สัดส่วนพอร์ต, cash weight, strategy bucket, exposure และ rebalance advisory
10. **Profit Agent**: วิเคราะห์แผนทำกำไร เช่น partial exit, trailing stop, break-even stop และ exit signal
11. **Performance Agent**: วัดผลงานจาก closed trades เช่น win rate, profit factor, expectancy และ max drawdown

> Alpha-layer agents ทั้ง 4 ตัวเป็น **advisory-only** และไม่ส่งคำสั่งไปที่ Execution Agent โดยตรง Manager ยังคงเป็นผู้ orchestrate ขั้นสุดท้ายเสมอ

---

## 🚀 Workflows การทำงานหลัก

### 1. การวิเคราะห์และเทรดสินทรัพย์เดี่ยว (`/analyze`)
*   รับ Ticker และ Account ID
*   ดึงข้อมูลสถานะบัญชีจาก **Database Agent**
*   เรียก **Technical** และ **Fundamental Agent** เพื่อขอผลวิเคราะห์พร้อมกัน
*   **Orchestrator** รวมคะแนน (Weighted Score) และประเมินผ่าน **Risk Manager**
*   หากผ่านเงื่อนไขความเสี่ยง จะส่งคำสั่งไปที่ **Execution Agent**
*   บันทึกข้อมูลและส่งให้ **Learning Agent** เพื่อพัฒนาระบบ

### 2. การวิเคราะห์หลายสินทรัพย์ (`/analyze-multi`)
*   รับรายการ Ticker หลายตัว
*   ดำเนินการวิเคราะห์แต่ละตัวขนานกัน
*   ใช้ **Portfolio Risk Manager** เพื่อควบคุมความเสี่ยงในภาพรวมของทั้งพอร์ต (Total Exposure) และจัดลำดับความสำคัญของแต่ละตัวเลือก

### 3. การสแกน ค้นหา และวิเคราะห์ (`/scan-and-analyze`)
*   ใช้ **Scanner Agent** ค้นหาสินทรัพย์ที่เป็น Candidate ที่ดีที่สุดตามประเภทที่ระบุ (Technical/Fundamental)
*   ส่งรายชื่อ Candidates เข้าสู่ Workflow ของ `/analyze-multi` โดยอัตโนมัติ

### 4. Alpha Advisory Layer (`/alpha/advisory`)
*   Manager รับ payload สำหรับ Agent ใหม่ทั้ง 4 ตัว
*   Forward ข้อมูลไปยัง **Market Regime**, **Portfolio**, **Profit**, และ **Performance Agent** ตาม key ที่ส่งมา
*   รวมผลลัพธ์กลับมาเป็น advisory metadata
*   ไม่ส่งคำสั่งซื้อขายเอง และไม่ bypass Risk/Execution guardrail

### 5. Idempotent Profit Decision Flow

สำหรับ position ที่มี lifecycle จาก Database Agent, Manager ส่ง
`position_id`, `position_version` และ target flags ไป Profit Agent แล้วใช้
`decision_id` แบบ deterministic ตามลำดับต่อไปนี้:

```text
Database lifecycle -> Profit advisory -> reserve PROPOSED
-> Risk gate -> RISK_APPROVED -> EXECUTION_PENDING
-> Execution (Idempotency-Key = decision_id) -> broker-confirmed EXECUTED
```

Manager จะไม่ mark target ว่า executed ก่อนมี fill ยืนยัน และ retry จะอ่าน
decision/order เดิมก่อนส่งซ้ำ ใช้คำสั่ง orchestration แบบ explicit ได้ด้วย:

```bash
python scripts/profit_decision_orchestrator.py \
  --input-json reports/bucket-profit-review-value_rebound.json \
  --output-json reports/bucket-profit-orchestration-value_rebound.json \
  --trading-mode SIMULATOR
```

ตัว orchestration นี้ปฏิเสธ `LIVE`; ค่า rollout เริ่มต้นยังปิด execution:

```env
PROFIT_DECISION_EXECUTION_ENABLED=false
PROFIT_AUTO_EXIT_ALL_ENABLED=false
```

`exit_all` ยังต้อง manual approval จนกว่าจะเปิด flag เฉพาะใน PAPER/SIMULATOR.

Profit Agent calls use the authenticated `profit-decision.v2` contract.
Manager sends the shared service secret and one correlation ID on every call:

```env
PROFIT_AGENT_ENABLED=true
PROFIT_AGENT_URL=http://profit-agent:8011
PROFIT_AGENT_API_KEY=
PROFIT_MARKET_DATA_MAX_AGE_SECONDS=120
```

Do not commit the key or place it in request/report data. Production Manager
startup fails when Profit is enabled without the key. Legacy Profit responses
remain advisory-display compatible during migration, but Manager logs a
deprecation warning and will not auto-execute a response without deterministic
lifecycle identity.

### 6. Phase 24 / 24.1: GitHub Actions → Secure Owner Snapshot

หน้า `Trading_Frontend` ไม่เรียก Alpaca, Execution_Agent หรือ Database_Agent แบบสดเพื่อแสดงยอดบัญชีเจ้าของ Railway Manager_Agent ทำหน้าที่เป็น read-only snapshot service และข้อมูลบัญชีมาจาก GitHub Actions ที่ตรวจ broker/reconciliation สำเร็จแล้ว

Phase 24.1 กำหนดให้ `Broker Sync Check` เป็น **แหล่งข้อมูลที่ต้องการก่อน (preferred source)** สำหรับ Cash, Equity, Buying Power, Positions และ Open Orders เพราะ workflow นี้อ่าน Alpaca Paper โดยตรงและยืนยันว่า Database_Agent ตรงกับ broker snapshot ล่าสุด ส่วน `Hourly Auto Trading`, `Alpaca Paper Soak` และ `Manual Alpaca Paper Trading` ยังคงรองรับเป็น fallback เมื่อมี `hourly-auto-trading-report` ที่มี account values จริง

```text
GitHub Actions
        │
        ├─ Broker Sync Check  ← preferred owner-balance source
        │      ├─ Execution_Agent อ่าน Alpaca Paper
        │      ├─ reconcile → Database_Agent
        │      ├─ verify mismatch.is_synced = true
        │      └─ broker-sync-check-reports
        │
        ├─ Hourly / Soak / Manual Paper workflow  ← compatible fallback
        │      └─ hourly-auto-trading-report
        │
        └─ Publish Secure Owner Snapshot
               ├─ เลือก broker-sync-check-reports ก่อน ถ้ามี
               ├─ ยอมรับเฉพาะ source run ที่ conclusion=success
               ├─ Broker Sync ต้องเป็น ALPACA + PAPER เท่านั้น
               ├─ สร้าง dashboard-snapshot.v2 privacy=full ใน runner ชั่วคราว
               ├─ ไม่ upload/commit full owner snapshot
               └─ POST HTTPS → Railway Manager_Agent
                         ↓
                  secure owner snapshot store
                         ↓
Trading_Frontend Owner Secure View
        └─ GET /web-control/owner-snapshot + X-Operator-Token
```

กฎ fail-closed ของ Broker Sync source:

- `reconcile.status` ต้องเป็น success และ `reconcile.data.ok=true`
- broker → Database sync ต้องสำเร็จ
- `database_sync_status.data.has_snapshot=true`
- `mismatch.is_synced=true`
- broker account ต้องระบุ `paper=true`; live account จะถูกปฏิเสธ
- account, positions และ orders response ต้องสำเร็จทั้งหมด
- ต้องมีอย่างน้อยหนึ่งค่าจาก `cash`, `equity`, `buying_power`
- source workflow ที่ failure/cancelled หรือ artifact ไม่ครบจะไม่เขียนทับ snapshot ล่าสุด

หลักการสำคัญ:

- `Execution_Agent` ไม่จำเป็นต้อง deploy ค้างบน Railway เพื่อให้หน้าเว็บแสดงยอด เพราะ Broker Sync/Hourly workflows สตาร์ต Execution_Agent ชั่วคราวภายใน GitHub runner
- public snapshot ยังคง `masked` เสมอ เงินสด, equity, buying power และตัวเลข position ไม่ถูก commit แบบเปิดเผย
- full owner snapshot ถูกสร้างเฉพาะใน ephemeral GitHub runner แล้วส่งตรงไป Manager_Agent ผ่าน HTTPS
- Owner Secure View เป็น read-only และ `GET /web-control/owner-snapshot` ไม่ติดต่อ broker หรือ trading agents ตอนผู้ใช้เปิดหน้าเว็บ
- publisher token และ operator token แยกจากกัน
- Manager ปฏิเสธ snapshot ที่ masked, ไม่มี account values, มีชื่อ field ที่เข้าข่าย secret หรือมาจาก workflow run ที่เก่ากว่า snapshot ปัจจุบัน

Environment บน Railway Manager_Agent:

```env
WEB_CONTROL_OPERATOR_TOKEN=<owner-read-token>
OWNER_SNAPSHOT_PUBLISH_TOKEN=<github-actions-publisher-token>
OWNER_SNAPSHOT_STORE_PATH=./config_data/latest-owner-dashboard-snapshot.json
```

GitHub Actions ต้องมี Repository Secret ชื่อ:

```text
OWNER_SNAPSHOT_PUBLISH_TOKEN
```

ค่าต้องตรงกับ `OWNER_SNAPSHOT_PUBLISH_TOKEN` บน Railway และต้องไม่ใช้ token เดียวกับ `WEB_CONTROL_OPERATOR_TOKEN`

กำหนด Repository Variable `OWNER_SNAPSHOT_PUBLISH_URL` ได้ถ้าต้องการเปลี่ยนปลายทาง เช่น:

```text
https://manageragent-production.up.railway.app
```

ถ้าไม่กำหนด workflow จะใช้ Railway production URL ข้างต้นเป็นค่าเริ่มต้น

Endpoints ของ Phase 24 / 24.1:

| Endpoint | Method | Auth | หน้าที่ |
| :--- | :--- | :--- | :--- |
| `/web-control/owner-snapshot/publish` | `POST` | `X-Owner-Snapshot-Token` | รับ full snapshot จาก GitHub Actions และเก็บ snapshot ล่าสุด |
| `/web-control/owner-snapshot` | `GET` | `X-Operator-Token` | ส่ง owner snapshot ล่าสุดให้ Frontend แบบ `no-store` |

ไฟล์ `.github/workflows/publish-owner-snapshot.yml` ฟัง `Broker Sync Check`, `Hourly Auto Trading`, `Alpaca Paper Soak` และ `Manual Alpaca Paper Trading` โดยเลือก `broker-sync-check-reports` ก่อน `hourly-auto-trading-report` เมื่อ run มี artifact ที่รองรับ ส่วน `.github/workflows/publish-dashboard-snapshot.yml` ยังคงรับผิดชอบ public masked snapshot แยกกัน

ตัวแปลง `scripts/normalize_broker_sync_owner_report.py` ลดข้อมูล Broker Sync ให้เหลือเฉพาะ account/positions/orders และ metadata ที่จำเป็น ก่อนส่งผ่าน `scripts/export_dashboard_snapshot.py` เพื่อสร้าง contract เดียวกับ Owner Secure View

> หมายเหตุเรื่อง persistence: default store อยู่ใน filesystem ของ Manager container. หาก Railway service ถูก redeploy ก่อน GitHub Action ถัดไป snapshot อาจยังไม่มีชั่วคราว ควร mount persistent volume แล้วตั้ง `OWNER_SNAPSHOT_STORE_PATH=/data/latest-owner-dashboard-snapshot.json` สำหรับ production ที่ต้องการให้ snapshot อยู่รอดข้าม deployment.

---

## 📡 รายการ Endpoints

### 🧠 Manager Agent (Orchestrator)
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | `GET` | ตรวจสอบความพร้อมของระบบและการเชื่อมต่อกับ Database Agent |
| `/analyze` | `POST` | วิเคราะห์และดำเนินการเทรดสำหรับ 1 สินทรัพย์ |
| `/analyze-multi` | `POST` | วิเคราะห์และจัดการความเสี่ยงระดับพอร์ตสำหรับหลายสินทรัพย์ |
| `/scan-and-analyze` | `POST` | ค้นหาสินทรัพย์ที่น่าสนใจและวิเคราะห์/เทรดทันที |
| `/alpha/health` | `GET` | ตรวจ health ของ Alpha-layer agents |
| `/alpha/advisory` | `POST` | รวม advisory จาก Market Regime, Portfolio, Profit และ Performance Agent |
| `/web-control/owner-snapshot` | `GET` | อ่าน secure owner snapshot ล่าสุดจาก GitHub Actions |
| `/web-control/owner-snapshot/publish` | `POST` | รับ secure owner snapshot จาก GitHub Actions |

### Alpha Advisory payload

```json
{
  "market_regime": {
    "symbol": "SPY",
    "price": 550,
    "sma_50": 530,
    "sma_200": 500,
    "atr_pct": 0.015,
    "vix": 15,
    "market_breadth_pct": 0.7
  },
  "portfolio": {
    "equity": 100000,
    "cash": 20000,
    "mode": "normal",
    "positions": []
  },
  "profit": {
    "position": {
      "symbol": "ADBE",
      "quantity": 20,
      "entry_price": 100,
      "current_price": 120,
      "stop_loss": 90
    }
  },
  "performance": {
    "initial_equity": 100000,
    "trades": [],
    "equity_curve": []
  }
}
```

### Run with alpha agents

```bash
docker compose -f docker-compose.yml -f docker-compose.alpha.yml up --build
```

Required sibling repos:

```text
../Market_Regime_Agent
../Portfolio_Agent
../Profit_Agent
../Performance_Agent
```

### 💾 Database Agent
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/accounts/{id}/balance` | `GET` | ดึงยอดเงินคงเหลือในบัญชี |
| `/accounts/{id}/positions` | `GET` | ดึงรายการสินทรัพย์ที่ถือครอง |
| `/accounts/{id}/trade_history` | `GET` | ดึงประวัติการเทรด |
| `/prices/{symbol}` | `GET` | ดึงข้อมูลราคาประวัติ |

### 🔍 Scanner Agent
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/scan` | `POST` | สแกนทางเทคนิคเพื่อหา Candidates |
| `/scan/fundamental` | `POST` | สแกนปัจจัยพื้นฐานเพื่อหา Candidates |

### ⚡ Execution & Learning
| Agent | Endpoint | Method | Description |
| :--- | :--- | :--- | :--- |
| **Execution** | `/execute` | `POST` | ส่งคำสั่งซื้อขาย |
| **Learning** | `/learn` | `POST` | ประมวลผลข้อมูลเพื่อปรับปรุง Policy |

---

## 📄 โครงสร้างข้อมูล (Data Schemas)

### 1. Standard Agent Response
โครงสร้างมาตรฐานที่ทุก Agent ต้องใช้ในการตอบกลับ:
```json
{
  "status": "success | error"
}
```