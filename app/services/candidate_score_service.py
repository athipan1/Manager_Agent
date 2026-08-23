from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional

CANDIDATE_SCORE_VERSION = "candidate-score.v1"
CANDIDATE_SCORE_MAX_POINTS = 10
CANDIDATE_MIN_SCORE = 8
MIN_REWARD_RISK = 2.0
MIN_ANALYSIS_COVERAGE = 0.80


def _mapping(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _finite(value: Any) -> Optional[float]:
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_ratio(value: Any) -> Optional[float]:
    number = _finite(value)
    if number is None:
        return None
    if abs(number) > 10.0:
        number /= 100.0
    return number


def _agent_data(analysis_result: Mapping[str, Any], agent: str) -> Dict[str, Any]:
    raw_data = _mapping(analysis_result.get("raw_data"))
    envelope = _mapping(raw_data.get(agent))
    return _mapping(envelope.get("data"))


def _scanner_bundle(scanner_candidate: Any) -> Dict[str, Any]:
    candidate = _mapping(scanner_candidate)
    metadata = _mapping(candidate.get("metadata"))
    details = _mapping(metadata.get("details"))
    bundle = _mapping(details.get("data_bundle"))
    if bundle:
        return bundle
    bundle = _mapping(metadata.get("data_bundle"))
    if bundle:
        return bundle
    details = _mapping(candidate.get("details"))
    return _mapping(details.get("data_bundle"))


def _criterion(
    *,
    available: bool,
    passed: bool,
    observed: Any,
    threshold: str,
    source: str,
) -> Dict[str, Any]:
    return {
        "available": bool(available),
        "passed": bool(available and passed),
        "point": 1 if available and passed else 0,
        "observed": observed,
        "threshold": threshold,
        "source": source,
    }


def _fundamental_criteria(fund_data: Dict[str, Any]) -> tuple[Dict[str, Any], str, float]:
    evidence = _mapping(fund_data.get("fundamental_evidence"))
    evidence_status = str(
        evidence.get("evidence_status")
        or fund_data.get("evidence_status")
        or "unavailable"
    ).lower()
    provenance = _mapping(evidence.get("provenance"))
    published_scorecard = _mapping(provenance.get("candidate_scorecard"))
    published_criteria = _mapping(published_scorecard.get("criteria"))
    if published_criteria:
        criteria = {
            name: _mapping(row)
            for name, row in published_criteria.items()
            if name in {
                "revenue_growth",
                "eps_growth",
                "free_cash_flow",
                "debt_quality",
                "capital_efficiency",
            }
        }
        if len(criteria) == 5:
            coverage = sum(
                bool(_mapping(row).get("available")) for row in criteria.values()
            ) / 5.0
            return criteria, evidence_status, round(coverage, 4)

    metrics = _mapping(evidence.get("metrics"))
    raw_scores = _mapping(evidence.get("raw_scores"))
    sector = str(metrics.get("sector") or fund_data.get("sector") or "").lower()
    revenue_growth = _normalize_ratio(
        metrics.get("revenue_growth")
        if metrics.get("revenue_growth") is not None
        else metrics.get("revenue_3y_cagr")
    )
    eps_growth = _normalize_ratio(
        metrics.get("eps_growth")
        if metrics.get("eps_growth") is not None
        else metrics.get("eps_3y_cagr")
    )
    free_cash_flow = _finite(metrics.get("free_cash_flow"))
    debt_to_equity = _normalize_ratio(metrics.get("debt_to_equity"))
    roic = _normalize_ratio(metrics.get("roic"))
    roe = _normalize_ratio(metrics.get("roe"))
    financial_health = _normalize_ratio(raw_scores.get("financial_health_score"))

    if sector in {"real estate", "utilities"}:
        debt_limit: Optional[float] = 2.5
    elif sector == "financial services":
        debt_limit = None
    else:
        debt_limit = 1.0

    if debt_limit is None:
        debt_value = financial_health
        debt_available = debt_value is not None
        debt_passed = debt_value is not None and debt_value >= 0.60
        debt_threshold = "financial_health_score >= 0.60 (financial sector)"
        debt_source = "fundamental_evidence.raw_scores.financial_health_score"
    else:
        debt_value = debt_to_equity
        debt_available = debt_value is not None
        debt_passed = debt_value is not None and 0 <= debt_value <= debt_limit
        debt_threshold = f"0 <= debt_to_equity <= {debt_limit}"
        debt_source = "fundamental_evidence.metrics.debt_to_equity"

    efficiency = roic if roic is not None else roe
    efficiency_available = efficiency is not None
    efficiency_passed = (
        (roic is not None and roic >= 0.10)
        or (roic is None and roe is not None and roe >= 0.15)
    )

    criteria = {
        "revenue_growth": _criterion(
            available=revenue_growth is not None,
            passed=revenue_growth is not None and revenue_growth >= 0.10,
            observed=revenue_growth,
            threshold="revenue growth >= 10%",
            source="fundamental_evidence.metrics",
        ),
        "eps_growth": _criterion(
            available=eps_growth is not None,
            passed=eps_growth is not None and eps_growth >= 0.10,
            observed=eps_growth,
            threshold="EPS growth >= 10%",
            source="fundamental_evidence.metrics",
        ),
        "free_cash_flow": _criterion(
            available=free_cash_flow is not None,
            passed=free_cash_flow is not None and free_cash_flow > 0,
            observed=free_cash_flow,
            threshold="free_cash_flow > 0",
            source="fundamental_evidence.metrics.free_cash_flow",
        ),
        "debt_quality": _criterion(
            available=debt_available,
            passed=debt_passed,
            observed=debt_value,
            threshold=debt_threshold,
            source=debt_source,
        ),
        "capital_efficiency": _criterion(
            available=efficiency_available,
            passed=efficiency_passed,
            observed=efficiency,
            threshold="ROIC >= 10%; fallback ROE >= 15%",
            source=(
                "fundamental_evidence.metrics.roic"
                if roic is not None
                else "fundamental_evidence.metrics.roe"
            ),
        ),
    }
    coverage = sum(row["available"] for row in criteria.values()) / 5.0
    return criteria, evidence_status, round(coverage, 4)


def _scanner_score_inputs(bundle: Dict[str, Any]) -> Dict[str, Any]:
    published = _mapping(bundle.get("candidate_score_inputs"))
    if published:
        return published

    technical = _mapping(bundle.get("technical"))
    indicators = _mapping(technical.get("indicator_values"))
    market_rank = _mapping(bundle.get("market_rank"))
    profile = _mapping(bundle.get("opportunity_profile"))
    context = _mapping(profile.get("execution_context"))

    close = _finite(indicators.get("close"))
    sma50 = _finite(indicators.get("sma50"))
    sma200 = _finite(indicators.get("sma200"))
    market_rank_score = _finite(
        market_rank.get("market_rank_score")
        if market_rank.get("market_rank_score") is not None
        else market_rank.get("score")
    )
    return_20d = _normalize_ratio(market_rank.get("return_20d"))
    return_60d = _normalize_ratio(market_rank.get("return_60d"))
    volume_ratio = _finite(
        context.get("relative_volume")
        if context.get("relative_volume") is not None
        else market_rank.get("volume_ratio")
    )

    return {
        "technical": {
            "close": close,
            "sma50": sma50,
            "sma200": sma200,
            "relative_volume": volume_ratio,
            "price_above_sma200": (
                close > sma200 if close is not None and sma200 is not None else None
            ),
            "sma50_above_sma200": (
                sma50 > sma200 if sma50 is not None and sma200 is not None else None
            ),
        },
        "market_strength": {
            "market_rank_score": market_rank_score,
            "return_20d": return_20d,
            "return_60d": return_60d,
            "stronger_than_universe_proxy": (
                market_rank_score >= 0.65 and return_20d > 0 and return_60d > 0
                if market_rank_score is not None
                and return_20d is not None
                and return_60d is not None
                else None
            ),
            "method": "scanner_market_rank_universe_proxy",
        },
        "opportunity": {
            "status": profile.get("status"),
            "workflow_status": profile.get("workflow_status"),
            "opportunity_score": _finite(profile.get("opportunity_score")),
            "fail_closed": bool(profile.get("fail_closed")),
            "execution_context": context,
        },
    }


def _technical_criteria(
    tech_data: Dict[str, Any],
    scanner_inputs: Dict[str, Any],
) -> tuple[Dict[str, Any], str, float]:
    evidence = _mapping(tech_data.get("technical_evidence"))
    evidence_status = str(
        evidence.get("evidence_status")
        or tech_data.get("evidence_status")
        or "unavailable"
    ).lower()
    scanner_technical = _mapping(scanner_inputs.get("technical"))
    market_strength = _mapping(scanner_inputs.get("market_strength"))

    price_above = scanner_technical.get("price_above_sma200")
    sma50_above = scanner_technical.get("sma50_above_sma200")
    relative_strength = market_strength.get("stronger_than_universe_proxy")
    volume_ratio = _finite(scanner_technical.get("relative_volume"))

    if price_above is None:
        provenance = _mapping(evidence.get("provenance"))
        scorecard = _mapping(provenance.get("candidate_scorecard"))
        row = _mapping(_mapping(scorecard.get("criteria")).get("price_above_sma200"))
        if row.get("available"):
            price_above = bool(row.get("passed"))

    if volume_ratio is None:
        metrics = _mapping(evidence.get("metrics"))
        volume_ratio = _finite(metrics.get("volume_ratio"))

    criteria = {
        "price_above_sma200": _criterion(
            available=price_above is not None,
            passed=price_above is True,
            observed=price_above,
            threshold="price > SMA200",
            source="scanner|technical evidence",
        ),
        "sma50_above_sma200": _criterion(
            available=sma50_above is not None,
            passed=sma50_above is True,
            observed=sma50_above,
            threshold="SMA50 > SMA200",
            source="scanner candidate_score_inputs",
        ),
        "relative_strength": _criterion(
            available=relative_strength is not None,
            passed=relative_strength is True,
            observed=relative_strength,
            threshold="Scanner market-rank strength proxy is positive",
            source=str(
                market_strength.get("method")
                or "scanner_market_rank_universe_proxy"
            ),
        ),
        "volume_confirmation": _criterion(
            available=volume_ratio is not None,
            passed=volume_ratio is not None and volume_ratio >= 1.10,
            observed=volume_ratio,
            threshold="relative volume >= 1.10",
            source="scanner|technical liquidity evidence",
        ),
    }
    coverage = sum(row["available"] for row in criteria.values()) / 4.0
    return criteria, evidence_status, round(coverage, 4)


def _reward_risk(tech_data: Dict[str, Any]) -> Dict[str, Any]:
    evidence = _mapping(tech_data.get("technical_evidence"))
    metrics = _mapping(evidence.get("metrics"))
    indicators = _mapping(tech_data.get("indicators"))

    entry = _finite(
        tech_data.get("current_price")
        if tech_data.get("current_price") is not None
        else metrics.get("current_price")
    )
    stop = _finite(
        indicators.get("stop_loss")
        if indicators.get("stop_loss") is not None
        else metrics.get("stop_loss")
    )
    target = _finite(metrics.get("resistance_level"))

    ratio: Optional[float] = None
    if (
        entry is not None
        and stop is not None
        and target is not None
        and target > entry > stop
    ):
        risk = entry - stop
        reward = target - entry
        if risk > 0:
            ratio = reward / risk

    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "reward_risk": round(ratio, 4) if ratio is not None else None,
        "point": 1 if ratio is not None and ratio >= MIN_REWARD_RISK else 0,
        "available": ratio is not None,
        "passed": ratio is not None and ratio >= MIN_REWARD_RISK,
        "threshold": f"reward/risk >= {MIN_REWARD_RISK}",
        "source": "technical_evidence",
    }


def build_candidate_score_v1(
    analysis_result: Mapping[str, Any],
    scanner_candidate: Any,
) -> Dict[str, Any]:
    """Build explainable 10-point candidate evidence without changing trade authority."""

    analysis = _mapping(analysis_result)
    fund_data = _agent_data(analysis, "fundamental")
    tech_data = _agent_data(analysis, "technical")
    bundle = _scanner_bundle(scanner_candidate)
    scanner_inputs = _scanner_score_inputs(bundle)

    fundamental, fund_status, fund_coverage = _fundamental_criteria(fund_data)
    technical, tech_status, tech_coverage = _technical_criteria(
        tech_data,
        scanner_inputs,
    )
    opportunity = _reward_risk(tech_data)

    fundamental_points = sum(int(row["point"]) for row in fundamental.values())
    technical_points = sum(int(row["point"]) for row in technical.values())
    opportunity_points = int(opportunity["point"])
    total_points = fundamental_points + technical_points + opportunity_points

    quality = _mapping(bundle.get("data_quality"))
    analysis_quality = _mapping(quality.get("analysis"))
    analysis_coverage = _finite(analysis_quality.get("coverage_ratio"))
    profile = _mapping(bundle.get("opportunity_profile"))
    opportunity_status = str(profile.get("status") or "").lower()
    fail_closed = bool(profile.get("fail_closed"))

    hard_gates = {
        "score_at_least_8": total_points >= CANDIDATE_MIN_SCORE,
        "fundamental_evidence_usable": (
            fund_status not in {"insufficient", "unavailable", ""}
            and fund_coverage == 1.0
        ),
        "technical_evidence_usable": (
            tech_status not in {"insufficient", "unavailable", ""}
            and tech_coverage == 1.0
        ),
        "scanner_analysis_coverage": (
            analysis_coverage is not None
            and analysis_coverage >= MIN_ANALYSIS_COVERAGE
        ),
        "scanner_opportunity_qualified": (
            opportunity_status == "qualified" and not fail_closed
        ),
        "reward_risk_at_least_2": bool(opportunity["passed"]),
    }
    hard_gates_passed = all(hard_gates.values())

    if total_points >= CANDIDATE_MIN_SCORE:
        decision = "CANDIDATE" if hard_gates_passed else "REVIEW"
    elif total_points >= 6:
        decision = "WATCHLIST"
    else:
        decision = "REJECT"

    return {
        "score_version": CANDIDATE_SCORE_VERSION,
        "score": total_points,
        "max_score": CANDIDATE_SCORE_MAX_POINTS,
        "fundamental_points": fundamental_points,
        "technical_points": technical_points,
        "opportunity_points": opportunity_points,
        "criteria": {
            "fundamental": fundamental,
            "technical": technical,
            "opportunity": opportunity,
        },
        "evidence_coverage": {
            "fundamental": fund_coverage,
            "technical": tech_coverage,
            "scanner_analysis": analysis_coverage,
        },
        "evidence_status": {
            "fundamental": fund_status,
            "technical": tech_status,
            "scanner_opportunity": opportunity_status or "unavailable",
        },
        "hard_gates": hard_gates,
        "hard_gates_passed": hard_gates_passed,
        "decision": decision,
        "activation_mode": "shadow_observation",
        "production_binding": False,
        "manager_decision_required": True,
        "risk_approval_required": True,
        "execution_authority": False,
        "thresholds": {
            "candidate_min_score": CANDIDATE_MIN_SCORE,
            "min_reward_risk": MIN_REWARD_RISK,
            "min_scanner_analysis_coverage": MIN_ANALYSIS_COVERAGE,
        },
    }
