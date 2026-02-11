import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.analyzer import (  # noqa: E402
    get_roe_score,
    get_de_ratio_score,
    get_revenue_trend_score,
    calculate_cagr,
    get_margins_score,
    get_pe_ratio_score,
    get_dividend_yield_score,
    get_pb_ratio_score,
    get_eps_score,
    get_growth_score,
    get_forward_pe_score,
    get_peg_ratio_score,
    get_cash_flow_score,
)


class TestAnalyzerHelpers(unittest.TestCase):

    def test_get_roe_score(self):
        self.assertEqual(get_roe_score(0.25), 0.25)
        self.assertEqual(get_roe_score(0.18), 0.15)
        self.assertEqual(get_roe_score(0.10), 0.05)
        self.assertEqual(get_roe_score(0.02), 0.0)

    def test_get_de_ratio_score(self):
        self.assertEqual(get_de_ratio_score(0.4), 0.20)
        self.assertEqual(get_de_ratio_score(0.8), 0.10)
        self.assertEqual(get_de_ratio_score(1.5), 0.05)
        self.assertEqual(get_de_ratio_score(2.5), 0.0)

    def test_get_revenue_trend_score(self):
        hist_rev_strong = {"2023": 100, "2022": 90, "2021": 80, "2020": 70}
        score, trend = get_revenue_trend_score(hist_rev_strong)
        self.assertEqual(score, 0.15)
        self.assertEqual(trend, "เติบโตต่อเนื่อง 3 ปี")

        hist_rev_weak = {"2023": 100, "2022": 90, "2021": 95, "2020": 80}
        score, trend = get_revenue_trend_score(hist_rev_weak)
        self.assertEqual(score, 0.10)

        hist_rev_flat = {"2023": 100, "2022": 100, "2021": 100, "2020": 100}
        score, trend = get_revenue_trend_score(hist_rev_flat)
        self.assertEqual(score, 0.0)
        self.assertEqual(trend, "รายได้ไม่เติบโต")

        hist_rev_insufficient = {"2023": 100, "2022": 90}
        score, trend = get_revenue_trend_score(hist_rev_insufficient)
        self.assertEqual(score, 0.0)
        self.assertEqual(trend, "ข้อมูลไม่เพียงพอ")

    def test_calculate_cagr(self):
        hist_rev = {"2023": 133.1, "2022": 121, "2021": 110, "2020": 100}
        self.assertAlmostEqual(calculate_cagr(hist_rev), 0.10, places=2)

        hist_rev_zero = {"2023": 100, "2022": 50, "2021": 20, "2020": 0}
        self.assertIsNone(calculate_cagr(hist_rev_zero))

        self.assertIsNone(calculate_cagr({}))

    def test_get_margins_score(self):
        self.assertEqual(get_margins_score(0.25), 0.10)
        self.assertEqual(get_margins_score(0.15), 0.0)

    def test_get_pe_ratio_score(self):
        self.assertEqual(get_pe_ratio_score(10), 0.10)
        self.assertEqual(get_pe_ratio_score(20), 0.05)
        self.assertEqual(get_pe_ratio_score(30), 0.0)
        self.assertEqual(get_pe_ratio_score(None), 0.0)

    def test_get_dividend_yield_score(self):
        self.assertEqual(get_dividend_yield_score(0.05), 0.10)
        self.assertEqual(get_dividend_yield_score(0.03), 0.05)
        self.assertEqual(get_dividend_yield_score(0.01), 0.0)
        self.assertEqual(get_dividend_yield_score(None), 0.0)

    def test_get_pb_ratio_score(self):
        self.assertEqual(get_pb_ratio_score(1.0), 0.05)
        self.assertEqual(get_pb_ratio_score(1.5), 0.0)
        self.assertEqual(get_pb_ratio_score(None), 0.0)

    def test_get_eps_score(self):
        self.assertEqual(get_eps_score(5), 0.05)
        self.assertEqual(get_eps_score(-1), 0.0)
        self.assertEqual(get_eps_score(None), 0.0)

    def test_get_growth_score(self):
        self.assertEqual(get_growth_score(0.30), 0.20)
        self.assertEqual(get_growth_score(0.15), 0.10)
        self.assertEqual(get_growth_score(0.05), 0.05)
        self.assertEqual(get_growth_score(-0.1), 0.0)
        self.assertEqual(get_growth_score(None), 0.0)

    def test_get_forward_pe_score(self):
        self.assertEqual(get_forward_pe_score(12), 0.10)
        self.assertEqual(get_forward_pe_score(22), 0.05)
        self.assertEqual(get_forward_pe_score(28), 0.0)
        self.assertEqual(get_forward_pe_score(None), 0.0)

    def test_get_peg_ratio_score(self):
        self.assertEqual(get_peg_ratio_score(0.8), 0.10)
        self.assertEqual(get_peg_ratio_score(1.2), 0.05)
        self.assertEqual(get_peg_ratio_score(1.8), 0.0)
        self.assertEqual(get_peg_ratio_score(None), 0.0)

    def test_get_cash_flow_score(self):
        self.assertEqual(get_cash_flow_score(1000000), 0.10)
        self.assertEqual(get_cash_flow_score(-50000), 0.0)
        self.assertEqual(get_cash_flow_score(None), 0.0)


if __name__ == '__main__':
    unittest.main()
