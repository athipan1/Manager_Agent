
from .models import LearningRequest, LearningResponse, PolicyDeltas, Trade, PricePoint
from .db_agent_client import fetch_trade_history
from typing import List, Dict
from decimal import Decimal
import numpy as np
from collections import defaultdict
import logging

# --- Constants for Asset-Aware Learning ---
ASSET_MIN_TRADES_WARMUP = 10
MAX_DRAWDOWN_THRESHOLD = 0.08
CONSECUTIVE_LOSS_THRESHOLD = 3
RECENT_TRADES_WINDOW = 10
RISK_PER_TRADE_ADJUSTMENT = -0.005

# --- Constants for Hybrid Scoring ---
PERFORMANCE_UPPER_THRESHOLD = 0.70
PERFORMANCE_LOWER_THRESHOLD = 0.45
BIAS_ADJUSTMENT_INCREMENT = 0.05

WEIGHT_WIN_RATE = 0.50
WEIGHT_MAX_DRAWDOWN = 0.35
WEIGHT_VOLATILITY = 0.15
MAX_ACCEPTABLE_DRAWDOWN = 0.20
MAX_ACCEPTABLE_VOLATILITY = 0.10


def _calculate_asset_performance(trades: List[Trade], pnl_pcts: List[float]) -> Dict:
    """
    Calculates performance metrics for a single asset.
    """
    # Win Rate
    win_rate = len([p for p in pnl_pcts if p > 0]) / len(pnl_pcts) if pnl_pcts else 0

    # Max Drawdown
    if not pnl_pcts:
        max_drawdown = 0
    else:
        # Prepend an initial capital of 1.0 for accurate peak/drawdown calculation
        equity_curve = np.insert(np.cumprod([1 + p for p in pnl_pcts]), 0, 1.0)
        peak = np.maximum.accumulate(equity_curve)
        drawdown = (equity_curve - peak) / peak
        # Ignore the initial 0.0 drawdown from the prepended capital
        max_drawdown = abs(np.min(drawdown[1:])) if len(drawdown) > 1 else 0

    # Volatility of Returns
    volatility = np.std(pnl_pcts) if len(pnl_pcts) > 1 else 0

    return {
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
        "volatility": volatility,
        "trade_count": len(trades)
    }

async def run_learning_cycle(request: LearningRequest, bias_state: Dict[str, Dict[str, float]], correlation_id: str = "not-provided") -> LearningResponse:
    """
    Hybrid, asset-aware learning cycle. Fetches historical data, merges it with
    request data, analyzes performance, and recommends policy adjustments.
    """
    logging.info(f"[correlation_id={correlation_id}] learning cycle started")
    response = LearningResponse(learning_state="active", policy_deltas=PolicyDeltas())
    reasoning = []

    # --- Step 1: Pre-process execution_result from the request ---
    # This ensures the most recent trade data is up-to-date before merging.
    if request.execution_result and request.trade_history:
        if request.execution_result.get("status") == "executed":
            request.trade_history.sort(key=lambda t: t.executed_at, reverse=True)
            latest_trade = request.trade_history[0]
            if 'pnl_pct' in request.execution_result:
                latest_trade.pnl_pct = Decimal(str(request.execution_result['pnl_pct']))
            if 'entry_price' in request.execution_result:
                latest_trade.entry_price = Decimal(str(request.execution_result['entry_price']))
            if 'exit_price' in request.execution_result:
                latest_trade.exit_price = Decimal(str(request.execution_result['exit_price']))
            reasoning.append(f"Merged execution result for trade {latest_trade.trade_id}.")

    # --- Step 2: Fetch and merge trade histories ---
    # Identify unique assets from the request to fetch their histories
    asset_ids_in_request = {t.asset_id for t in request.trade_history}

    all_trades = {} # Use a dict to automatically handle de-duplication

    # Add trades from the request first
    for trade in request.trade_history:
        all_trades[trade.trade_id] = trade

    # Fetch historical trades for each asset and merge them
    for asset_id in asset_ids_in_request:
        historical_trades = await fetch_trade_history(
            account_id=request.account_id,
            asset_id=asset_id,
            correlation_id=correlation_id
        )
        for trade in historical_trades:
            if trade.trade_id not in all_trades:
                all_trades[trade.trade_id] = trade

    final_trade_list = list(all_trades.values())

    if not final_trade_list:
        response.learning_state = "insufficient_data"
        response.reasoning.append("No trades found in history (request + database).")
        logging.warning(f"[correlation_id={correlation_id}] learning cycle ended: no trades provided.")
        return response

    # --- Step 3: Group trades by asset for analysis ---
    trades_by_asset = defaultdict(list)
    for trade in final_trade_list:
        trades_by_asset[trade.asset_id].append(trade)

    global_risk_adjustment_needed = False
    assets_in_warmup = 0

    for asset_id, trades in trades_by_asset.items():
        if len(trades) < ASSET_MIN_TRADES_WARMUP:
            assets_in_warmup += 1
            reasoning.append(f"Asset '{asset_id}' is in warmup ({len(trades)}/{ASSET_MIN_TRADES_WARMUP} trades). No bias will be applied.")
            continue

        # --- P/L Calculation ---
        pnl_pcts = [float(t.pnl_pct) for t in trades]

        # --- Performance and Scoring ---
        perf = _calculate_asset_performance(trades, pnl_pcts)
        current_bias = bias_state.get(asset_id, {"bull_bias": 0.0, "bear_bias": 0.0, "vol_bias": 0.0})

        # Normalize metrics to scores (higher is better)
        wr_score = perf["win_rate"]
        mdd_score = 1.0 - min(1.0, perf["max_drawdown"] / MAX_ACCEPTABLE_DRAWDOWN)
        base_vol_score = 1.0 - min(1.0, perf["volatility"] / MAX_ACCEPTABLE_VOLATILITY)
        vol_score = max(0.0, min(1.0, base_vol_score + current_bias.get("vol_bias", 0.0)))

        base_performance_score = (WEIGHT_WIN_RATE * wr_score) + (WEIGHT_MAX_DRAWDOWN * mdd_score) + (WEIGHT_VOLATILITY * vol_score)

        directional_bias_adjustment = current_bias.get("bull_bias", 0.0) if base_performance_score > 0.5 else -current_bias.get("bear_bias", 0.0)
        performance_score = max(0.0, min(1.0, base_performance_score + directional_bias_adjustment))

        bias_delta = 0.0
        if performance_score > PERFORMANCE_UPPER_THRESHOLD:
            bias_delta = BIAS_ADJUSTMENT_INCREMENT
            reasoning.append(f"Asset '{asset_id}' performance score ({performance_score:.2f}) is above {PERFORMANCE_UPPER_THRESHOLD}. Applying positive bias.")
        elif performance_score < PERFORMANCE_LOWER_THRESHOLD:
            bias_delta = -BIAS_ADJUSTMENT_INCREMENT
            reasoning.append(f"Asset '{asset_id}' performance score ({performance_score:.2f}) is below {PERFORMANCE_LOWER_THRESHOLD}. Applying negative bias.")

        if bias_delta != 0.0:
            response.policy_deltas.asset_biases[asset_id] = bias_delta

        # --- Drawdown Clustering Detection ---
        sorted_trades_and_pnl = sorted(zip(trades, pnl_pcts), key=lambda x: x[0].executed_at, reverse=True)
        recent_pnl = [tp[1] for tp in sorted_trades_and_pnl[:RECENT_TRADES_WINDOW]]

        consecutive_losses = 0
        for pnl in recent_pnl:
            if pnl < 0:
                consecutive_losses += 1
                if consecutive_losses >= CONSECUTIVE_LOSS_THRESHOLD:
                    global_risk_adjustment_needed = True
                    reasoning.append(f"Asset '{asset_id}' has {consecutive_losses} consecutive losses. Flagging for risk review.")
                    break
            else:
                consecutive_losses = 0

        recent_trades = [tp[0] for tp in sorted_trades_and_pnl[:RECENT_TRADES_WINDOW]]
        recent_perf = _calculate_asset_performance(recent_trades, recent_pnl)
        if recent_perf["max_drawdown"] > MAX_DRAWDOWN_THRESHOLD:
            global_risk_adjustment_needed = True
            reasoning.append(f"Asset '{asset_id}' has a high recent drawdown of {recent_perf['max_drawdown']:.2%}. Flagging for risk review.")

    if global_risk_adjustment_needed:
        response.policy_deltas.risk["risk_per_trade"] = RISK_PER_TRADE_ADJUSTMENT
        reasoning.append(f"Applying a global risk reduction of {RISK_PER_TRADE_ADJUSTMENT} due to drawdown clustering.")

    if assets_in_warmup == len(trades_by_asset):
        response.learning_state = "warmup"
    else:
        response.learning_state = "success"

    response.reasoning = reasoning
    logging.info(f"[correlation_id={correlation_id}] policy updated")
    return response
