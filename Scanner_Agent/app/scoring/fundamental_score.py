from typing import Dict, Any, Optional
from app.config import settings

def calculate_quality_score(metrics: Dict[str, Optional[float]]) -> Optional[float]:
    """Calculates the quality score based on a set of quality metrics."""
    score = 0
    max_score = 0

    # ROE > 15% is good
    if metrics.get("roe") is not None:
        max_score += 1
        if metrics["roe"] > 15:
            score += 1

    # ROA > 10% is good
    if metrics.get("roa") is not None:
        max_score += 1
        if metrics["roa"] > 10:
            score += 1

    # Debt-to-Equity < 0.5 is good
    if metrics.get("debt_to_equity") is not None:
        max_score += 1
        if metrics["debt_to_equity"] < 0.5:
            score += 1

    # Positive Free Cash Flow
    if metrics.get("free_cash_flow") is not None:
        max_score += 1
        if metrics["free_cash_flow"] > 0:
            score += 1

    # Profit Margin > 10%
    if metrics.get("profit_margins") is not None:
        max_score += 1
        if metrics["profit_margins"] > 10:
            score += 1

    if max_score == 0:
        return None

    return (score / max_score) * 100

def calculate_growth_score(metrics: Dict[str, Optional[float]]) -> Optional[float]:
    """Calculates the growth score based on growth metrics."""
    score = 0
    max_score = 0

    # Revenue CAGR > 10%
    if metrics.get("revenue_cagr") is not None:
        max_score += 1
        if metrics["revenue_cagr"] > 10:
            score += 1

    # EPS Growth > 10%
    if metrics.get("eps_growth") is not None:
        max_score += 1
        if metrics["eps_growth"] > 10:
            score += 1

    if max_score == 0:
        return None

    return (score / max_score) * 100

def calculate_valuation_score(metrics: Dict[str, Optional[float]]) -> Optional[float]:
    """Calculates the valuation score based on valuation metrics."""
    score = 0
    max_score = 0

    # P/E ratio < 20 is good
    if metrics.get("pe_ratio") is not None:
        max_score += 1
        if metrics["pe_ratio"] < 20:
            score += 1

    # PEG ratio < 1 is good
    if metrics.get("peg_ratio") is not None:
        max_score += 1
        if metrics["peg_ratio"] < 1:
            score += 1

    # P/B ratio < 3 is good
    if metrics.get("pb_ratio") is not None:
        max_score += 1
        if metrics["pb_ratio"] < 3:
            score += 1

    if max_score == 0:
        return None

    return (score / max_score) * 100

def calculate_fundamental_score(scores: Dict[str, Optional[float]]) -> Optional[float]:
    """Calculates the final fundamental score from the individual scores."""
    total_score = 0
    total_weight = 0

    if scores.get("quality_score") is not None:
        total_score += scores["quality_score"] * settings.QUALITY_SCORE_WEIGHT
        total_weight += settings.QUALITY_SCORE_WEIGHT

    if scores.get("growth_score") is not None:
        total_score += scores["growth_score"] * settings.GROWTH_SCORE_WEIGHT
        total_weight += settings.GROWTH_SCORE_WEIGHT

    if scores.get("valuation_score") is not None:
        total_score += scores["valuation_score"] * settings.VALUATION_SCORE_WEIGHT
        total_weight += settings.VALUATION_SCORE_WEIGHT

    if total_weight == 0:
        return None

    return total_score / total_weight

def get_grade(score: float) -> str:
    """Assigns a grade based on the fundamental score."""
    if score >= 80:
        return "A"
    elif score >= 65:
        return "B"
    else:
        return "C"
