
from typing import List, Dict
from .models import Trade, PricePoint

def analyze_agent_accuracy(trade_history: List[Trade]) -> Dict[str, float]:
    """
    Analyzes the accuracy of each agent using a risk-aware formula.

    An agent's decision is "correct" if:
    - It voted with the final verdict on a profitable trade.
    - It voted against the final verdict on a losing trade.
    """
    agent_correct_counts = {}
    agent_total_votes = {}

    for trade in trade_history:
        is_profitable = trade.pnl_pct > 0
        for agent_name, vote in trade.agent_votes.items():
            if agent_name not in agent_total_votes:
                agent_total_votes[agent_name] = 0
                agent_correct_counts[agent_name] = 0

            if vote.action != "hold":
                agent_total_votes[agent_name] += 1
                vote_matched_verdict = (vote.action == trade.final_verdict)

                if (is_profitable and vote_matched_verdict) or \
                   (not is_profitable and not vote_matched_verdict):
                    agent_correct_counts[agent_name] += 1

    agent_accuracies = {}
    for agent_name, total_votes in agent_total_votes.items():
        if total_votes > 0:
            accuracy = agent_correct_counts[agent_name] / total_votes
            agent_accuracies[agent_name] = accuracy

    return agent_accuracies

def calculate_performance_metrics(trade_history: List[Trade]) -> Dict:
    """
    Calculates overall system performance metrics.
    """
    if not trade_history:
        return {
            "win_rate": 0.0,
            "average_pnl_pct": 0.0,
            "max_drawdown": 0.0,
            "equity_curve": []
        }

    win_count = 0
    total_pnl_pct = 0
    equity = 100000
    peak_equity = equity
    max_drawdown = 0
    equity_curve = [equity]

    for trade in trade_history:
        if trade.pnl_pct > 0:
            win_count += 1
        total_pnl_pct += trade.pnl_pct
        equity *= (1 + trade.pnl_pct)
        equity_curve.append(equity)

        if equity > peak_equity:
            peak_equity = equity

        drawdown = (peak_equity - equity) / peak_equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    return {
        "win_rate": win_count / len(trade_history),
        "average_pnl_pct": total_pnl_pct / len(trade_history),
        "max_drawdown": max_drawdown,
        "equity_curve": equity_curve
    }
