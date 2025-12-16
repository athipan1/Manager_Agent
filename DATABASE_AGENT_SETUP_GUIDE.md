# คู่มือการปรับปรุง Database_Agent ให้เป็น FastAPI Service

เอกสารนี้จะอธิบายขั้นตอนทั้งหมดในการเปลี่ยน `Database_Agent` จากสคริปต์ Python ธรรมดาให้กลายเป็น FastAPI service ที่สามารถทำงานร่วมกับ `Manager_Agent` ผ่าน Docker ได้

## ภาพรวม

เป้าหมายคือการสร้าง API server ครอบ `TradingDB` class ที่มีอยู่ เพื่อให้ `Manager_Agent` สามารถส่งคำสั่ง HTTP มาจัดการข้อมูล (เช่น เช็คยอดเงิน, สร้างคำสั่งซื้อขาย) ได้

---

## ขั้นตอนที่ 1: อัปเดต Dependencies

`Database_Agent` ต้องการ library เพิ่มเติมเพื่อสร้าง API server ให้เพิ่มรายการต่อไปนี้ลงในไฟล์ `Database_Agent/requirements.txt`:

```txt
fastapi
uvicorn[standard]
python-dotenv
```

ไฟล์ `requirements.txt` ที่สมบูรณ์ควรจะมีลักษณะนี้:
```txt
# Original dependencies
sqlite3
# Added for API
fastapi
uvicorn[standard]
python-dotenv
```
*(Note: `sqlite3` เป็น standard library ไม่จำเป็นต้องใส่ แต่ใส่ไว้เพื่อความชัดเจน)*

---

## ขั้นตอนที่ 2: สร้างไฟล์สำหรับ API

ในโปรเจกต์ `Database_Agent` ให้สร้างไฟล์ใหม่ 2 ไฟล์ คือ:
1.  `main.py`: ไฟล์นี้จะเป็นจุดเริ่มต้นของ API server และเป็นที่ที่เราจะกำหนด API endpoints ทั้งหมด
2.  `models.py`: ไฟล์นี้จะใช้กำหนด Pydantic models เพื่อตรวจสอบความถูกต้องของข้อมูลที่รับส่งผ่าน API

โครงสร้างไฟล์สุดท้ายของ `Database_Agent` จะเป็นดังนี้:
```
Database_Agent/
├── .github/
├── tests/
├── Dockerfile          <-- เราจะสร้างไฟล์นี้
├── README.md
├── example.db
├── main.py             <-- ไฟล์ใหม่
├── models.py           <-- ไฟล์ใหม่
├── requirements.txt    <-- อัปเดตไฟล์นี้
└── trading_db.py
```

---

## ขั้นตอนที่ 3: เขียนโค้ดสำหรับ Pydantic Models

เปิดไฟล์ `Database_Agent/models.py` แล้วใส่โค้ด Pydantic model ต่อไปนี้ลงไป โค้ดส่วนนี้จะเหมือนกับที่เพิ่มใน `Manager_Agent` เพื่อให้ทั้งสอง service สื่อสารกันด้วยโครงสร้างข้อมูลเดียวกัน

```python
# In Database_Agent/models.py
from pydantic import BaseModel
from typing import Literal, List

class AccountBalance(BaseModel):
    cash_balance: float

class Position(BaseModel):
    symbol: str
    quantity: int
    average_cost: float

class Order(BaseModel):
    order_id: int
    symbol: str
    order_type: Literal["BUY", "SELL"]
    quantity: int
    price: float
    status: Literal["pending", "executed", "cancelled", "failed"]
    timestamp: str

class CreateOrderBody(BaseModel):
    symbol: str
    order_type: Literal["BUY", "SELL"]
    quantity: int
    price: float

class CreateOrderResponse(BaseModel):
    order_id: int
    status: str
```

---

## ขั้นตอนที่ 4: สร้าง API Server ด้วย FastAPI

เปิดไฟล์ `Database_Agent/main.py` แล้วใส่โค้ดต่อไปนี้ โค้ดนี้จะสร้าง API endpoints ที่ `Manager_Agent` เรียกใช้

```python
# In Database_Agent/main.py
from fastapi import FastAPI, HTTPException
from typing import List
import logging

from .trading_db import TradingDB
from .models import AccountBalance, Position, Order, CreateOrderBody, CreateOrderResponse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI(title="Database Agent")

# สร้าง instance ของ TradingDB เพื่อใช้ตลอดการทำงานของแอปพลิเคชัน
# ใช้ db_file="trading_persistent.db" เพื่อให้ข้อมูลถูกบันทึกถาวรข้าม session
db = TradingDB(db_file="trading_persistent.db")
db.setup_database() # ตรวจสอบและสร้างตารางถ้ายังไม่มี

@app.on_event("startup")
async def startup_event():
    logging.info("Database Agent API starting up.")
    # ไม่ต้องทำอะไรเป็นพิเศษ เพราะ db ถูกสร้างแล้ว

@app.on_event("shutdown")
async def shutdown_event():
    logging.info("Database Agent API shutting down.")
    # การเชื่อมต่อ db จะถูกปิดโดยอัตโนมัติเมื่อ object ถูกทำลาย

# --- API Endpoints ---

@app.get("/accounts/{account_id}/balance", response_model=AccountBalance)
async def get_balance(account_id: int):
    """ดึงข้อมูลยอดเงินคงเหลือ"""
    balance = db.get_account_balance(account_id)
    if balance is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return AccountBalance(cash_balance=balance)

@app.get("/accounts/{account_id}/positions", response_model=List[Position])
async def get_positions_for_account(account_id: int):
    """ดึงข้อมูลหุ้นทั้งหมดในพอร์ต"""
    positions = db.get_positions(account_id)
    return positions

@app.get("/accounts/{account_id}/orders", response_model=List[Order])
async def get_order_history_for_account(account_id: int):
    """ดึงประวัติคำสั่งซื้อขายทั้งหมด"""
    orders = db.get_order_history(account_id)
    return orders

@app.post("/accounts/{account_id}/orders", response_model=CreateOrderResponse)
async def create_new_order(account_id: int, order_body: CreateOrderBody):
    """สร้างคำสั่งซื้อขายใหม่ (สถานะเริ่มต้นคือ 'pending')"""
    order_id = db.create_order(
        account_id=account_id,
        symbol=order_body.symbol,
        order_type=order_body.order_type,
        quantity=order_body.quantity,
        price=order_body.price
    )
    if order_id is None:
        raise HTTPException(status_code=500, detail="Failed to create order")
    return CreateOrderResponse(order_id=order_id, status="pending")

@app.post("/orders/{order_id}/execute")
async def execute_existing_order(order_id: int):
    """ยืนยันการซื้อขาย (execute) จาก order ที่เป็น pending"""
    # ต้องดึงข้อมูล order ก่อน execute เพื่อดูผลลัพธ์
    cursor = db.get_cursor()
    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order_before = cursor.fetchone()

    if not order_before or order_before['status'] != 'pending':
        raise HTTPException(status_code=404, detail=f"Pending order with ID {order_id} not found.")

    db.execute_order(order_id)

    # ดึงข้อมูล order อีกครั้งหลัง execute เพื่อดูสถานะล่าสุด
    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order_after = cursor.fetchone()

    if not order_after:
         raise HTTPException(status_code=500, detail="Order disappeared after execution attempt.")

    return dict(order_after) # คืนค่าเป็น dict เพื่อให้ยืดหยุ่น

```

---

## ขั้นตอนที่ 5: สร้าง Dockerfile

สุดท้าย, สร้างไฟล์ `Database_Agent/Dockerfile` แล้วใส่โค้ดต่อไปนี้:

```Dockerfile
# ใช้ official Python image
FROM python:3.9-slim

# กำหนด working directory ใน container
WORKDIR /code

# Copy ไฟล์ requirements.txt และติดตั้ง dependencies
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy โค้ดทั้งหมดในโปรเจกต์เข้าไปใน container
COPY . /code/

# กำหนด Command ที่จะรันเมื่อ container เริ่มทำงาน
# รัน API server ด้วย Uvicorn บน port 8003
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
```

---

## สรุปและการทำงานร่วมกัน

เมื่อคุณทำตามขั้นตอนทั้งหมดนี้แล้ว `Database_Agent` จะพร้อมทำงานเป็น service

-   เมื่อรัน `docker compose up` จากโปรเจกต์ `Manager_Agent`, `docker-compose.yml` ที่เราแก้ไขจะ:
    1.  Build Docker image สำหรับ `Database_Agent` ตาม `Database_Agent/Dockerfile`
    2.  สร้าง container ชื่อ `database-agent`
    3.  เปิด port `8003` สำหรับการสื่อสารภายใน Docker network
-   `Manager_Agent` จะสามารถเรียกใช้ `Database_Agent` ได้ที่ URL `http://database-agent:8003` ซึ่งเราได้ตั้งค่าไว้ใน `docker-compose.yml` และ `app/config.py` เรียบร้อยแล้ว

ตอนนี้ทั้งสอง service ก็พร้อมที่จะทำงานร่วมกันอย่างสมบูรณ์ครับ
