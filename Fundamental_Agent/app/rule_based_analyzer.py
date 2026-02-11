"""
This module provides a rule-based fallback for financial analysis when the
primary AI model fails. It generates a simplified analysis based on a few
key metrics for different investment styles.
"""
from .analyzer import generate_actionable_strength


def _analyze_growth(data: dict) -> dict:
    """Rule-based analysis for Growth style."""
    revenue_growth = data.get("Revenue Growth", 0) or 0
    eps_growth = data.get("EPS Growth", 0) or 0

    score = 0.3
    conditions_met = []
    conditions_not_met = []

    if revenue_growth > 0.10:
        score += 0.35
        conditions_met.append("Revenue Growth > 10%")
    else:
        conditions_not_met.append("Revenue Growth <= 10%")

    if eps_growth > 0.10:
        score += 0.35
        conditions_met.append("EPS Growth > 10%")
    else:
        conditions_not_met.append("EPS Growth <= 10%")

    score = min(score, 1.0)
    reasoning = (
        "วิเคราะห์ตามกฎพื้นฐาน (Rule-based Fallback): "
        f"หุ้นเติบโตจะพิจารณาจากเงื่อนไข: Revenue Growth > 10% และ EPS Growth > 10%. "
        f"ผลลัพธ์: [Met: {', '.join(conditions_met) if conditions_met else 'None'}] "
        f"[Not Met: {', '.join(conditions_not_met) if conditions_not_met else 'None'}]."
    )

    return {
        "strength": generate_actionable_strength(score),
        "reasoning": reasoning,
        "score": round(score, 2),
        "score_details": {"growth": round(score, 2)},
        "key_metrics": data,
        "analysis_source": "rule_based_fallback"
    }


def _analyze_value(data: dict) -> dict:
    """Rule-based analysis for Value style."""
    pe_ratio = data.get("P/E Ratio", float('inf')) or float('inf')
    pb_ratio = data.get("P/B Ratio", float('inf')) or float('inf')

    score = 0.3
    conditions_met = []
    conditions_not_met = []

    if 0 < pe_ratio < 15:
        score += 0.35
        conditions_met.append("P/E Ratio < 15")
    else:
        conditions_not_met.append("P/E Ratio >= 15 or N/A")

    if 0 < pb_ratio < 1:
        score += 0.35
        conditions_met.append("P/B Ratio < 1")
    else:
        conditions_not_met.append("P/B Ratio >= 1 or N/A")

    score = min(score, 1.0)
    reasoning = (
        "วิเคราะห์ตามกฎพื้นฐาน (Rule-based Fallback): "
        f"หุ้นคุณค่าจะพิจารณาจากเงื่อนไข: P/E Ratio < 15 และ P/B Ratio < 1. "
        f"ผลลัพธ์: [Met: {', '.join(conditions_met) if conditions_met else 'None'}] "
        f"[Not Met: {', '.join(conditions_not_met) if conditions_not_met else 'None'}]."
    )

    return {
        "strength": generate_actionable_strength(score),
        "reasoning": reasoning,
        "score": round(score, 2),
        "score_details": {"valuation": round(score, 2)},
        "key_metrics": data,
        "analysis_source": "rule_based_fallback"
    }


def _analyze_dividend(data: dict) -> dict:
    """Rule-based analysis for Dividend style."""
    dividend_yield = data.get("Dividend Yield", 0) or 0
    # Using Debt to Equity as a proxy for sustainability, since payout ratio is not available.
    # A D/E ratio below 100 (or 1.0) is generally considered healthy.
    de_ratio = data.get("Debt to Equity Ratio", float('inf')) or float('inf')

    score = 0.3
    conditions_met = []
    conditions_not_met = []

    if dividend_yield > 0.04:
        score += 0.35
        conditions_met.append("Dividend Yield > 4%")
    else:
        conditions_not_met.append("Dividend Yield <= 4%")

    # Payout Ratio is not available in yfinance 'info'. A common rule of thumb
    # is to check if debt is manageable, ensuring dividends are not funded by debt.
    if de_ratio < 100:
        score += 0.35
        conditions_met.append("Debt to Equity Ratio < 100")
    else:
        conditions_not_met.append("Debt to Equity Ratio >= 100")

    score = min(score, 1.0)
    reasoning = (
        "วิเคราะห์ตามกฎพื้นฐาน (Rule-based Fallback): "
        f"หุ้นปันผลจะพิจารณาจากเงื่อนไข: Dividend Yield > 4% และ Debt to Equity Ratio < 100 (เพื่อความยั่งยืน). "
        f"ผลลัพธ์: [Met: {', '.join(conditions_met) if conditions_met else 'None'}] "
        f"[Not Met: {', '.join(conditions_not_met) if conditions_not_met else 'None'}]."
    )

    return {
        "strength": generate_actionable_strength(score),
        "reasoning": reasoning,
        "score": round(score, 2),
        "score_details": {"yield_and_sustainability": round(score, 2)},
        "key_metrics": data,
        "analysis_source": "rule_based_fallback"
    }


def run_rule_based_analysis(ticker: str, data: dict, style: str) -> dict:
    """
    Runs the appropriate rule-based analysis based on the investment style.
    """
    if style == "growth":
        return _analyze_growth(data)
    if style == "value":
        return _analyze_value(data)
    if style == "dividend":
        return _analyze_dividend(data)
    else:
        # Default to 'value' analysis if style is unknown
        return _analyze_value(data)
