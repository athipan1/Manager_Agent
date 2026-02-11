# Technical Analysis Agent (ตัวแทนวิเคราะห์ทางเทคนิค)

โปรเจกต์นี้เป็น Microservice สำหรับวิเคราะห์ทางเทคนิคของหุ้น (Technical Analysis) โดยใช้ข้อมูลราคาในอดีตเพื่อสร้างสัญญาณซื้อ (Buy), ขาย (Sell) หรือถือ (Hold) ตามตัวชี้วัดทางเทคนิค (Technical Indicators) เพื่อส่งข้อมูลให้กับระบบ Orchestrator ต่อไป

## การทำงานของโปรเจกต์
1. รับคำขอผ่าน REST API พร้อมระบุชื่อย่อหุ้น (Ticker)
2. ดึงข้อมูลราคาย้อนหลัง 5 ปีจาก Yahoo Finance โดยใช้ `yfinance`
3. คำนวณตัวชี้วัดทางเทคนิค (SMA, RSI, MACD) โดยใช้ `pandas-ta`
4. วิเคราะห์ข้อมูลและสร้างสัญญาณการซื้อขายตามอัลกอริทึมที่กำหนด
5. ส่งผลลัพธ์กลับในรูปแบบ JSON ตามมาตรฐาน `StandardResponse` ที่กำหนดไว้

## อัลกอริทึมการตัดสินใจ (Trading Strategy)
การสร้างสัญญาณจะพิจารณาจากแนวโน้ม (Trend) และตัวชี้วัดประกอบกัน ดังนี้:

### 1. การกำหนดแนวโน้ม (Trend Determination)
- **Uptrend (แนวโน้มขาขึ้น):** ราคาปัจจุบัน > เส้นค่าเฉลี่ย SMA 200 วัน
- **Downtrend (แนวโน้มขาลง):** ราคาปัจจุบัน < เส้นค่าเฉลี่ย SMA 200 วัน
- **Sideways (แนวโน้มออกข้าง):** กรณีอื่นๆ

### 2. เงื่อนไขสัญญาณ (Signals)
- **BUY (ซื้อ):**
    - อยู่ในแนวโน้มขาขึ้น (Uptrend) **และ**
    - RSI < 30 (ภาวะขายมากเกินไป) **และ**
    - MACD Line > MACD Signal (เกิดจุดตัด Bullish Crossover)
- **SELL (ขาย):**
    - อยู่ในแนวโน้มขาลง (Downtrend) **และ**
    - RSI > 70 (ภาวะซื้อมากเกินไป) **และ**
    - MACD Line < MACD Signal (เกิดจุดตัด Bearish Crossover)
- **HOLD (ถือ):**
    - หากไม่เข้าเงื่อนไข BUY หรือ SELL

### 3. คะแนนความเชื่อมั่น (Confidence Score)
- **Buy/Sell:** 0.75
- **Hold:** 0.50
- **Error:** 0.00

---

## ข้อมูลสำหรับนักพัฒนา (Developer Guide)

### โครงสร้างไฟล์ในระบบ
- `app/main.py`: จุดเริ่มต้นของแอปพลิเคชัน FastAPI กำหนด Endpoints และการจัดการ Request/Response
- `app/models.py`: คำจำกัดความของ Pydantic models (Schema) เพื่อควบคุมโครงสร้างข้อมูล
- `app/service.py`: ตรรกะทางธุรกิจ (Business Logic) การคำนวณตัวชี้วัด และอัลกอริทึมการวิเคราะห์
- `Dockerfile`: ไฟล์สำหรับสร้าง Docker Image สำหรับการ Deploy ในรูปแบบ Container

### เทคโนโลยีที่ใช้
- **FastAPI**: Web Framework ประสิทธิภาพสูงสำหรับสร้าง API
- **yfinance**: ไลบรารีสำหรับดึงข้อมูลการเงินจาก Yahoo Finance
- **pandas-ta**: ส่วนขยายของ Pandas สำหรับการคำนวณทางเทคนิค (Technical Analysis Indicators)
- **Pydantic**: สำหรับการตรวจสอบความถูกต้องของข้อมูล (Data Validation)

---

## API Endpoints และ Schema ข้อมูล

### 1. วิเคราะห์หุ้น (Analyze Ticker)
**Endpoint:** `POST /analyze`

#### Request Body (`AnalyzeRequest`)
```json
{
  "ticker": "AOT.BK"
}
```

#### Response Body (`StandardResponse`) - กรณีสำเร็จ
```json
{
  "status": "success",
  "agent_type": "technical",
  "version": "1.1.0",
  "timestamp": "2023-10-27T10:00:00.000000",
  "data": {
    "action": "hold",
    "confidence": 0.5,
    "reason": "Signal 'hold' generated. Trend: Uptrend, RSI: 45.23.",
    "current_price": 70.25,
    "indicators": {
      "trend": "Uptrend",
      "rsi": 45.23,
      "macd_line": 0.15,
      "macd_signal": 0.10
    }
  },
  "error": null
}
```

#### Response Body (`StandardResponse`) - กรณีเกิดข้อผิดพลาดทางธุรกิจ
```json
{
  "status": "error",
  "agent_type": "technical",
  "version": "1.1.0",
  "timestamp": "2023-10-27T10:05:00.000000",
  "data": {
    "action": "hold",
    "confidence": 0.0,
    "reason": "ticker_not_found"
  },
  "error": {
    "code": "TICKER_NOT_FOUND",
    "message": "No data found for ticker 'INVALID'",
    "retryable": false
  }
}
```

### 2. ตรวจสอบความพร้อมของระบบ (Health Check)
**Endpoint:** `GET /health`
- **Response:** `{"status": "ok"}`

### 3. หน้าเริ่มต้น (Root)
**Endpoint:** `GET /`
- **Response:** `{"message": "Technical Analysis Agent is running."}`
