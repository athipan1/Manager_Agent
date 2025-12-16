from fastapi import FastAPI, HTTPException
import uuid
import datetime

from .models import AgentRequestBody, OrchestratorResponse, ReportDetail, ReportDetails, TechnicalAgentResponse, FundamentalAgentResponse, DatabaseAgentResponse
from .agent_client import call_agents
from .synthesis import get_weighted_verdict, get_reasons
from .logger import report_logger

app = FastAPI()

@app.post("/analyze", response_model=OrchestratorResponse)
async def analyze_ticker(request: AgentRequestBody):
    """
    Receives a ticker, queries technical, fundamental, and database agents,
    and returns a synthesized investment report.
    """
    ticker = request.ticker
    tech_response, fund_response, db_response = None, None, None

    # 1. Call agents concurrently
    tech_response_raw, fund_response_raw, db_response_raw = await call_agents(ticker)

    # 2. Handle potential errors from agents
    tech_error = isinstance(tech_response_raw, Exception) or ("error" in tech_response_raw if isinstance(tech_response_raw, dict) else False)
    fund_error = isinstance(fund_response_raw, Exception) or ("error" in fund_response_raw if isinstance(fund_response_raw, dict) else False)
    db_error = isinstance(db_response_raw, Exception) or ("error" in db_response_raw if isinstance(db_response_raw, dict) else False)

    if tech_error and fund_error:
        # If the main analysis agents fail, we can't proceed.
        raise HTTPException(status_code=500, detail="Both Technical and Fundamental Agents failed to respond.")

    # 3. Validate successful responses with Pydantic models
    try:
        if not tech_error:
            tech_response = TechnicalAgentResponse(**tech_response_raw)
        if not fund_error:
            fund_response = FundamentalAgentResponse(**fund_response_raw)
        if not db_error:
            db_response = DatabaseAgentResponse(**db_response_raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse agent responses: {e}")

    # 4. Process agent responses and create details
    tech_detail = None
    if tech_response:
        tech_reason, _ = get_reasons(tech_response.data.action, "hold")
        tech_detail = ReportDetail(
            action=tech_response.data.action,
            score=tech_response.data.confidence_score,
            reason=tech_reason
        )

    fund_detail = None
    if fund_response:
        _, fund_reason = get_reasons("hold", fund_response.data.action)
        fund_detail = ReportDetail(
            action=fund_response.data.action,
            score=fund_response.data.confidence_score,
            reason=fund_reason
        )

    status = "complete" if tech_detail and fund_detail else "partial"

    # 5. Get final verdict from synthesis logic
    final_verdict = get_weighted_verdict(
        tech_detail.action if tech_detail else "hold",
        tech_detail.score if tech_detail else 0.0,
        fund_detail.action if fund_detail else "hold",
        fund_detail.score if fund_detail else 0.0,
    )

    # 6. Construct the final report
    report = OrchestratorResponse(
        report_id=str(uuid.uuid4()),
        ticker=ticker.upper(),
        timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
        final_verdict=final_verdict,
        status=status,
        details=ReportDetails(
            technical=tech_detail,
            fundamental=fund_detail,
        ),
        historical_data=db_response.data.historical_data if db_response else None
    )

    # Log the successful report
    report_logger.info({
        "ticker": report.ticker,
        "final_verdict": report.final_verdict,
        "status": report.status,
        "report_id": report.report_id
    })

    return report
