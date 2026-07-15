"""Pre-backtest market investability gate.

This gate answers a different question from Walk-forward validation:

* Investability: can this security be traded safely enough to justify testing?
* Walk-forward: did the strategy remain stable out of sample?

Missing values are never imputed. Required missing evidence is quarantined and
hard threshold failures are blocked before Backtest, Risk, and Execution.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


INVESTABILITY_POLICY_VERSION = "manager-investability-v1"


_ACTION_BY_CODE = {
    "investability_price_missing": "refresh_current_market_price",
    "investability_price_below_minimum": "exclude_penny_stock_or_raise_policy_exception",
    "investability_market_cap_missing": "refresh_company_market_cap",
    "investability_market_cap_below_minimum": "exclude_microcap_or_raise_policy_exception",
    "investability_atr_missing": "refresh_daily_volatility_evidence",
    "investability_atr_above_maximum": "wait_for_volatility_to_normalize",
    "investability_extreme_volatility": "wait_for_volatility_to_normalize",
    "investability_average_dollar_volume_missing": "refresh_liquidity_evidence",
    "investability_average_dollar_volume_below_minimum": "exclude_illiquid_security",
    "investability_spread_missing": "refresh_bid_ask_evidence",
    "investability_spread_above_maximum": "exclude_wide_spread_security",
}


def _symbol(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("symbol") or value.get("ticker") or "").strip().upper()
    return str(
        getattr(value, "symbol", None)
        or getattr(value, "ticker", None)
        or ""
    ).strip().upper()


def _finite_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _walk_mappings(value: Any, *, max_depth: int = 8) -> Iterable[Mapping[str, Any]]:
    """Yield nested mappings in deterministic breadth-first order."""

    queue: List[tuple[Any, int]] = [(value, 0)]
    seen: set[int] = set()
    while queue:
        current, depth = queue.pop(0)
        if depth > max_depth:
            continue
        if isinstance(current, Mapping):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            yield current
            for nested in current.values():
                if isinstance(nested, (Mapping, list, tuple)):
                    queue.append((nested, depth + 1))
        elif isinstance(current, (list, tuple)):
            for nested in current:
                if isinstance(nested, (Mapping, list, tuple)):
                    queue.append((nested, depth + 1))


def _first_value(rows: Sequence[Any], names: Sequence[str]) -> Any:
    lowered = tuple(name.lower() for name in names)
    for row in rows:
        for mapping in _walk_mappings(row):
            for name in names:
                if name in mapping and mapping.get(name) not in (None, ""):
                    return mapping.get(name)
            normalized = {str(key).lower(): key for key in mapping}
            for name in lowered:
                key = normalized.get(name)
                if key is not None and mapping.get(key) not in (None, ""):
                    return mapping.get(key)
    return None


def _first_number(rows: Sequence[Any], names: Sequence[str]) -> Optional[float]:
    return _finite_float(_first_value(rows, names))


def _volatility_regime(rows: Sequence[Any]) -> Optional[str]:
    value = _first_value(rows, ("volatility_regime", "volatilityRegime"))
    text = str(value or "").strip().lower()
    return text or None


def _average_dollar_volume(rows: Sequence[Any], price: Optional[float]) -> Optional[float]:
    direct = _first_number(
        rows,
        (
            "average_dollar_volume",
            "avg_dollar_volume",
            "averageDollarVolume",
            "dollar_volume_30d",
        ),
    )
    if direct is not None:
        return direct
    average_volume = _first_number(
        rows,
        (
            "average_daily_volume",
            "average_volume",
            "avg_volume",
            "averageVolume",
            "averageVolume10days",
        ),
    )
    if average_volume is None or price is None:
        return None
    return average_volume * price


def _spread_bps(rows: Sequence[Any]) -> Optional[float]:
    direct = _first_number(rows, ("spread_bps", "bid_ask_spread_bps"))
    if direct is not None:
        return direct
    bid = _first_number(rows, ("bid", "bid_price", "bidPrice"))
    ask = _first_number(rows, ("ask", "ask_price", "askPrice"))
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    midpoint = (bid + ask) / 2.0
    return ((ask - bid) / midpoint) * 10_000.0 if midpoint > 0 else None


def evaluate_investability(
    candidate: Mapping[str, Any],
    *,
    analysis_payload: Optional[Mapping[str, Any]] = None,
    enabled: bool = True,
    min_price_usd: float = 3.0,
    min_market_cap_usd: float = 300_000_000.0,
    min_average_dollar_volume_usd: float = 5_000_000.0,
    max_spread_bps: float = 100.0,
    max_atr_pct: float = 15.0,
    require_average_dollar_volume: bool = False,
    require_spread: bool = False,
    require_atr: bool = True,
    block_extreme_volatility: bool = True,
) -> Dict[str, Any]:
    """Classify one candidate as PASS, QUARANTINE, BLOCK, or DISABLED."""

    symbol = _symbol(candidate) or _symbol(analysis_payload or {})
    rows: List[Any] = [candidate]
    if analysis_payload is not None:
        rows.append(analysis_payload)

    price = _first_number(
        rows,
        ("current_price", "current_market_price", "market_price", "last_price"),
    )
    market_cap = _first_number(rows, ("market_cap", "marketCap"))
    atr_pct = _first_number(rows, ("atr_percent", "atr_pct", "atrPercent"))
    regime = _volatility_regime(rows)
    average_dollar_volume = _average_dollar_volume(rows, price)
    spread_bps = _spread_bps(rows)

    metrics = {
        "current_price": price,
        "market_cap": market_cap,
        "average_dollar_volume": average_dollar_volume,
        "spread_bps": spread_bps,
        "atr_percent": atr_pct,
        "volatility_regime": regime,
    }
    thresholds = {
        "min_price_usd": float(min_price_usd),
        "min_market_cap_usd": float(min_market_cap_usd),
        "min_average_dollar_volume_usd": float(min_average_dollar_volume_usd),
        "max_spread_bps": float(max_spread_bps),
        "max_atr_pct": float(max_atr_pct),
        "require_average_dollar_volume": bool(require_average_dollar_volume),
        "require_spread": bool(require_spread),
        "require_atr": bool(require_atr),
        "block_extreme_volatility": bool(block_extreme_volatility),
    }

    if not enabled:
        return {
            "symbol": symbol,
            "allowed": True,
            "status": "disabled",
            "policy_version": INVESTABILITY_POLICY_VERSION,
            "rejection_codes": [],
            "warning_codes": [],
            "required_actions": [],
            "metrics": metrics,
            "thresholds": thresholds,
        }

    block_codes: List[str] = []
    quarantine_codes: List[str] = []
    warning_codes: List[str] = []

    if price is None:
        quarantine_codes.append("investability_price_missing")
    elif price < float(min_price_usd):
        block_codes.append("investability_price_below_minimum")

    if market_cap is None:
        quarantine_codes.append("investability_market_cap_missing")
    elif market_cap < float(min_market_cap_usd):
        block_codes.append("investability_market_cap_below_minimum")

    if atr_pct is None:
        target = quarantine_codes if require_atr else warning_codes
        target.append("investability_atr_missing")
    elif atr_pct > float(max_atr_pct):
        block_codes.append("investability_atr_above_maximum")

    if block_extreme_volatility and regime == "extreme":
        block_codes.append("investability_extreme_volatility")

    if average_dollar_volume is None:
        target = quarantine_codes if require_average_dollar_volume else warning_codes
        target.append("investability_average_dollar_volume_missing")
    elif average_dollar_volume < float(min_average_dollar_volume_usd):
        block_codes.append("investability_average_dollar_volume_below_minimum")

    if spread_bps is None:
        target = quarantine_codes if require_spread else warning_codes
        target.append("investability_spread_missing")
    elif spread_bps > float(max_spread_bps):
        block_codes.append("investability_spread_above_maximum")

    block_codes = list(dict.fromkeys(block_codes))
    quarantine_codes = list(dict.fromkeys(quarantine_codes))
    warning_codes = list(dict.fromkeys(warning_codes))
    if block_codes:
        status = "block"
        rejection_codes = block_codes + quarantine_codes
    elif quarantine_codes:
        status = "quarantine"
        rejection_codes = quarantine_codes
    else:
        status = "pass"
        rejection_codes = []

    required_actions = list(
        dict.fromkeys(
            _ACTION_BY_CODE[code]
            for code in rejection_codes
            if code in _ACTION_BY_CODE
        )
    )
    return {
        "symbol": symbol,
        "allowed": status == "pass",
        "status": status,
        "policy_version": INVESTABILITY_POLICY_VERSION,
        "rejection_codes": rejection_codes,
        "warning_codes": warning_codes,
        "required_actions": required_actions,
        "metrics": metrics,
        "thresholds": thresholds,
    }


def filter_candidates_with_investability_gate(
    *,
    selected_positions: List[Dict[str, Any]],
    position_analysis_payloads: List[Dict[str, Any]],
    enabled: bool,
    min_price_usd: float,
    min_market_cap_usd: float,
    min_average_dollar_volume_usd: float,
    max_spread_bps: float,
    max_atr_pct: float,
    require_average_dollar_volume: bool,
    require_spread: bool,
    require_atr: bool,
    block_extreme_volatility: bool,
) -> Dict[str, Any]:
    """Filter aligned positions/payloads and retain one audit decision per symbol."""

    payload_by_symbol = {
        _symbol(payload): payload
        for payload in position_analysis_payloads or []
        if _symbol(payload)
    }
    decisions: List[Dict[str, Any]] = []
    allowed_positions: List[Dict[str, Any]] = []
    allowed_payloads: List[Dict[str, Any]] = []

    for position in selected_positions or []:
        symbol = _symbol(position)
        payload = payload_by_symbol.get(symbol)
        decision = evaluate_investability(
            position,
            analysis_payload=payload,
            enabled=enabled,
            min_price_usd=min_price_usd,
            min_market_cap_usd=min_market_cap_usd,
            min_average_dollar_volume_usd=min_average_dollar_volume_usd,
            max_spread_bps=max_spread_bps,
            max_atr_pct=max_atr_pct,
            require_average_dollar_volume=require_average_dollar_volume,
            require_spread=require_spread,
            require_atr=require_atr,
            block_extreme_volatility=block_extreme_volatility,
        )
        decisions.append(decision)
        if not decision["allowed"]:
            continue
        next_position = dict(position)
        next_position["investability_gate"] = decision
        allowed_positions.append(next_position)
        if payload is not None:
            next_payload = dict(payload)
            next_payload["investability_gate"] = decision
            allowed_payloads.append(next_payload)

    rejected = [decision for decision in decisions if not decision["allowed"]]
    return {
        "status": "enabled" if enabled else "disabled",
        "enabled": bool(enabled),
        "policy_version": INVESTABILITY_POLICY_VERSION,
        "selected_positions": allowed_positions,
        "position_analysis_payloads": allowed_payloads,
        "decisions": decisions,
        "rejected": rejected,
        "summary": {
            "candidate_count": len(decisions),
            "allowed_count": len(decisions) - len(rejected),
            "rejected_count": len(rejected),
            "blocked_count": sum(row.get("status") == "block" for row in decisions),
            "quarantined_count": sum(
                row.get("status") == "quarantine" for row in decisions
            ),
            "warning_count": sum(bool(row.get("warning_codes")) for row in decisions),
        },
    }
