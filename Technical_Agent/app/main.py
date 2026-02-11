from fastapi import FastAPI, Header
from typing import Optional

# Import the business logic from the service module
from .service import analyze_stock
# Import models from the newly created models module
from .models import (
    AnalyzeRequest,
    StandardAgentData,
    StandardAgentResponse,
    Action
)

# --- API Metadata ---
app = FastAPI(
    title="Technical Analysis Agent",
    description="An API for performing technical analysis on stock tickers, "
    "conforming to the Orchestrator's canonical schema.",
    version="1.1.0",
)


# --- API Endpoints ---

@app.post(
    "/analyze",
    summary="Analyze a stock ticker for the Orchestrator",
    tags=["Analysis"],
    response_model=StandardAgentResponse[StandardAgentData]
)
def analyze_ticker_endpoint(
    request: AnalyzeRequest,
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID")
):
    """
    Analyzes a stock ticker and returns a result conforming to the
    Orchestrator's canonical schema.

    - **Receives**: A stock `ticker` and an optional `X-Correlation-ID` header.
    - **Returns**: A structured JSON response with an `action`, `confidence`,
      `reason`, and other relevant data.
    - **Error Handling**: Business logic errors (e.g., ticker not found) are
      handled gracefully and returned with an HTTP 200 status code,
      with the error details encoded in the `reason` field.
    """
    # The service function now handles internal errors and returns the
    # appropriate dictionary structure for both success and failure cases.
    service_result = analyze_stock(
        ticker=request.ticker,
        correlation_id=x_correlation_id
    )

    # Map the service result data to the new StandardAgentData model
    # Note: confidence_score is used, and action is ensured to be lowercase
    raw_data = service_result["data"]
    analysis_data = StandardAgentData(
        action=Action(raw_data["action"].lower()),
        confidence_score=raw_data["confidence_score"],
        reason=raw_data["reason"],
        current_price=raw_data.get("current_price"),
        indicators=raw_data.get("indicators")
    )

    # Instantiate the StandardAgentResponse model.
    return StandardAgentResponse(
        status=service_result["status"],
        agent_type="technical",
        version="1.1.0",
        data=analysis_data,
        error=service_result.get("error")
    )


@app.get("/health", summary="Health Check", tags=["Health"], response_model=StandardAgentResponse[dict])
def health_check():
    """Returns a 200 OK status if the service is healthy."""
    return StandardAgentResponse(
        status="success",
        agent_type="technical",
        version="1.1.0",
        data={"status": "ok"}
    )


@app.get("/", include_in_schema=False)
def root():
    """A simple root endpoint to confirm the API is running."""
    return {"message": "Technical Analysis Agent is running."}
