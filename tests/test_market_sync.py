"""市场名单、指数路由与对照窗口的回归验证。"""
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from threading import Event

import pandas as pd

from analysis.market_comparison import (compare_returns, normalized_curves,
                                        rank_comparisons, product_category)
from core.market_sync import MarketSync, market_open
from PySide6.QtCore import QObject, QCoreApplication, QEventLoop, QTimer
from core.market_universe import filter_a500, load_universe, is_plain_a500
from downloaders.akshare_source import AkshareSource


def frame(dates, prices):
    return pd.DataFrame({"time_key": dates, "close": prices})


class MarketTests(unittest.TestCase):
    def test_signed_and_absolute_rank_keep_missing_last(self):
        rows = [("a", "a", {"excess": -10}), ("b", "b", {"excess": 2}),
                ("c", "c", None)]
        self.assertEqual([r[0] for r in rank_comparisons(rows)], ["b", "a", "c"])
        self.assertEqual([r[0] for r in rank_comparisons(rows, "abs")], ["a", "b", "c"])
        self.assertEqual([r[0] for r in rank_comparisons(rows, "asc")], ["a", "b", "c"])

    def test_product_groups(self):
        self.assertEqual(product_category("SH.000510", "中证A500"), "指数")
        self.assertEqual(product_category("SH.560530", "中证A500ETF摩根"), "普通A500")
        self.assertEqual(product_category("SH.563550", "A500增强ETF摩根"), "增强")
        self.assertEqual(product_category("SH.563510", "A500红利低波ETF易方达"), "红利低波")

    def test_catalog_excludes_other_strategies_and_deduplicates(self):
        rows = [{"f12": "560530", "f13": 1, "f14": "中证A500ETF摩根"},
                {"f12": "159226", "f13": 0, "f14": "中证A500增强ETF国泰"},
                {"f12": "510300", "f13": 1, "f14": "沪深300ETF"}]
        self.assertEqual(filter_a500(rows + rows),
                         [("SH.560530", "中证A500ETF摩根")])

    def test_old_cache_cannot_reintroduce_other_funds(self):
        payload = '{"etfs": [["SH.560530", "中证A500ETF摩根"], ["SH.563510", "A500红利低波ETF易方达"]]}'
        with patch("pathlib.Path.read_text", return_value=payload):
            self.assertEqual(load_universe("unused.json"), [("SH.560530", "中证A500ETF摩根")])
        for name in ("沪深300ETF", "A500增强ETF", "A500红利ETF", "A500低波ETF", "A500ETF联接"):
            self.assertFalse(is_plain_a500(name))

    def test_index_exchange_is_retained(self):
        source = AkshareSource.__new__(AkshareSource)
        source._em = MagicMock()
        source._em.get_kline.return_value = frame(["2026-10-13"], [3800])
        result = source._fetch("000001", "K_DAY", "2026-10-01", "2026-10-13", "SH.000001")
        source._em.get_kline.assert_called_once_with("SH.000001", "K_DAY", "2026-10-01", "2026-10-13")
        self.assertEqual(result.iloc[0]["close"], 3800)

    def test_index_failure_does_not_fetch_stock(self):
        source = AkshareSource.__new__(AkshareSource)
        source._em = MagicMock()
        source._em.get_kline.return_value = None
        source._yahoo = MagicMock()
        with self.assertRaises(RuntimeError):
            source._fetch("000001", "K_DAY", "2026-10-01", "2026-10-13", "SH.000001")
        source._yahoo.get_kline.assert_not_called()

    def test_aligned_excess_returns(self):
        dates = ["2026-10-09", "2026-10-12", "2026-10-13"]
        result = compare_returns(frame(dates, [100, 103, 110]), frame(dates, [100, 101, 105]), 2)
        self.assertAlmostEqual(result["return"], 10)
        self.assertAlmostEqual(result["excess"], 5)
        self.assertEqual(result["end"], "2026-10-13")

    def test_stale_missing_and_short_history_are_not_zero(self):
        dates = ["2026-10-09", "2026-10-12", "2026-10-13"]
        benchmark = frame(dates, [100, 101, 105])
        self.assertIsNone(compare_returns(frame(dates[:2], [100, 110]), benchmark, 1))
        self.assertIsNone(compare_returns(frame(dates[::2], [100, 110]), benchmark, 2))
        self.assertIsNone(compare_returns(frame(dates, [100, 103, 110]), benchmark, 20))

    def test_normalized_chart_has_common_dates(self):
        result = normalized_curves({"ETF": frame(["2026-10-09", "2026-10-12"], [1, 1.1]),
                                    "指数": frame(["2026-10-09", "2026-10-12", "2026-10-13"], [100, 105, 110])})
        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0].tolist(), [100, 100])
        self.assertAlmostEqual(result.iloc[1]["ETF"], 110)

    def test_market_hours_and_weekend(self):
        self.assertTrue(market_open(datetime(2026, 10, 13, 10, 0)))
        self.assertTrue(market_open(datetime(2026, 10, 13, 15, 5)))
        self.assertFalse(market_open(datetime(2026, 10, 13, 12, 0)))
        self.assertFalse(market_open(datetime(2026, 10, 13, 20, 0)))
        self.assertFalse(market_open(datetime(2026, 10, 17, 10, 0)))

    def test_background_jobs_do_not_overlap_and_shutdown_finishes(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        window = QObject()
        window.db = SimpleNamespace(db_path="test_market.db")
        window.config = SimpleNamespace(get=lambda *args, default=None: default)
        sync = MarketSync(window)
        gate = Event()
        called = []
        loop = QEventLoop()

        def fetch():
            called.append("first")
            gate.wait(2)
            return 1

        sync._job("test", fetch, lambda result: None)
        sync._job("test", lambda: called.append("duplicate"), lambda result: None)
        worker = sync.jobs["test"]
        worker.finished.connect(loop.quit)
        QTimer.singleShot(20, lambda: (sync.stop(), gate.set()))
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        app.processEvents()
        self.assertTrue(sync.is_idle())
        self.assertTrue(sync.stopping)
        self.assertEqual(called, ["first"])


if __name__ == "__main__":
    unittest.main()
