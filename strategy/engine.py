"""策略引擎 - 条件评估与执行"""
import json
from datetime import datetime
from loguru import logger


class ConditionEvaluator:
    """评估策略条件"""

    def __init__(self, indicator_engine):
        self.ind = indicator_engine

    def evaluate(self, conditions: dict, quote: dict, kline_df) -> bool:
        """
        评估条件组

        Args:
            conditions: {"logic": "AND"/"OR", "items": [condition_dict, ...]}
                每个 condition_dict: {"type": "price_above", "params": {"value": 100}}
            quote: 当前行情 {price, volume, ...}
            kline_df: K线 DataFrame (需有 open, high, low, close, volume 列)

        Returns:
            是否满足条件
        """
        logic = conditions.get("logic", "AND")
        items = conditions.get("items", [])
        if not items:
            return False

        results = [self._eval_single(item, quote, kline_df) for item in items]

        if logic == "AND":
            return all(results)
        return any(results)

    def _eval_single(self, cond: dict, quote: dict, df) -> bool:
        """评估单个条件"""
        ctype = cond.get("type", "")
        params = cond.get("params", {})
        price = quote.get("price", 0) or 0

        if df is None or df.empty:
            return False

        try:
            return self._dispatch_condition(ctype, params, price, quote, df)
        except Exception as e:
            logger.warning(f"条件评估异常: {ctype} -> {e}")
            return False

    def _dispatch_condition(self, ctype, params, price, quote, df):
        """分发条件类型并评估"""
        # ── 价格条件 ──
        if ctype == "price_above":
            return price > params.get("value", 0)

        if ctype == "price_below":
            return price < params.get("value", 0)

        if ctype == "price_cross_ma":
            period = params.get("period", 20)
            ma = self.ind.ma(df, period=period)
            if len(ma) < 2:
                return False
            ma_prev = ma.iloc[-2]
            ma_curr = ma.iloc[-1]
            close_prev = df["close"].iloc[-2]
            close_curr = df["close"].iloc[-1]
            direction = params.get("direction", "up")
            if direction == "up":
                return close_prev <= ma_prev and close_curr > ma_curr
            else:
                return close_prev >= ma_prev and close_curr < ma_curr

        # ── MACD 条件 ──
        if ctype == "macd_golden_cross":
            dif, dea, _ = self.ind.macd(df)
            if len(dif) < 2:
                return False
            return dif.iloc[-2] <= dea.iloc[-2] and dif.iloc[-1] > dea.iloc[-1]

        if ctype == "macd_dead_cross":
            dif, dea, _ = self.ind.macd(df)
            if len(dif) < 2:
                return False
            return dif.iloc[-2] >= dea.iloc[-2] and dif.iloc[-1] < dea.iloc[-1]

        # ── RSI 条件 ──
        if ctype == "rsi_above":
            period = params.get("period", 14)
            rsi = self.ind.rsi(df, period=period)
            if rsi.empty:
                return False
            return rsi.iloc[-1] > params.get("value", 70)

        if ctype == "rsi_below":
            period = params.get("period", 14)
            rsi = self.ind.rsi(df, period=period)
            if rsi.empty:
                return False
            return rsi.iloc[-1] < params.get("value", 30)

        # ── KDJ 条件 ──
        if ctype == "kdj_golden_cross":
            k, d, _ = self.ind.kdj(df)
            if len(k) < 2:
                return False
            return k.iloc[-2] <= d.iloc[-2] and k.iloc[-1] > d.iloc[-1]

        if ctype == "kdj_dead_cross":
            k, d, _ = self.ind.kdj(df)
            if len(k) < 2:
                return False
            return k.iloc[-2] >= d.iloc[-2] and k.iloc[-1] < d.iloc[-1]

        # ── 布林带条件 ──
        if ctype == "boll_break_upper":
            upper, mid, lower = self.ind.boll(df)
            if len(upper) < 2:
                return False
            return df["close"].iloc[-2] <= upper.iloc[-2] and df["close"].iloc[-1] > upper.iloc[-1]

        if ctype == "boll_break_lower":
            upper, mid, lower = self.ind.boll(df)
            if len(lower) < 2:
                return False
            return df["close"].iloc[-2] >= lower.iloc[-2] and df["close"].iloc[-1] < lower.iloc[-1]

        # ── 量比条件 ──
        if ctype == "volume_ratio_above":
            vr = self.ind.volume_ratio(df)
            if vr.empty:
                return False
            return vr.iloc[-1] > params.get("value", 2.0)

        # ── 时间条件 ──
        if ctype == "time_in_range":
            now = datetime.now()
            start_str = params.get("start", "09:30")
            end_str = params.get("end", "15:00")
            try:
                start_time = datetime.strptime(start_str, "%H:%M").time()
                end_time = datetime.strptime(end_str, "%H:%M").time()
                return start_time <= now.time() <= end_time
            except ValueError:
                return False

        logger.warning(f"未知条件类型: {ctype}")
        return False


class ScriptRunner:
    """受限 Python 脚本执行器"""

    def run(self, script: str, context: dict) -> dict:
        """
        在受限环境中执行用户脚本

        context 提供: quote, kline_df, indicators (IndicatorEngine), account
        脚本应设置: signal ('buy'/'sell'/None), quantity, price
        """
        result = {"signal": None, "quantity": 0, "price": None}

        safe_builtins = {
            "abs": abs,
            "max": max,
            "min": min,
            "round": round,
            "len": len,
            "range": range,
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "sorted": sorted,
            "enumerate": enumerate,
            "zip": zip,
            "map": map,
            "filter": filter,
            "sum": sum,
            "any": any,
            "all": all,
            "isinstance": isinstance,
            "print": lambda *a, **kw: None,  # 静默 print
            "True": True,
            "False": False,
            "None": None,
        }

        safe_globals = {"__builtins__": safe_builtins}
        safe_globals.update(context)
        safe_globals["result"] = result

        try:
            exec(script, safe_globals)
        except Exception as e:
            logger.warning(f"策略脚本执行错误: {e}")
            result["error"] = str(e)

        return result


class StrategyEngine:
    """策略引擎：加载、评估、执行策略"""

    def __init__(self, db, paper_engine, indicator_engine, config):
        self.db = db
        self.paper = paper_engine
        self.ind = indicator_engine
        self.config = config
        self.evaluator = ConditionEvaluator(indicator_engine)
        self.script_runner = ScriptRunner()
        self._kline_cache = {}  # {code: DataFrame}
        self._ensure_tables()

    def _ensure_tables(self):
        """确保策略相关数据表存在"""
        cur = self.db.conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS strategy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mode TEXT DEFAULT 'visual',
            target_codes TEXT DEFAULT '[]',
            conditions TEXT DEFAULT '{}',
            action TEXT DEFAULT '{}',
            script TEXT DEFAULT '',
            enabled INTEGER DEFAULT 0,
            account_id INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS strategy_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id INTEGER NOT NULL,
            level TEXT DEFAULT 'INFO',
            message TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """)
        self.db.conn.commit()

    # ─────────────────────── 策略 CRUD ───────────────────────

    def load_strategies(self) -> list:
        """加载所有策略"""
        cur = self.db.conn.cursor()
        cur.execute("SELECT * FROM strategy ORDER BY id")
        columns = [desc[0] for desc in cur.description]
        strategies = []
        for row in cur.fetchall():
            s = dict(zip(columns, row))
            # 解析 JSON 字段
            try:
                s["target_codes"] = json.loads(s.get("target_codes", "[]") or "[]")
            except (json.JSONDecodeError, TypeError):
                s["target_codes"] = []
            try:
                s["conditions"] = json.loads(s.get("conditions", "{}") or "{}")
            except (json.JSONDecodeError, TypeError):
                s["conditions"] = {}
            try:
                s["action"] = json.loads(s.get("action", "{}") or "{}")
            except (json.JSONDecodeError, TypeError):
                s["action"] = {}
            s["enabled"] = bool(s.get("enabled", 0))
            strategies.append(s)
        return strategies

    def save_strategy(self, strategy: dict) -> int:
        """保存策略（新建或更新）"""
        cur = self.db.conn.cursor()
        target_codes = json.dumps(strategy.get("target_codes", []), ensure_ascii=False)
        conditions = json.dumps(strategy.get("conditions", {}), ensure_ascii=False)
        action = json.dumps(strategy.get("action", {}), ensure_ascii=False)

        if strategy.get("id"):
            cur.execute(
                """UPDATE strategy
                   SET name=?, mode=?, target_codes=?, conditions=?, action=?,
                       script=?, enabled=?, account_id=?, updated_at=datetime('now')
                   WHERE id=?""",
                (
                    strategy.get("name", "未命名"),
                    strategy.get("mode", "visual"),
                    target_codes,
                    conditions,
                    action,
                    strategy.get("script", ""),
                    1 if strategy.get("enabled") else 0,
                    strategy.get("account_id", 1),
                    strategy["id"],
                ),
            )
            self.db.conn.commit()
            return strategy["id"]
        else:
            cur.execute(
                """INSERT INTO strategy
                   (name, mode, target_codes, conditions, action, script, enabled, account_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    strategy.get("name", "未命名"),
                    strategy.get("mode", "visual"),
                    target_codes,
                    conditions,
                    action,
                    strategy.get("script", ""),
                    1 if strategy.get("enabled") else 0,
                    strategy.get("account_id", 1),
                ),
            )
            self.db.conn.commit()
            return cur.lastrowid

    def delete_strategy(self, strategy_id: int):
        """删除策略"""
        cur = self.db.conn.cursor()
        cur.execute("DELETE FROM strategy WHERE id=?", (strategy_id,))
        cur.execute("DELETE FROM strategy_log WHERE strategy_id=?", (strategy_id,))
        self.db.conn.commit()
        logger.info(f"已删除策略 #{strategy_id}")

    def toggle_strategy(self, strategy_id: int, enabled: bool):
        """启用/停用策略"""
        cur = self.db.conn.cursor()
        cur.execute(
            "UPDATE strategy SET enabled=?, updated_at=datetime('now') WHERE id=?",
            (1 if enabled else 0, strategy_id),
        )
        self.db.conn.commit()
        state = "启用" if enabled else "停用"
        logger.info(f"策略 #{strategy_id} 已{state}")

    def save_strategy_log(self, strategy_id: int, level: str, message: str):
        """保存策略运行日志"""
        cur = self.db.conn.cursor()
        cur.execute(
            "INSERT INTO strategy_log (strategy_id, level, message) VALUES (?, ?, ?)",
            (strategy_id, level, message),
        )
        self.db.conn.commit()

    def get_strategy_logs(self, strategy_id: int, limit: int = 50) -> list:
        """获取策略日志"""
        cur = self.db.conn.cursor()
        cur.execute(
            "SELECT * FROM strategy_log WHERE strategy_id=? ORDER BY created_at DESC LIMIT ?",
            (strategy_id, limit),
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    # ─────────────────────── 主循环 ───────────────────────

    def run_tick(self, quotes: dict):
        """
        主循环：对所有启用的策略用当前行情进行评估

        Args:
            quotes: {code: {price, volume, name, ...}}
        """
        strategies = [s for s in self.load_strategies() if s.get("enabled")]
        for strat in strategies:
            try:
                self._evaluate_and_execute(strat, quotes)
            except Exception as e:
                self.save_strategy_log(strat["id"], "ERROR", str(e))
                logger.error(f"策略 #{strat['id']} 执行异常: {e}")

    def _evaluate_and_execute(self, strat: dict, quotes: dict):
        """评估单个策略并在触发时执行"""
        strategy_id = strat["id"]
        mode = strat.get("mode", "visual")
        target_codes = strat.get("target_codes", [])
        account_id = strat.get("account_id", 1)

        if not target_codes:
            return

        for code in target_codes:
            quote = quotes.get(code)
            if not quote or not isinstance(quote, dict):
                continue
            current_price = quote.get("price", 0)
            if not current_price or current_price <= 0:
                continue

            # 确保有 K 线数据
            kline_df = self._ensure_kline(code)

            if mode == "script":
                # 脚本模式
                script = strat.get("script", "")
                if not script.strip():
                    continue
                account_summary = self.paper.get_account_summary(account_id)
                context = {
                    "quote": quote,
                    "kline_df": kline_df,
                    "indicators": self.ind,
                    "account": account_summary,
                    "code": code,
                }
                result = self.script_runner.run(script, context)
                if result.get("error"):
                    self.save_strategy_log(
                        strategy_id, "ERROR",
                        f"{code}: 脚本错误 - {result['error']}"
                    )
                    continue

                signal = result.get("signal")
                if signal in ("buy", "sell"):
                    direction = "BUY" if signal == "buy" else "SELL"
                    quantity = int(result.get("quantity", 0))
                    price = result.get("price") or current_price
                    if quantity > 0:
                        order_id = self.paper.place_order(
                            account_id, code, direction, quantity,
                            order_type="MARKET", price=price,
                            strategy_id=strategy_id,
                        )
                        self.save_strategy_log(
                            strategy_id, "TRADE",
                            f"{code}: {direction} x{quantity} @ {price:.2f}, 订单#{order_id}"
                        )
            else:
                # 可视化条件模式
                conditions = strat.get("conditions", {})
                action = strat.get("action", {})
                if not conditions.get("items"):
                    continue

                triggered = self.evaluator.evaluate(conditions, quote, kline_df)
                if triggered:
                    direction = action.get("direction", "BUY")
                    quantity = int(action.get("quantity", 100))
                    if quantity <= 0:
                        continue

                    # 止损止盈检查
                    stop_loss_pct = action.get("stop_loss_pct", 0)
                    take_profit_pct = action.get("take_profit_pct", 0)

                    order_id = self.paper.place_order(
                        account_id, code, direction, quantity,
                        order_type="MARKET", price=current_price,
                        strategy_id=strategy_id,
                    )
                    msg = (
                        f"{code}: 条件触发 -> {direction} x{quantity} @ {current_price:.2f}, "
                        f"订单#{order_id}"
                    )
                    self.save_strategy_log(strategy_id, "TRADE", msg)
                    logger.info(f"策略 #{strategy_id} {msg}")

                    # 如果有止损止盈，下对应的止损/止盈单
                    if direction == "BUY":
                        if stop_loss_pct > 0:
                            stop_price = round(current_price * (1 - stop_loss_pct / 100), 2)
                            self.paper.place_order(
                                account_id, code, "SELL", quantity,
                                order_type="STOP", price=stop_price,
                                strategy_id=strategy_id,
                            )
                        if take_profit_pct > 0:
                            tp_price = round(current_price * (1 + take_profit_pct / 100), 2)
                            self.paper.place_order(
                                account_id, code, "SELL", quantity,
                                order_type="LIMIT", price=tp_price,
                                strategy_id=strategy_id,
                            )

    def _ensure_kline(self, code: str):
        """加载 K 线数据到缓存"""
        if code in self._kline_cache:
            return self._kline_cache[code]
        try:
            df = self.db.get_kline(code, "K_DAY")
            if df.empty:
                # 尝试其他 K 线类型
                for ktype in ["K_60M", "K_5M", "K_1M"]:
                    df = self.db.get_kline(code, ktype)
                    if not df.empty:
                        break
            self._kline_cache[code] = df
            return df
        except Exception as e:
            logger.warning(f"加载 {code} K线数据失败: {e}")
            import pandas as pd
            empty = pd.DataFrame()
            self._kline_cache[code] = empty
            return empty

    def clear_kline_cache(self):
        """清空 K 线缓存（每轮刷新后可调用）"""
        self._kline_cache.clear()
