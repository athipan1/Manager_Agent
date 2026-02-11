from tradingview_ta import TA_Handler, Interval
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Dict, Any

from app.models import Candidate, ErrorDetail

def fetch_analysis(symbol: str, screener: str, exchange: str) -> Dict[str, Any]:
    """
    Fetches technical analysis for a single stock symbol.
    """
    try:
        handler = TA_Handler(
            symbol=symbol,
            screener=screener,
            exchange=exchange,
            interval=Interval.INTERVAL_1_DAY
        )
        analysis = handler.get_analysis().summary
        return {"symbol": symbol, "analysis": analysis}
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

def scan_market(symbols: List[str], screener: str = "thailand", exchange: str = "SET") -> Tuple[List[Candidate], List[ErrorDetail]]:
    """
    Scans a list of stock symbols in parallel and filters for strong buy or buy recommendations.
    """
    candidates = []
    errors = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all tasks to the executor
        future_to_symbol = {executor.submit(fetch_analysis, symbol, screener, exchange): symbol for symbol in symbols}

        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                result = future.result()
                if "error" in result:
                    # Capture the specific error message from the result
                    error_message = result.get("error", "Unknown error")
                    errors.append(ErrorDetail(symbol=symbol, error=error_message))
                else:
                    analysis = result.get("analysis", {})
                    recommendation = analysis.get("RECOMMENDATION")

                    if recommendation in ["BUY", "STRONG_BUY"]:
                        candidates.append(Candidate(
                            symbol=symbol,
                            recommendation=recommendation,
                            details=analysis
                        ))
            except Exception as e:
                # Capture any other unexpected errors during processing
                errors.append(ErrorDetail(symbol=symbol, error=str(e)))

    return candidates, errors
