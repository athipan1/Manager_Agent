from __future__ import annotations

from typing import Any, Dict

from .shadow_trading_service import ShadowTradePlan


def shadow_plan_to_observation(plan: ShadowTradePlan) -> Dict[str, Any]:
    """Map a research-only plan to Database_Agent's append-only shadow contract."""

    return {
        "shadow_trade_id": plan.shadow_trade_id,
        "account_id": plan.account_id,
        "correlation_id": plan.correlation_id,
        "signal_id": plan.signal_id,
        "strategy_id": plan.strategy_id,
        "strategy_version": plan.strategy_version,
        "symbol": plan.symbol,
        "side": plan.side,
        "event_type": "signal_decision",
        "decision_price": plan.decision_price,
        "bid": plan.bid,
        "ask": plan.ask,
        "spread_bps": plan.spread_bps,
        "simulated_fill_price": plan.simulated_fill_price,
        "simulated_slippage_bps": plan.simulated_slippage_bps,
        "market_regime": plan.market_regime,
        "scanner_score": plan.scanner_score,
        "opportunity_score": plan.opportunity_score,
        "source_commit_sha": plan.source_commit_sha,
        "execution_mode": "shadow",
        "broker_order_authorized": False,
        "metadata": {
            **plan.metadata,
            "lane": "research",
            "risk_approval_allowed": False,
            "execution_agent_allowed": False,
            "manager_schema_version": plan.schema_version,
        },
    }
