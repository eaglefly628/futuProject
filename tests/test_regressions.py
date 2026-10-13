"""资金、挂单、配置和回测的离线回归测试。"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import yaml

from config import Config
from storage.database import Database
from strategy.backtester import Backtester, BacktestResult
from trading.fee_calculator import FeeCalculator
from trading.paper_engine import PaperEngine


class Settings:
    def get(self, *keys, default=None):
        data = {"paper_trading": {"initial_cash": 100000,
                                  "fx_rate": {"USD_CNY": 7, "HKD_CNY": 0.9}}}
        for key in keys:
            if not isinstance(data, dict) or key not in data:
                return default
            data = data[key]
        return data


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.fees = FeeCalculator(Settings())
        self.engine = PaperEngine(self.db, self.fees, Settings())

    def tearDown(self):
        self.db.close()

    def test_foreign_currency_cash_value_and_pnl(self):
        for code, rate in [("US.AAPL", 7), ("HK.00700", 0.9)]:
            before = self.engine.get_account_summary(1)["cash"]
            buy_fees = self.fees.calculate(code, "BUY", 10, 100)["total_cost"]
            self.engine.place_order(1, code, "BUY", 10, price=100)
            summary = self.engine.get_account_summary(1)
            self.assertAlmostEqual(summary["cash"], before - 1000 * rate - buy_fees, places=2)
            self.assertAlmostEqual(summary["positions_value"], 1000 * rate, places=2)
            self.engine.update_positions_price({code: {"price": 110}})
            self.assertAlmostEqual(self.engine.get_positions(1)[0]["unrealized_pnl"], 100 * rate)
            sell_fees = self.fees.calculate(code, "SELL", 10, 110)["total_cost"]
            self.engine.place_order(1, code, "SELL", 10, price=110)
            self.assertAlmostEqual(self.engine.get_account_summary(1)["cash"],
                                   before + 100 * rate - buy_fees - sell_fees, places=2)

    def test_multiple_pending_sells_cannot_oversell(self):
        self.engine.place_order(1, "SZ.159338", "BUY", 100, price=10)
        first = self.engine.place_order(1, "SZ.159338", "SELL", 100, "LIMIT", 11)
        second = self.engine.place_order(1, "SZ.159338", "SELL", 100, "LIMIT", 11)
        self.engine.try_fill_orders({"SZ.159338": {"price": 12}})
        self.assertEqual(self.engine._get_order(first)["status"], "FILLED")
        self.assertEqual(self.engine._get_order(second)["status"], "REJECTED")
        self.assertEqual(len(self.engine.get_trade_logs(1)), 2)
        self.assertEqual(self.engine.get_positions(1), [])

    def test_delayed_market_order_and_duplicate_fill(self):
        order_id = self.engine.place_order(1, "SZ.159338", "BUY", 100)
        pending = self.engine._get_order(order_id)
        self.engine.try_fill_orders({"SZ.159338": {"price": 10}})
        self.engine._execute_fill(pending, 10)
        self.assertEqual(len(self.engine.get_trade_logs(1)), 1)
        self.assertEqual(self.engine.get_positions(1)[0]["quantity"], 100)

    def test_invalid_orders(self):
        for args in [("BUY", -1, "MARKET", 10), ("INVALID", 1, "MARKET", 10),
                     ("BUY", 1, "LIMIT", None), ("BUY", 1, "MARKET", float("nan"))]:
            self.assertEqual(self.engine.place_order(1, "SZ.159338", *args), -1)
        self.assertEqual(self.engine.get_orders(1), [])


class ConfigTests(unittest.TestCase):
    def test_local_overrides_never_written_to_public_config(self):
        previous = Config._instance
        Config._instance = None
        try:
            with tempfile.TemporaryDirectory() as temp:
                directory = Path(temp) / "config"
                directory.mkdir()
                default = directory / "default.yaml"
                default.write_text("opend:\n  host: localhost\n  password: ''\nkline:\n  count: 100\n", encoding="utf-8")
                local = directory / "local.yaml"
                local.write_text("opend:\n  password: example-secret\n  user: example-user\n", encoding="utf-8")
                config = Config(str(default))
                config.set("kline", "count", 200)
                config.set("opend", "password", "changed-secret")
                config.save_local({"opend": {"token": "new-secret"}})
                config.save()
                config.save()
                public = yaml.safe_load(default.read_text(encoding="utf-8"))
                private = yaml.safe_load(local.read_text(encoding="utf-8"))
                self.assertEqual(public["kline"]["count"], 200)
                self.assertEqual(public["opend"], {"host": "localhost", "password": ""})
                self.assertEqual(private["opend"]["password"], "changed-secret")
                self.assertEqual(private["opend"]["token"], "new-secret")
        finally:
            Config._instance = previous


def bars(dates, prices):
    return pd.DataFrame({"time_key": dates, "close": prices})


class BacktestTests(unittest.TestCase):
    def run_backtest(self, data, runner):
        db = SimpleNamespace(get_kline=lambda code, *args, **kwargs: data[code])
        tester = Backtester(db, FeeCalculator(Settings()), None)
        with patch("strategy.engine.ScriptRunner.run", side_effect=runner):
            result = tester.run({"mode": "script", "script": "test"}, list(data),
                                "2026-01-01", "2026-01-31", 100000)
        return result

    def test_no_trades_on_missing_bar(self):
        data = {"SZ.159338": bars(["2026-01-01", "2026-01-03"], [10, 10]),
                "SH.512050": bars(["2026-01-02"], [20])}
        result = self.run_backtest(data, lambda *args: {"signal": "buy", "quantity": 100})
        self.assertEqual([(t["code"], t["date"]) for t in result.trades],
                         [("SZ.159338", "2026-01-01"), ("SH.512050", "2026-01-02"),
                          ("SZ.159338", "2026-01-03")])

    def test_script_account_uses_each_positions_price_and_currency(self):
        observed = []
        data = {"US.AAPL": bars(["2026-01-01", "2026-01-02"], [100, 110]),
                "SZ.159338": bars(["2026-01-01", "2026-01-02"], [10, 12])}

        def runner(script, context):
            observed.append((context["code"], context["account"]["total_asset"]))
            return {"signal": "buy", "quantity": 10}

        result = self.run_backtest(data, runner)
        fees = FeeCalculator(Settings())
        first_fee = fees.calculate("US.AAPL", "BUY", 10, 100)["total_cost"]
        second_fee = fees.calculate("SZ.159338", "BUY", 10, 10)["total_cost"]
        self.assertAlmostEqual(observed[1][1], 100000 - first_fee)
        self.assertAlmostEqual(observed[2][1], 100000 - first_fee - second_fee + 720)
        self.assertEqual(result.trades[0]["amount"], 7000)

    def test_drawdown_includes_initial_capital(self):
        result = BacktestResult()
        result.equity_curve = [{"date": "2026-01-01", "equity": 90}]
        Backtester(None, None, None)._calc_stats(result, 100)
        self.assertEqual(result.max_drawdown, 10)


if __name__ == "__main__":
    unittest.main()
