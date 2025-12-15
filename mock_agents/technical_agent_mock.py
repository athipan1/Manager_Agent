from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

app = FastAPI()

class AgentRequestBody(BaseModel):
    ticker: str
    period: str = "1mo"

@app.post("/analyze")
async def analyze(request: AgentRequestBody):
    if request.ticker.upper() == "AAPL":
        return {
          "agent_type": "technical",
          "ticker": "AAPL",
          "status": "success",
          "data": {
            "current_price": 150.50,
            "action": "buy",
            "confidence_score": 0.85,
            "indicators": {
              "rsi": 35.5,
              "macd": "bullish",
              "trend": "uptrend"
            }
          }
        }
    elif request.ticker.upper() == "GOOG":
         return {
          "agent_type": "technical",
          "ticker": "GOOG",
          "status": "success",
          "data": {
            "current_price": 2800.00,
            "action": "sell",
            "confidence_score": 0.90,
            "indicators": {
              "rsi": 75.0,
              "macd": "bearish",
              "trend": "downtrend"
            }
          }
        }
    else:
        raise HTTPException(status_code=404, detail="Ticker not found")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)