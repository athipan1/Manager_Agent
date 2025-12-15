from fastapi import FastAPI, HTTPException
import uuid
import datetime

from .models import AgentRequestBody, OrchestratorResponse, ReportDetail, ReportDetails, TechnicalAgentResponse, FundamentalAgentResponse
from .agent_client import call_agents
from .synthesis import get_weighted_verdict, get_reasons

app = FastAPI()

@app.post("/analyze", response_model=OrchestratorResponse)
async def analyze_ticker(request: AgentRequestBody):
    """
    Receives a ticker, queries technical and fundamental agents,
    and returns a synthesized investment report.
    """
    ticker = request.ticker

    # 1. Call agents concurrently
    tech_response_raw, fund_response_raw = await call_agents(ticker)

    # 2. Handle potential errors from agents
    if "error" in tech_response_raw:
        raise HTTPException(status_code=500, detail=f"Technical Agent Error: {tech_response_raw['error']}")
    if "error" in fund_response_raw:
        raise HTTPException(status_code=500, detail=f"Fundamental Agent Error: {fund_response_raw['error']}")

    # 3. Validate responses with Pydantic models
    try:
        tech_response = TechnicalAgentResponse(**tech_response_raw)
        fund_response = FundamentalAgentResponse(**fund_response_raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse agent responses: {e}")

    # 4. Extract actions from agent responses
    tech_action = tech_response.data.action
    fund_action = fund_response.data.action

    # 5. Get final verdict and reasons from synthesis logic
    final_verdict = get_weighted_verdict(
        tech_action,
        tech_response.data.confidence_score,
        fund_action,
        fund_response.data.confidence_score,
    )
    tech_reason, fund_reason = get_reasons(tech_action, fund_action)

    # 6. Construct the final report
    report = OrchestratorResponse(
        report_id=str(uuid.uuid4()),
        ticker=ticker.upper(),
        timestamp=datetime.datetime.utcnow().isoformat(),
        final_verdict=final_verdict,
        details=ReportDetails(
            technical=ReportDetail(
                action=tech_action,
                score=tech_response.data.confidence_score,
                reason=tech_reason,
            ),
            fundamental=ReportDetail(
                action=fund_action,
                score=fund_response.data.confidence_score,
                reason=fund_reason,
            ),
        )
    )

    return report