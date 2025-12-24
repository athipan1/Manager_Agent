from typing import Dict, Any, List
from .models import TradeHistory, PortfolioMetrics, OptimizerRequest, Trade

def evaluate_decision_quality(trades: List[Trade]) -> Dict[str, Any]:
    """
    Dynamically analyzes agent contributions to winning and losing trades.
    """
    agent_performance = {}

    for trade in trades:
        if trade.pnl_percent is None:
            continue

        is_win = trade.pnl_percent > 0

        # Dynamically find agent signals
        for key, value in trade.model_dump().items():
            if key.endswith("_signal") and value:
                agent_name = key.replace("_signal", "")
                if agent_name not in agent_performance:
                    agent_performance[agent_name] = {"wins": 0, "losses": 0, "win_rate": 0}

                if trade.final_action == value["action"]:
                    if is_win:
                        agent_performance[agent_name]["wins"] += 1
                    else:
                        agent_performance[agent_name]["losses"] += 1

    # Calculate win rates
    for agent, stats in agent_performance.items():
        total = stats["wins"] + stats["losses"]
        if total > 0:
            stats["win_rate"] = stats["wins"] / total

    return agent_performance


def detect_behavioral_bias(trades: List[Trade], metrics: PortfolioMetrics) -> Dict[str, Any]:
    """
    Detects behavioral biases such as overtrading or excessive risk-taking in volatile markets.
    """
    bias = {
        "overtrading_detected": False,
        "high_volatility_losses": False,
    }

    if len(trades) > 30 and metrics.win_rate < 0.5:
        bias["overtrading_detected"] = True

    volatile_losses = sum(1 for t in trades if t.market_condition == "volatile" and t.pnl_percent and t.pnl_percent < 0)
    if volatile_losses > len(trades) * 0.2:
        bias["high_volatility_losses"] = True

    return bias


def adjust_strategy_parameters(
    agent_performance: Dict[str, Any], bias: Dict[str, Any], config: OptimizerRequest
) -> Dict[str, Any]:
    """
    Generates conservative adjustments to agent weights and risk parameters based on performance and biases.
    """
    adjustments = {
        "technical": 0.0,
        "fundamental": 0.0,
        "sentiment": 0.0,
        "macro": 0.0,
    }

    # Adjust agent weights based on win rate
    for agent, stats in agent_performance.items():
        if agent in adjustments:
            if stats["win_rate"] > 0.6:
                adjustments[agent] = 0.05
            elif stats["win_rate"] < 0.4:
                adjustments[agent] = -0.05

    # Risk adjustments based on biases
    risk_adj = {
        "risk_per_trade": 0.0,
        "max_position_pct": 0.0,
        "stop_loss_pct": 0.0,
        "enable_technical_stop": config.risk_parameters.enable_technical_stop
    }
    if bias["overtrading_detected"]:
        risk_adj["risk_per_trade"] = -0.005  # Reduce risk slightly
    if bias["high_volatility_losses"]:
        risk_adj["stop_loss_pct"] = -0.01  # Tighten stop loss

    # Strategy bias
    strategy_bias = {
        "preferred_action": "hold",
        "market_condition_bias": "range"
    }
    if bias["high_volatility_losses"]:
        strategy_bias["market_condition_bias"] = "trend" # Avoid volatile markets

    # Guardrails
    guardrails = {
        "pause_trading_if": {
            "max_drawdown_pct": config.risk_parameters.max_position_pct * 1.5,
            "consecutive_losses": 5
        }
    }

    return {
        "agent_weight_adjustments": adjustments,
        "risk_adjustments": risk_adj,
        "strategy_bias": strategy_bias,
        "guardrails": guardrails,
    }


def run_analysis(
    trade_history: TradeHistory,
    portfolio_metrics: PortfolioMetrics,
    config: OptimizerRequest,
) -> Dict[str, Any]:
    """
    Main analysis function to generate optimization recommendations.
    """
    agent_performance = evaluate_decision_quality(trade_history.trades)
    behavioral_bias = detect_behavioral_bias(trade_history.trades, portfolio_metrics)

    adjustments = adjust_strategy_parameters(agent_performance, behavioral_bias, config)

    # Reasoning
    reasoning = []
    for agent, adj in adjustments["agent_weight_adjustments"].items():
        if adj > 0:
            reasoning.append(f"{agent.capitalize()} agent showing strong performance.")
        elif adj < 0:
            reasoning.append(f"{agent.capitalize()} agent underperforming, reducing weight.")

    if behavioral_bias["overtrading_detected"]:
        reasoning.append("Overtrading detected, reducing risk per trade.")
    if behavioral_bias["high_volatility_losses"]:
        reasoning.append("Losses concentrated in volatile markets, tightening stop-loss.")

    # Summary
    summary = {
        "overall_assessment": "stable",
        "key_issue": "No major issues detected.",
        "confidence_level": 0.7,
    }
    if behavioral_bias["overtrading_detected"] or behavioral_bias["high_volatility_losses"]:
        summary["overall_assessment"] = "degrading"
        summary["key_issue"] = "High losses in volatile markets and potential overtrading."

    recommendation = {
        "summary": summary,
        **adjustments,
        "reasoning": reasoning,
    }

    return recommendation
