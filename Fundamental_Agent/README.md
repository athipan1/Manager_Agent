# Fundamental Agent - ระบบวิเคราะห์ปัจจัยพื้นฐานหุ้น

โปรเจกต์นี้เป็นไมโครเซอร์วิสสำหรับวิเคราะห์ปัจจัยพื้นฐานของหุ้น (Fundamental Analysis) โดยใช้ข้อมูลทางการเงินและเทคโนโลยี LLM (Google Gemini) เพื่อช่วยในการตัดสินใจลงทุนตามสไตล์การลงทุนต่างๆ

## รายละเอียดทางเทคนิคสำหรับนักพัฒนา (Technical Overview)

ระบบทำงานเป็นกระบวนการ (Pipeline) ดังนี้:
1.  **Data Fetching**: ดึงข้อมูลทางการเงินล่าสุดผ่าน `yfinance` ซึ่งครอบคลุมทั้งงบการเงิน อัตราส่วนทางการเงิน และข้อมูลการจ่ายปันผลย้อนหลัง
2.  **Caching System**: ใช้ระบบ Cache สองระดับ (File-based cache) สำหรับข้อมูลดิบและผลการวิเคราะห์สุดท้าย เพื่อลด Latency และลดการเรียกใช้ API ภายนอกโดยไม่จำเป็น
3.  **Scoring Engine**: คำนวณคะแนนพื้นฐาน (Scoring) ตามสไตล์การลงทุนที่เลือก (Growth, Value, Dividend) โดยใช้ตัวชี้วัด เช่น ROE, D/E Ratio, Revenue Growth, PEG Ratio และ Yield
4.  **LLM Analysis**: นำข้อมูลที่ผ่านการประมวลผลและคะแนนที่คำนวณได้มาสร้าง Prompt แบบ Chain-of-Thought เพื่อให้ Gemini API วิเคราะห์เชิงลึกและสรุปเป็นข้อความภาษาไทย
5.  **Fallback Mechanism**: มีระบบสำรอง (Rule-based Analyzer) ที่จะทำงานโดยอัตโนมัติหากการวิเคราะห์ผ่าน LLM เกิดข้อผิดพลาด เพื่อให้ระบบยังคงส่งคืนผลลัพธ์ที่เชื่อถือได้

---

## API Endpoints และ Schema ข้อมูล

### 1. วิเคราะห์หุ้น (Analyze Ticker)
**Endpoint:** `POST /analyze`

ใช้สำหรับการสั่งวิเคราะห์หุ้นรายตัวตามสไตล์ที่ต้องการ

#### Request Body (`TickerRequest`)
| ฟิลด์ | ประเภท (Type) | คำอธิบาย |
| :--- | :--- | :--- |
| `ticker` | `string` | สัญลักษณ์หุ้นที่ต้องการวิเคราะห์ (เช่น "AAPL", "MSFT") |
| `style` | `string` | สไตล์การลงทุน: `"growth"`, `"value"`, หรือ `"dividend"` (Default: `"growth"`) |

#### Response Body (`StandardAgentResponse`)
| ฟิลด์ | ประเภท (Type) | คำอธิบาย |
| :--- | :--- | :--- |
| `agent_type` | `string` | ประเภทของเอเจนต์ (ค่าเริ่มต้นคือ `"fundamental"`) |
| `version` | `string` | เวอร์ชันปัจจุบันของระบบ |
| `status` | `string` | สถานะการทำงาน (`"success"` หรือ `"error"`) |
| `timestamp` | `datetime` | เวลาที่สร้างผลลัพธ์ (รูปแบบ ISO 8601 UTC) |
| `data` | `object` | ข้อมูลผลลัพธ์หลัก (ประกอบด้วย `action`, `confidence_score`, `reason`, `source`) |
| `error` | `object` | ข้อมูลข้อผิดพลาด (จะมีค่าเมื่อ `status` เป็น `"error"`) |
| `metadata` | `object` | ข้อมูลส่วนขยายอื่นๆ |

**รายละเอียดในวัตถุ `data`:**
| ฟิลด์ | ประเภท (Type) | คำอธิบาย |
| :--- | :--- | :--- |
| `action` | `string` | คำแนะนำเบื้องต้น: `"buy"`, `"hold"`, หรือ `"sell"` |
| `confidence_score` | `float` | คะแนนความมั่นใจหรือคะแนนพื้นฐานหุ้น (ค่าระหว่าง 0.0 ถึง 1.0) |
| `reason` | `string` | บทวิเคราะห์สรุปเชิงคุณภาพภาษาไทย |
| `source` | `string` | แหล่งที่มาของผลลัพธ์ (เช่น `"fundamental_agent"`) |

**รายละเอียดในวัตถุ `error`:**
| ฟิลด์ | ประเภท (Type) | คำอธิบาย |
| :--- | :--- | :--- |
| `code` | `string` | รหัสข้อผิดพลาดเชิงเทคนิค (เช่น `"TICKER_NOT_FOUND"`, `"MODEL_ERROR"`) |
| `message` | `string` | ข้อความอธิบายสาเหตุของข้อผิดพลาด |
| `retryable` | `boolean` | ระบุว่าระบบควรลองส่งคำขอใหม่อีกครั้งหรือไม่ |

### 2. ตรวจสอบสถานะระบบ (Health Check)
**Endpoint:** `GET /health`
- **Response:**
```json
{
  "agent_type": "fundamental",
  "version": "2.0.0",
  "status": "success",
  "timestamp": "2024-05-20T10:00:00Z",
  "data": {
    "status": "healthy"
  }
}
```

### 3. หน้าแรก (Root)
**Endpoint:** `GET /`
- **Response:**
```json
{
  "agent_type": "fundamental",
  "version": "2.0.0",
  "status": "success",
  "timestamp": "2024-05-20T10:00:00Z",
  "data": {
    "message": "Hello World"
  }
}
```

---

## โครงสร้างโมดูลที่สำคัญ
- `app/main.py`: จุดเริ่มต้นของ FastAPI และการจัดการ Routing
- `app/fundamental_agent.py`: จัดการ Workflow การวิเคราะห์หลักและระบบ Cache
- `app/analyzer.py`: ตรรกะการคำนวณคะแนนและการเชื่อมต่อกับ LLM
- `app/data_fetcher.py`: โมดูลสำหรับดึงและจัดรูปแบบข้อมูลจาก yfinance
- `app/rule_based_analyzer.py`: ระบบวิเคราะห์สำรองแบบเงื่อนไข (Rule-based)
- `app/models.py`: นิยาม Pydantic models และ Enum สำหรับ Request/Response
