from typing import List
import pandas as pd
import pandas_ta as ta

from .models import PricePoint, MarketRegimeResponse


def _determine_regime_from_indicators(
    latest_price: float,
    latest_ema_200: float,
    latest_adx: float,
    adx_5_periods_ago: float,
    ema_slope: float,
    ema_slope_3_periods_ago: float,
    atr_ratio: float,
    close_mean: float
) -> MarketRegimeResponse:
    """Calculates regime based on pre-computed indicator values."""
    scores = { "uptrend": 0.0, "downtrend": 0.0, "ranging": 0.0, "volatile": 0.0 }

    # Uptrend Scoring
    if latest_adx > 25: scores["uptrend"] += 0.4
    if ema_slope > 0: scores["uptrend"] += 0.4
    if latest_price > latest_ema_200: scores["uptrend"] += 0.2

    # Downtrend Scoring
    if latest_adx > 25: scores["downtrend"] += 0.4
    if ema_slope < 0: scores["downtrend"] += 0.4
    if latest_price < latest_ema_200: scores["downtrend"] += 0.2

    # Ranging Scoring
    slope_threshold = close_mean * 0.0005
    price_proximity_pct = abs(latest_price - latest_ema_200) / latest_ema_200 if latest_ema_200 != 0 else 0

    if latest_adx < 20: scores["ranging"] += 0.5
    if abs(ema_slope) < slope_threshold: scores["ranging"] += 0.3
    if price_proximity_pct < 0.01: scores["ranging"] += 0.2

    # Volatile / Transition Scoring
    if atr_ratio >= 1.5: scores["volatile"] += 0.7

    adx_accelerating = latest_adx > (adx_5_periods_ago + 5) # ADX increased by 5 in 5 periods
    ema_flipped = (ema_slope > 0 and ema_slope_3_periods_ago < 0) or \
                  (ema_slope < 0 and ema_slope_3_periods_ago > 0)

    if adx_accelerating or ema_flipped:
        scores["volatile"] += 0.3

    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    if scores["volatile"] >= 0.7:
        final_regime = "volatile"
        confidence_score = scores["volatile"]
        explanation_parts = [
            f"Scores: Uptrend={scores['uptrend']:.2f}, Downtrend={scores['downtrend']:.2f}, Ranging={scores['ranging']:.2f}, Volatile={scores['volatile']:.2f}.",
            "Volatility override was triggered (ATR spike >= 1.5x mean).",
            f"Final regime is 'volatile' with confidence {confidence_score:.2f}."
        ]
        explanation = " ".join(explanation_parts)
    else:
        winner, runner_up = sorted_scores[0], sorted_scores[1]
        winning_regime, winning_score = winner
        runner_up_regime, runner_up_score = runner_up
        confidence_score = max(0.0, min(1.0, winning_score - runner_up_score))

        is_ambiguous = winning_score < 0.6 or confidence_score < 0.15
        final_regime = "undefined" if is_ambiguous else winning_regime

        explanation_parts = [
            f"Scores: Uptrend={scores['uptrend']:.2f}, Downtrend={scores['downtrend']:.2f}, Ranging={scores['ranging']:.2f}, Volatile={scores['volatile']:.2f}.",
            f"Winning regime before ambiguity check: {winning_regime} (Score: {winning_score:.2f}).",
            f"Runner-up: {runner_up_regime} (Score: {runner_up_score:.2f}).",
            f"Confidence calculation: max(0, min(1, {winning_score:.2f} - {runner_up_score:.2f})) = {confidence_score:.2f}."
        ]
        if is_ambiguous:
            reason = "winning score was < 0.6" if winning_score < 0.6 else "confidence was < 0.15"
            explanation_parts.append(f"Final regime is 'undefined' because {reason}.")
        else:
            explanation_parts.append(f"Final regime is '{final_regime}'.")
        explanation = " ".join(explanation_parts)

    return MarketRegimeResponse(
        regime=final_regime,
        confidence_score=min(1.0, confidence_score), # Ensure confidence doesn't exceed 1.0
        explanation=explanation
    )


def classify_market_regime(price_history: List[PricePoint]) -> MarketRegimeResponse:
    if len(price_history) < 200:
        return MarketRegimeResponse(regime="undefined", confidence_score=0.0, explanation="Insufficient data.")

    df = pd.DataFrame([p.model_dump() for p in price_history])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)

    ema_200 = ta.ema(df['close'], length=200)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    atr = ta.atr(df['high'], df['low'], df['close'], length=14)

    if ema_200 is None or adx is None or atr is None or ema_200.dropna().empty or adx.dropna().empty or atr.dropna().empty:
        return MarketRegimeResponse(regime="undefined", confidence_score=0.0, explanation="Failed to calculate indicators.")

    # Ensure we have enough data points for historical lookups
    if len(adx.dropna()) < 6 or len(ema_200.dropna()) < 6:
        return MarketRegimeResponse(regime="undefined", confidence_score=0.0, explanation="Not enough data for historical indicator analysis.")

    latest_price = df['close'].iloc[-1]
    latest_ema_200 = ema_200.iloc[-1]
    latest_adx = adx.iloc[-1]['ADX_14']
    adx_5_periods_ago = adx.iloc[-6]['ADX_14']
    latest_atr = atr.iloc[-1]

    ema_slope = ema_200.iloc[-1] - ema_200.iloc[-3]
    ema_slope_3_periods_ago = ema_200.iloc[-4] - ema_200.iloc[-6]

    atr_mean_20 = atr.rolling(window=20).mean().iloc[-1]
    atr_ratio = latest_atr / atr_mean_20 if atr_mean_20 > 0 else 1.0

    return _determine_regime_from_indicators(
        latest_price=latest_price,
        latest_ema_200=latest_ema_200,
        latest_adx=latest_adx,
        adx_5_periods_ago=adx_5_periods_ago,
        ema_slope=ema_slope,
        ema_slope_3_periods_ago=ema_slope_3_periods_ago,
        atr_ratio=atr_ratio,
        close_mean=df['close'].mean()
    )
