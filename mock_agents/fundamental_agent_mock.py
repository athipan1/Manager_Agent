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
          "agent_type": "fundamental",
          "ticker": "AAPL",
          "status": "success",
          "data": {
            "action": "hold",
            "confidence_score": 0.60,
            "analysis_summary": "รายได้เติบโตดีแต่ PE สูงเกินไป ข่าวล่าสุดเป็นบวก",
            "metrics": {
              "pe_ratio": 28.5,
              "eps": 6.5,
              "news_sentiment": "positive"
            }
          }
        }
    elif request.ticker.upper() == "GOOG":
        return {
          "agent_type": "fundamental",
          "ticker": "GOOG",
          "status": "success",
          "data": {
            "action": "buy",
            "confidence_score": 0.95,
            "analysis_summary": "Strong revenue growth and positive market sentiment.",
            "metrics": {
              "pe_ratio": 25.0,
              "eps": 110.0,
              "news_sentiment": "positive"
            }
          }
        }
    else:
        raise HTTPException(status_code=404, detail="Ticker not found")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)