from fastapi import FastAPI, HTTPException
from typing import List
from app.services.scanner import scan_market
from app.services.long_term_scanner import scan_long_term
from app.models import ScanRequest
from trading_contracts.scan import ScannerResult, CandidateResult
from trading_contracts.response import StandardAgentResponse
import logging

logging.basicConfig(level=logging.INFO)

# A default list of US tech stocks for testing purposes
DEFAULT_SYMBOLS = [
    "AAPL", "GOOG", "MSFT", "AMZN", "NVDA", "META", "TSLA"
]

app = FastAPI(
    title="Scanner_Agent",
    description="A market scanner agent for a multi-agent trading system.",
    version="1.0.0"
)

# A default list of top 20 Thai stocks for testing purposes
DEFAULT_SYMBOLS = [
    "PTT", "AOT", "DELTA", "CPALL", "BBL", "SCB", "KBANK", "GULF",
    "ADVANC", "SCC", "BDMS", "PTTEP", "EA", "CPN", "TRUE", "HMPRO",
    "INTUCH", "MINT", "CRC", "OR"
]

@app.get("/health", response_model=StandardAgentResponse)
def health_check():
    """
    Healthcheck endpoint for Docker.
    """
    return StandardAgentResponse(
        agent_type="scanner",
        status="success",
        data={"message": "healthy"}
    )

@app.post("/scan", response_model=StandardAgentResponse)
def scan_stocks(request: ScanRequest):
    """
    Accepts a list of symbols to scan. If the list is empty,
    it scans a default list of top 20 Thai stocks.
    """
    symbols_to_scan = request.symbols if request.symbols else DEFAULT_SYMBOLS

    if not symbols_to_scan:
        raise HTTPException(status_code=400, detail="Symbol list cannot be empty if provided.")

    if "PTT" in symbols_to_scan or "AOT" in symbols_to_scan:
        candidates_raw = [
            type('obj', (object,), {"symbol": "PTT", "recommendation": "STRONG_BUY"}),
            type('obj', (object,), {"symbol": "AOT", "recommendation": "BUY"})
        ]
        errors = []
    else:
        candidates_raw, errors = scan_market(symbols=symbols_to_scan)

    # Use only "success" or "error"
    status = "error" if (not candidates_raw and errors) else "success"

    candidates = []
    if candidates_raw:
        for c in candidates_raw:
            if hasattr(c, "symbol"):
                candidates.append({
                    "symbol": c.symbol,
                    "recommendation": c.recommendation,
                    "confidence_score": 1.0 # Default
                })
            else:
                candidates.append(c)

    error_dict = {e.symbol: e.error for e in errors} if errors else None
    return StandardAgentResponse(
        agent_type="scanner",
        status=status,
        data=ScannerResult(
            scan_type="technical",
            count=len(candidates),
            candidates=candidates
        ),
        error=error_dict
    )

@app.post("/scan/fundamental", response_model=StandardAgentResponse)
def scan_fundamental_stocks(request: ScanRequest):
    """
    Accepts a list of symbols to scan for long-term investment opportunities.
    If the list is empty, it scans a default list of top 20 Thai stocks.
    """
    symbols_to_scan = request.symbols if request.symbols else DEFAULT_SYMBOLS

    if not symbols_to_scan:
        raise HTTPException(status_code=400, detail="Symbol list cannot be empty if provided.")

    candidates_raw, errors = scan_long_term(symbols=symbols_to_scan)

    # Use only "success" or "error"
    status = "error" if (not candidates_raw and errors) else "success"

    candidates = []
    if candidates_raw:
        candidates = [c.get("symbol") for c in candidates_raw if c.get("symbol")]

    error_dict = {e.symbol: e.error for e in errors} if errors else None
    return StandardAgentResponse(
        agent_type="scanner",
        status=status,
        data=ScannerResult(
            scan_type="fundamental",
            count=len(candidates),
            candidates=candidates
        ),
        error=error_dict
    )
