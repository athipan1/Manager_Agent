from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Literal, Dict
from .fundamental_agent import run_analysis
from .models import StandardAgentResponse, Action, FundamentalAnalysisData, HealthData

app = FastAPI()


class TickerRequest(BaseModel):
    ticker: str
    style: Literal["growth", "value", "dividend"] = "growth"


@app.get("/", response_model=StandardAgentResponse[Dict[str, str]])
def read_root():
    return StandardAgentResponse(
        status="success",
        data={"message": "Hello World"}
    )


@app.get("/health", response_model=StandardAgentResponse[HealthData])
def health():
    return StandardAgentResponse(
        status="success",
        data=HealthData(status="healthy")
    )


@app.post("/analyze", response_model=StandardAgentResponse[FundamentalAnalysisData])
def analyze_ticker(request: TickerRequest, req: Request):
    """
    Analyzes a stock ticker and returns a standardized analysis response.
    It handles success and failure cases by returning a consistent schema.
    """
    correlation_id = req.headers.get("X-Correlation-ID")
    analysis_result = run_analysis(
        request.ticker,
        request.style,
        correlation_id=correlation_id
    )

    # Check if the analysis failed
    if "error" in analysis_result:
        error_reason = analysis_result["error"]
        error_code = "ANALYSIS_FAILED"  # Default error code

        if error_reason == "ticker_not_found":
            error_code = "TICKER_NOT_FOUND"
        elif error_reason == "data_not_enough":
            error_code = "INSUFFICIENT_DATA"
        elif error_reason == "model_error":
            error_code = "MODEL_ERROR"

        return StandardAgentResponse(
            status="error",
            data=FundamentalAnalysisData(
                action=Action.HOLD,
                confidence_score=0.0,
                reason=error_reason
            ),
            error={
                "code": error_code,
                "message": error_reason,
                "retryable": False
            }
        )

    # --- Process successful analysis ---
    action_map = {
        "strong_buy": Action.BUY,
        "buy": Action.BUY,
        "neutral": Action.HOLD,
        "sell": Action.SELL,
        "strong_sell": Action.SELL,
    }
    action = action_map.get(analysis_result.get("strength"), Action.HOLD)

    return StandardAgentResponse(
        status="success",
        data=FundamentalAnalysisData(
            action=action,
            confidence_score=analysis_result.get("score", 0.0),
            reason=analysis_result.get("reasoning", "ไม่สามารถสร้างคำวิเคราะห์ได้"),
            source="fundamental_agent"
        )
    )
