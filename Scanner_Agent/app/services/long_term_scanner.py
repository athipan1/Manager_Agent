from typing import List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.data_sources import financial_statements, market_data
from app.analyzers import quality_analyzer, growth_analyzer, valuation_analyzer
from app.scoring import fundamental_score
from app.models import ErrorDetail

def analyze_stock(symbol: str) -> Tuple[str, Dict[str, Any]]:
    """
    Performs a full fundamental analysis on a single stock symbol.
    """
    financials = financial_statements.get_financials(symbol)
    market = market_data.get_market_data(symbol)

    if not financials or not market:
        raise ValueError("Missing essential financial or market data")

    # --- Analysis ---
    quality_metrics = {
        "roe": quality_analyzer.calculate_roe(financials),
        "roa": quality_analyzer.calculate_roa(financials),
        "debt_to_equity": quality_analyzer.calculate_debt_to_equity(financials),
        "free_cash_flow": quality_analyzer.calculate_free_cash_flow(financials),
        "profit_margins": quality_analyzer.calculate_profit_margins(financials),
    }

    growth_metrics = {
        "revenue_cagr": growth_analyzer.calculate_revenue_cagr(financials),
        "eps_growth": growth_analyzer.calculate_eps_growth(financials),
    }

    valuation_metrics = {
        "pe_ratio": valuation_analyzer.get_pe_ratio(market),
        "peg_ratio": valuation_analyzer.get_peg_ratio(market),
        "pb_ratio": valuation_analyzer.get_pb_ratio(market),
    }

    # --- Scoring ---
    quality_score = fundamental_score.calculate_quality_score(quality_metrics)
    growth_score = fundamental_score.calculate_growth_score(growth_metrics)
    valuation_score = fundamental_score.calculate_valuation_score(valuation_metrics)

    scores = {
        "quality_score": quality_score,
        "growth_score": growth_score,
        "valuation_score": valuation_score,
    }

    final_score = fundamental_score.calculate_fundamental_score(scores)

    if final_score is None:
        raise ValueError("Could not calculate a final score due to missing data")

    grade = fundamental_score.get_grade(final_score)

    # --- Thesis Generation (Template-based) ---
    thesis = (
        f"{symbol} demonstrates {'strong' if quality_score > 70 else 'fair'} business quality, "
        f"with {'robust' if growth_score > 70 else 'moderate'} growth prospects. "
        f"The stock appears {'undervalued' if valuation_score > 70 else 'fairly valued'}."
    )

    return symbol, {
        "grade": grade,
        "fundamental_score": round(final_score, 2),
        "quality": {**quality_metrics, "score": round(quality_score, 2) if quality_score is not None else None},
        "growth": {**growth_metrics, "score": round(growth_score, 2) if growth_score is not None else None},
        "valuation": {**valuation_metrics, "score": round(valuation_score, 2) if valuation_score is not None else None},
        "thesis": thesis,
    }

def scan_long_term(symbols: List[str]) -> Tuple[List[Dict[str, Any]], List[ErrorDetail]]:
    """
    Scans a list of stock symbols for long-term investment opportunities.
    """
    candidates = []
    errors = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_symbol = {executor.submit(analyze_stock, symbol): symbol for symbol in symbols}

        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                _, result = future.result()
                candidates.append({"symbol": symbol, **result})
            except Exception as e:
                errors.append(ErrorDetail(symbol=symbol, error=str(e)))

    # Rank candidates by fundamental_score
    candidates.sort(key=lambda x: x["fundamental_score"], reverse=True)

    return candidates, errors
