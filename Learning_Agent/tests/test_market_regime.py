
import unittest
from learning_agent.market_regime import _determine_regime_from_indicators, classify_market_regime
from learning_agent.models import PricePoint
import pandas as pd
from typing import List

def generate_price_history(num_points: int) -> List[PricePoint]:
    prices = []
    for i in range(num_points):
        prices.append(
            PricePoint(
                timestamp=(pd.to_datetime('2023-01-01') + pd.Timedelta(days=i)).isoformat(),
                open=100 + i * 0.1, high=100 + i * 0.1 + 1, low=100 + i * 0.1 - 1,
                close=100 + i * 0.1, volume=1000
            )
        )
    return prices

class TestMarketRegimeLogic(unittest.TestCase):
    defaults = {
        "latest_price": 100, "latest_ema_200": 100, "latest_adx": 20,
        "adx_5_periods_ago": 20, "ema_slope": 0.1, "ema_slope_3_periods_ago": 0.1,
        "atr_ratio": 1.0, "close_mean": 100
    }

    def test_strong_uptrend(self):
        result = _determine_regime_from_indicators(
            **{**self.defaults, "latest_price": 110, "latest_adx": 30, "ema_slope": 1.5}
        )
        self.assertEqual(result.regime, "uptrend")
        self.assertAlmostEqual(result.confidence_score, 0.6)
        self.assertIn("Final regime is 'uptrend'", result.explanation)

    def test_strong_downtrend(self):
        result = _determine_regime_from_indicators(
            **{**self.defaults, "latest_price": 90, "latest_adx": 30, "ema_slope": -1.5}
        )
        self.assertEqual(result.regime, "downtrend")
        self.assertAlmostEqual(result.confidence_score, 0.6)
        self.assertIn("Final regime is 'downtrend'", result.explanation)

    def test_ranging_market(self):
        result = _determine_regime_from_indicators(
            **{**self.defaults, "latest_price": 100.1, "latest_adx": 15, "ema_slope": 0.01}
        )
        self.assertEqual(result.regime, "ranging")
        self.assertAlmostEqual(result.confidence_score, 0.4)
        self.assertIn("Final regime is 'ranging'", result.explanation)

    def test_volatile_override_atr_spike(self):
        result = _determine_regime_from_indicators(
            **{**self.defaults, "atr_ratio": 2.0, "latest_adx": 30}
        )
        self.assertEqual(result.regime, "volatile")
        self.assertAlmostEqual(result.confidence_score, 1.0)
        self.assertIn("Volatility override was triggered", result.explanation)

    def test_volatile_adx_acceleration(self):
        result = _determine_regime_from_indicators(
            **{**self.defaults, "latest_adx": 25, "adx_5_periods_ago": 19}
        )
        self.assertEqual(result.regime, "undefined")
        self.assertIn("Volatile=0.30", result.explanation)

    def test_defined_at_winning_score_threshold(self):
        result = _determine_regime_from_indicators(
            **{**self.defaults, "latest_price": 101, "latest_adx": 22, "ema_slope": 0.1}
        )
        self.assertEqual(result.regime, "uptrend")
        self.assertIn("Final regime is 'uptrend'", result.explanation)

    def test_undefined_low_confidence(self):
        result = _determine_regime_from_indicators(
           **{**self.defaults, "latest_price": 100.2, "latest_adx": 22, "ema_slope": 0.01}
        )
        self.assertEqual(result.regime, "undefined")
        self.assertIn("confidence was < 0.15", result.explanation)

class TestMarketRegimeIntegration(unittest.TestCase):
    def test_insufficient_data(self):
        price_history = generate_price_history(199)
        result = classify_market_regime(price_history)
        self.assertEqual(result.regime, "undefined")
        self.assertIn("Insufficient data", result.explanation)

    def test_full_run_sanity_check(self):
        try:
            price_history = generate_price_history(250)
            classify_market_regime(price_history)
        except Exception as e:
            self.fail(f"classify_market_regime failed on a simple case: {e}")

if __name__ == '__main__':
    unittest.main()
