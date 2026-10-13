"""参考净值偏离不能与指数超额收益或跨日净值混淆。"""
import unittest

from analysis.etf_value import deviation, value_metrics
from downloaders.etf_value import parse_market, parse_fee_html


class ValueTests(unittest.TestCase):
    def test_premium_sign(self):
        self.assertAlmostEqual(deviation(.99, 1), -1)
        self.assertAlmostEqual(deviation(1.01, 1), 1)
        self.assertIsNone(deviation(1, 0))
        self.assertIsNone(deviation(float("nan"), 1))

    def test_discount_last_trade_does_not_mean_discount_ask(self):
        result = value_metrics({"price": 1.119, "iopv": 1.1193, "bid": 1.119, "ask": 1.121})
        self.assertLess(result["premium_pct"], 0)
        self.assertGreater(result["ask_premium_pct"], 0)
        self.assertAlmostEqual(result["spread_pct"], .17857142857)

    def test_official_nav_comparison_requires_same_date(self):
        row = {"price": 1.119, "nav": 1.1225, "nav_date": "2026-10-12", "market_date": "2026-10-13"}
        self.assertIsNone(value_metrics(row)["nav_premium_pct"])
        row["market_date"] = "2026-10-12"
        self.assertLess(value_metrics(row)["nav_premium_pct"], 0)

    def test_crossed_missing_and_invalid_book(self):
        self.assertIsNone(value_metrics({"ask": 1, "bid": 2})["spread_pct"])
        self.assertIsNone(value_metrics({"ask": 1, "bid": 2, "iopv": 2})["ask_premium_pct"])
        self.assertIsNone(value_metrics({"ask": 1})["spread_pct"])
        self.assertIsNone(value_metrics({"price": 1, "iopv": "-"})["premium_pct"])

    def test_market_mapping_does_not_invent_iopv_timestamp(self):
        row = parse_market({"f12": "560530", "f13": 1, "f2": 1.119, "f441": 1.1193,
                            "f31": 1.119, "f32": 1.121, "f297": 20261013, "f402": .03})
        self.assertEqual(row["code"], "SH.560530")
        self.assertIsNone(row["iopv_time"])
        self.assertEqual(row["market_date"], "2026-10-13")
        self.assertLess(row["premium_pct"], 0)
        self.assertEqual(row["provider_discount_pct"], .03)

    def test_fee_parser_keeps_missing_unknown(self):
        result = parse_fee_html("<table><tr><th>管理费率</th><td>0.15%（每年）</td></tr></table>")
        self.assertEqual(result["management_fee_pct"], .15)
        self.assertIsNone(result["custody_fee_pct"])


if __name__ == "__main__":
    unittest.main()
