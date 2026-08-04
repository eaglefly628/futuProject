"""策略回测引擎 - 在历史 K 线上模拟策略执行"""
import json
from datetime import datetime
from loguru import logger

import pandas as pd
import numpy as np


class BacktestResult:
    """回测结果"""

    def __init__(self):
        self.trades = []        # [{date, code, direction, quantity, price, amount, fees, pnl}, ...]
        self.equity_curve = []  # [{date, equity}, ...]
        self.total_return = 0.0
        self.max_drawdown = 0.0
        self.sharpe_ratio = 0.0
        self.win_rate = 0.0
        self.profit_factor = 0.0
        self.total_trades = 0
        self.initial_cash = 0.0
        self.final_equity = 0.0

    def to_dict(self) -> dict:
        return {
            "total_return": round(self.total_return, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "win_rate": round(self.win_rate, 1),
            "profit_factor": round(self.profit_factor, 2),
            "total_trades": self.total_trades,
            "initial_cash": self.initial_cash,
            "final_equity": round(self.final_equity, 2),
            "trades": self.trades,
            "equity_curve": self.equity_curve,
        }


class Backtester:
    """策略回测器"""

    def __init__(self, db, fee_calculator, indicator_engine):
        self.db = db
        self.fee_calc = fee_calculator
        self.ind = indicator_engine

    def run(self, strategy: dict, codes: list, start_date: str, end_date: str,
            initial_cash: float = 1000000) -> BacktestResult:
        """
        执行回测

        Args:
            strategy: 策略定义 dict
            codes: 股票代码列表
            start_date: 起始日期 "YYYY-MM-DD"
            end_date: 结束日期 "YYYY-MM-DD"
            initial_cash: 初始资金

        Returns:
            BacktestResult
        """
        result = BacktestResult()
        result.initial_cash = initial_cash

        # 收集所有代码的日K线数据
        all_klines = {}
        for code in codes:
            df = self.db.get_kline(code, "K_DAY", start=start_date, end=end_date)
            if not df.empty:
                all_klines[code] = df
            else:
                logger.warning(f"回测: {code} 在 {start_date}~{end_date} 无K线数据")

        if not all_klines:
            logger.warning("回测: 没有可用的 K 线数据")
            result.final_equity = initial_cash
            return result

        # 构建按日期排序的交易日列表
        all_dates = set()
        for df in all_klines.values():
            if "time_key" in df.columns:
                # 取日期部分
                dates = df["time_key"].apply(lambda x: str(x)[:10])
                all_dates.update(dates.tolist())
        trading_days = sorted(all_dates)
        if not trading_days:
            result.final_equity = initial_cash
            return result

        # 模拟状态
        cash = initial_cash
        positions = {}  # {code: {quantity, avg_cost}}
        mode = strategy.get("mode", "visual")
        conditions = strategy.get("conditions", {})
        action = strategy.get("action", {})
        script = strategy.get("script", "")

        from strategy.engine import ConditionEvaluator, ScriptRunner
        evaluator = ConditionEvaluator(self.ind)
        script_runner = ScriptRunner()

        # 逐日模拟
        for day in trading_days:
            for code, full_df in all_klines.items():
                if "time_key" not in full_df.columns:
                    continue

                # 截取到当日的K线
                mask = full_df["time_key"].apply(lambda x: str(x)[:10]) <= day
                hist_df = full_df[mask].copy()
                if hist_df.empty:
                    continue

                current_row = hist_df.iloc[-1]
                current_price = float(current_row.get("close", 0))
                if current_price <= 0:
                    continue

                # 当日行情
                quote = {
                    "price": current_price,
                    "volume": float(current_row.get("volume", 0)),
                    "high": float(current_row.get("high", current_price)),
                    "low": float(current_row.get("low", current_price)),
                }

                signal = None
                trade_quantity = 0
                trade_price = current_price

                if mode == "script" and script.strip():
                    pos_val = sum(
                        p["quantity"] * current_price for p in positions.values()
                    )
                    account_summary = {
                        "cash": cash,
                        "total_asset": cash + pos_val,
                    }
                    context = {
                        "quote": quote,
                        "kline_df": hist_df,
                        "indicators": self.ind,
                        "account": account_summary,
                        "code": code,
                    }
                    res = script_runner.run(script, context)
                    sig = res.get("signal")
                    if sig in ("buy", "sell"):
                        signal = sig.upper()
                        trade_quantity = int(res.get("quantity", 0))
                        trade_price = res.get("price") or current_price
                else:
                    # 可视化条件模式
                    if conditions.get("items"):
                        triggered = evaluator.evaluate(conditions, quote, hist_df)
                        if triggered:
                            signal = action.get("direction", "BUY")
                            trade_quantity = int(action.get("quantity", 100))

                if not signal or trade_quantity <= 0:
                    continue

                # 执行交易
                fee_info = self.fee_calc.calculate(code, signal, trade_quantity, trade_price)
                total_fees = fee_info["total_cost"]
                amount = trade_quantity * trade_price
                realized_pnl = 0.0

                if signal == "BUY":
                    needed = amount + total_fees
                    if cash < needed:
                        continue
                    cash -= needed
                    pos = positions.get(code, {"quantity": 0, "avg_cost": 0})
                    old_qty = pos["quantity"]
                    old_avg = pos["avg_cost"]
                    new_qty = old_qty + trade_quantity
                    new_avg = (old_qty * old_avg + trade_quantity * trade_price) / new_qty if new_qty > 0 else 0
                    positions[code] = {"quantity": new_qty, "avg_cost": round(new_avg, 4)}
                elif signal == "SELL":
                    pos = positions.get(code)
                    if not pos or pos["quantity"] < trade_quantity:
                        continue
                    cash += amount - total_fees
                    realized_pnl = (trade_price - pos["avg_cost"]) * trade_quantity - total_fees
                    new_qty = pos["quantity"] - trade_quantity
                    if new_qty <= 0:
                        positions.pop(code, None)
                    else:
                        positions[code] = {"quantity": new_qty, "avg_cost": pos["avg_cost"]}

                result.trades.append({
                    "date": day,
                    "code": code,
                    "direction": signal,
                    "quantity": trade_quantity,
                    "price": round(trade_price, 2),
                    "amount": round(amount, 2),
                    "fees": round(total_fees, 2),
                    "pnl": round(realized_pnl, 2),
                })

            # 计算当日权益
            pos_value = 0
            for code, pos in positions.items():
                # 用最新已知的收盘价
                if code in all_klines:
                    code_df = all_klines[code]
                    day_mask = code_df["time_key"].apply(lambda x: str(x)[:10]) <= day
                    day_data = code_df[day_mask]
                    if not day_data.empty:
                        pos_value += pos["quantity"] * float(day_data.iloc[-1]["close"])
                    else:
                        pos_value += pos["quantity"] * pos["avg_cost"]
                else:
                    pos_value += pos["quantity"] * pos["avg_cost"]

            equity = cash + pos_value
            result.equity_curve.append({"date": day, "equity": round(equity, 2)})

        # 计算统计指标
        result.final_equity = result.equity_curve[-1]["equity"] if result.equity_curve else initial_cash
        result.total_return = ((result.final_equity - initial_cash) / initial_cash * 100)
        result.total_trades = len(result.trades)

        self._calc_stats(result, initial_cash)

        return result

    def _calc_stats(self, result: BacktestResult, initial_cash: float):
        """计算回测统计指标"""
        # ── 最大回撤 ──
        if result.equity_curve:
            equities = [e["equity"] for e in result.equity_curve]
            peak = equities[0]
            max_dd = 0.0
            for eq in equities:
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak * 100 if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
            result.max_drawdown = round(max_dd, 2)

        # ── 胜率 ──
        sell_trades = [t for t in result.trades if t["direction"] == "SELL"]
        if sell_trades:
            wins = sum(1 for t in sell_trades if t["pnl"] > 0)
            result.win_rate = round(wins / len(sell_trades) * 100, 1)
        else:
            result.win_rate = 0.0

        # ── 盈亏比 (Profit Factor) ──
        gross_profit = sum(t["pnl"] for t in result.trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in result.trades if t["pnl"] < 0))
        result.profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0

        # ── 夏普比率 (简化版，年化，假设无风险利率为 3%) ──
        if len(result.equity_curve) >= 2:
            equities = pd.Series([e["equity"] for e in result.equity_curve])
            daily_returns = equities.pct_change().dropna()
            if len(daily_returns) > 1 and daily_returns.std() > 0:
                avg_return = daily_returns.mean()
                std_return = daily_returns.std()
                # 年化: 252个交易日
                risk_free_daily = 0.03 / 252
                sharpe = (avg_return - risk_free_daily) / std_return * np.sqrt(252)
                result.sharpe_ratio = round(sharpe, 2)
            else:
                result.sharpe_ratio = 0.0
        else:
            result.sharpe_ratio = 0.0
