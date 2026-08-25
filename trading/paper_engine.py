"""模拟交易引擎 - 账户管理、下单、成交、持仓"""
import json
from datetime import datetime
from loguru import logger


class PaperEngine:
    """纸盘交易引擎：管理模拟账户、订单、持仓"""

    def __init__(self, db, fee_calculator, config):
        self.db = db
        self.fee_calc = fee_calculator
        self.config = config
        self._quotes_cache = {}  # {code: {price, name, ...}} 实时行情缓存
        self._ensure_tables()
        self._ensure_default_account()

    # ─────────────────────── 初始化 ───────────────────────

    def _ensure_tables(self):
        """确保模拟交易相关表存在"""
        cur = self.db.conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS paper_account (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            initial_cash REAL DEFAULT 1000000,
            cash REAL DEFAULT 1000000,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS paper_order (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            name TEXT DEFAULT '',
            direction TEXT NOT NULL,
            order_type TEXT DEFAULT 'MARKET',
            quantity INTEGER NOT NULL,
            price REAL,
            filled_price REAL,
            commission REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            fees REAL DEFAULT 0,
            total_cost REAL DEFAULT 0,
            status TEXT DEFAULT 'PENDING',
            strategy_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            filled_at TEXT,
            FOREIGN KEY(account_id) REFERENCES paper_account(id)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS paper_position (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            name TEXT DEFAULT '',
            quantity INTEGER DEFAULT 0,
            avg_cost REAL DEFAULT 0,
            current_price REAL DEFAULT 0,
            unrealized_pnl REAL DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(account_id, code),
            FOREIGN KEY(account_id) REFERENCES paper_account(id)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS paper_trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            order_id INTEGER,
            code TEXT NOT NULL,
            direction TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            amount REAL NOT NULL,
            commission REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            fees REAL DEFAULT 0,
            realized_pnl REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """)
        self.db.conn.commit()
        logger.info("模拟交易数据表初始化完成")

    def _ensure_default_account(self):
        """如果没有账户则创建默认账户"""
        cur = self.db.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM paper_account")
        count = cur.fetchone()[0]
        if count == 0:
            initial_cash = self.config.get("paper_trading", "initial_cash", default=1000000)
            cur.execute(
                "INSERT INTO paper_account (name, initial_cash, cash) VALUES (?, ?, ?)",
                ("默认账户", initial_cash, initial_cash),
            )
            self.db.conn.commit()
            logger.info(f"已创建默认模拟账户, 初始资金: {initial_cash:,.2f}")

    def get_default_account_id(self) -> int:
        """获取默认账户ID"""
        cur = self.db.conn.cursor()
        cur.execute("SELECT id FROM paper_account ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else 1

    # ─────────────────────── 行情缓存 ───────────────────────

    def update_quotes_cache(self, quotes: dict):
        """更新行情缓存 quotes: {code: {price, name, ...}}"""
        self._quotes_cache.update(quotes)

    # ─────────────────────── 下单 ───────────────────────

    def place_order(self, account_id, code, direction, quantity,
                    order_type="MARKET", price=None, strategy_id=None) -> int:
        """
        下单

        Args:
            account_id: 账户ID
            code: 股票代码
            direction: "BUY" 或 "SELL"
            quantity: 数量
            order_type: "MARKET" / "LIMIT" / "STOP"
            price: 限价/止损价 (市价单可不填)
            strategy_id: 关联策略ID

        Returns:
            订单ID
        """
        direction = direction.upper()
        order_type = order_type.upper()

        # 获取股票名称
        name = ""
        quote = self._quotes_cache.get(code, {})
        if isinstance(quote, dict):
            name = quote.get("name", "")

        # 卖出前检查持仓
        if direction == "SELL":
            pos = self._get_position(account_id, code)
            if not pos or pos["quantity"] < quantity:
                avail = pos["quantity"] if pos else 0
                logger.warning(f"卖出失败: {code} 持仓不足, 持有 {avail}, 欲卖 {quantity}")
                return -1

        cur = self.db.conn.cursor()
        cur.execute(
            """INSERT INTO paper_order
               (account_id, code, name, direction, order_type, quantity, price, status, strategy_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
            (account_id, code, name, direction, order_type, quantity, price, strategy_id),
        )
        self.db.conn.commit()
        order_id = cur.lastrowid
        logger.info(f"下单成功: #{order_id} {direction} {code} x{quantity} type={order_type} price={price}")

        # 市价单立即成交
        if order_type == "MARKET":
            fill_price = price
            if not fill_price:
                fill_price = quote.get("price") if isinstance(quote, dict) else None
            if fill_price and fill_price > 0:
                order = self._get_order(order_id)
                if order:
                    self._execute_fill(order, float(fill_price))
            else:
                logger.warning(f"市价单 #{order_id} 缺少行情价格，等待下次行情更新")

        return order_id

    # ─────────────────────── 尝试成交 ───────────────────────

    def try_fill_orders(self, quotes: dict):
        """
        尝试用当前行情成交待处理的限价/止损订单

        Args:
            quotes: {code: {price, ...}}
        """
        self.update_quotes_cache(quotes)
        cur = self.db.conn.cursor()
        cur.execute(
            "SELECT * FROM paper_order WHERE status='PENDING' AND order_type != 'MARKET'"
        )
        columns = [desc[0] for desc in cur.description]
        pending = [dict(zip(columns, row)) for row in cur.fetchall()]

        for order in pending:
            code = order["code"]
            quote = quotes.get(code)
            if not quote or not isinstance(quote, dict):
                continue
            current_price = quote.get("price", 0)
            if not current_price or current_price <= 0:
                continue

            order_price = order.get("price", 0) or 0
            order_type = order.get("order_type", "")
            direction = order.get("direction", "")

            should_fill = False

            if order_type == "LIMIT":
                if direction == "BUY" and current_price <= order_price:
                    should_fill = True
                elif direction == "SELL" and current_price >= order_price:
                    should_fill = True
            elif order_type == "STOP":
                if direction == "BUY" and current_price >= order_price:
                    should_fill = True
                elif direction == "SELL" and current_price <= order_price:
                    should_fill = True

            if should_fill:
                fill_price = order_price if order_type == "LIMIT" else current_price
                self._execute_fill(order, fill_price)

    # ─────────────────────── 成交执行 ───────────────────────

    def _execute_fill(self, order: dict, fill_price: float):
        """
        执行成交: 更新资金、持仓、订单状态

        BUY: 扣除 (quantity * price + fees)，更新/新建持仓，计算新均价
        SELL: 增加 (quantity * price - fees)，减少持仓数量（减至0则删除）
        """
        order_id = order["id"]
        account_id = order["account_id"]
        code = order["code"]
        direction = order["direction"]
        quantity = order["quantity"]

        # 计算手续费
        fee_info = self.fee_calc.calculate(code, direction, quantity, fill_price)
        commission = fee_info["commission"]
        tax = fee_info["tax"]
        fees = fee_info["fees"]
        total_cost = fee_info["total_cost"]

        amount = quantity * fill_price
        cur = self.db.conn.cursor()

        # 获取当前账户现金
        cur.execute("SELECT cash FROM paper_account WHERE id=?", (account_id,))
        row = cur.fetchone()
        if not row:
            logger.error(f"账户 {account_id} 不存在")
            return
        cash = row[0]

        realized_pnl = 0.0

        if direction == "BUY":
            needed = amount + total_cost
            if cash < needed:
                logger.warning(f"资金不足: 需要 {needed:.2f}, 可用 {cash:.2f}")
                cur.execute(
                    "UPDATE paper_order SET status='REJECTED' WHERE id=?", (order_id,)
                )
                self.db.conn.commit()
                return
            # 扣款
            cur.execute(
                "UPDATE paper_account SET cash = cash - ? WHERE id=?",
                (needed, account_id),
            )
            # 更新持仓
            pos = self._get_position(account_id, code)
            if pos and pos["quantity"] > 0:
                old_qty = pos["quantity"]
                old_avg = pos["avg_cost"]
                new_qty = old_qty + quantity
                new_avg = (old_qty * old_avg + quantity * fill_price) / new_qty
                cur.execute(
                    """UPDATE paper_position
                       SET quantity=?, avg_cost=?, current_price=?, updated_at=datetime('now')
                       WHERE account_id=? AND code=?""",
                    (new_qty, round(new_avg, 4), fill_price, account_id, code),
                )
            else:
                name = order.get("name", "")
                cur.execute(
                    """INSERT OR REPLACE INTO paper_position
                       (account_id, code, name, quantity, avg_cost, current_price, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (account_id, code, name, quantity, round(fill_price, 4), fill_price),
                )
        else:  # SELL
            # 加款
            received = amount - total_cost
            cur.execute(
                "UPDATE paper_account SET cash = cash + ? WHERE id=?",
                (received, account_id),
            )
            # 减少持仓
            pos = self._get_position(account_id, code)
            if pos:
                old_qty = pos["quantity"]
                new_qty = old_qty - quantity
                realized_pnl = (fill_price - pos["avg_cost"]) * quantity - total_cost
                if new_qty <= 0:
                    cur.execute(
                        "DELETE FROM paper_position WHERE account_id=? AND code=?",
                        (account_id, code),
                    )
                else:
                    cur.execute(
                        """UPDATE paper_position
                           SET quantity=?, current_price=?, updated_at=datetime('now')
                           WHERE account_id=? AND code=?""",
                        (new_qty, fill_price, account_id, code),
                    )

        # 更新订单状态
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            """UPDATE paper_order
               SET status='FILLED', filled_price=?, commission=?, tax=?, fees=?,
                   total_cost=?, filled_at=?
               WHERE id=?""",
            (fill_price, commission, tax, fees, total_cost, now, order_id),
        )

        # 记录交易日志
        cur.execute(
            """INSERT INTO paper_trade_log
               (account_id, order_id, code, direction, quantity, price, amount,
                commission, tax, fees, realized_pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, order_id, code, direction, quantity, fill_price, amount,
             commission, tax, fees, round(realized_pnl, 2)),
        )

        self.db.conn.commit()
        logger.info(
            f"成交: #{order_id} {direction} {code} x{quantity} @ {fill_price:.2f}, "
            f"费用={total_cost:.2f}, 实现盈亏={realized_pnl:.2f}"
        )

    # ─────────────────────── 撤单 ───────────────────────

    def cancel_order(self, order_id):
        """撤销待成交订单"""
        cur = self.db.conn.cursor()
        cur.execute("SELECT status FROM paper_order WHERE id=?", (order_id,))
        row = cur.fetchone()
        if not row:
            logger.warning(f"订单 #{order_id} 不存在")
            return False
        if row[0] != "PENDING":
            logger.warning(f"订单 #{order_id} 状态为 {row[0]}，无法撤销")
            return False
        cur.execute(
            "UPDATE paper_order SET status='CANCELLED' WHERE id=?", (order_id,)
        )
        self.db.conn.commit()
        logger.info(f"已撤销订单 #{order_id}")
        return True

    # ─────────────────────── 查询 ───────────────────────

    def _get_order(self, order_id) -> dict:
        """获取单个订单"""
        cur = self.db.conn.cursor()
        cur.execute("SELECT * FROM paper_order WHERE id=?", (order_id,))
        columns = [desc[0] for desc in cur.description]
        row = cur.fetchone()
        return dict(zip(columns, row)) if row else None

    def _get_position(self, account_id, code) -> dict:
        """获取单只股票持仓"""
        cur = self.db.conn.cursor()
        cur.execute(
            "SELECT * FROM paper_position WHERE account_id=? AND code=?",
            (account_id, code),
        )
        columns = [desc[0] for desc in cur.description]
        row = cur.fetchone()
        return dict(zip(columns, row)) if row else None

    def get_positions(self, account_id) -> list:
        """获取所有持仓"""
        cur = self.db.conn.cursor()
        cur.execute(
            "SELECT * FROM paper_position WHERE account_id=? AND quantity > 0 ORDER BY code",
            (account_id,),
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get_orders(self, account_id, status=None) -> list:
        """获取订单列表"""
        cur = self.db.conn.cursor()
        if status and status != "ALL":
            cur.execute(
                "SELECT * FROM paper_order WHERE account_id=? AND status=? ORDER BY created_at DESC",
                (account_id, status),
            )
        else:
            cur.execute(
                "SELECT * FROM paper_order WHERE account_id=? ORDER BY created_at DESC",
                (account_id,),
            )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get_account_summary(self, account_id) -> dict:
        """
        获取账户摘要

        Returns:
            dict: cash, positions_value, total_asset, total_pnl, pnl_rate, initial_cash
        """
        cur = self.db.conn.cursor()
        cur.execute("SELECT cash, initial_cash FROM paper_account WHERE id=?", (account_id,))
        row = cur.fetchone()
        if not row:
            return {
                "cash": 0, "positions_value": 0, "total_asset": 0,
                "total_pnl": 0, "pnl_rate": 0, "initial_cash": 0,
            }
        cash = row[0]
        initial_cash = row[1]

        positions = self.get_positions(account_id)
        positions_value = sum(
            p["quantity"] * p["current_price"] for p in positions
        )

        total_asset = cash + positions_value
        total_pnl = total_asset - initial_cash
        pnl_rate = (total_pnl / initial_cash * 100) if initial_cash > 0 else 0.0

        return {
            "cash": round(cash, 2),
            "positions_value": round(positions_value, 2),
            "total_asset": round(total_asset, 2),
            "total_pnl": round(total_pnl, 2),
            "pnl_rate": round(pnl_rate, 2),
            "initial_cash": round(initial_cash, 2),
        }

    def get_trade_logs(self, account_id) -> list:
        """获取交易记录"""
        cur = self.db.conn.cursor()
        cur.execute(
            "SELECT * FROM paper_trade_log WHERE account_id=? ORDER BY created_at DESC",
            (account_id,),
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get_trade_stats(self, account_id) -> dict:
        """获取交易统计"""
        logs = self.get_trade_logs(account_id)
        total_trades = len(logs)
        filled_count = total_trades  # trade_log 只记录成交的

        # 按卖出方向计算胜率
        sell_trades = [t for t in logs if t["direction"] == "SELL"]
        win_count = sum(1 for t in sell_trades if t["realized_pnl"] > 0)
        win_rate = (win_count / len(sell_trades) * 100) if sell_trades else 0.0

        total_pnl = sum(t.get("realized_pnl", 0) for t in logs)

        return {
            "total_trades": total_trades,
            "filled_count": filled_count,
            "win_rate": round(win_rate, 1),
            "total_realized_pnl": round(total_pnl, 2),
        }

    # ─────────────────────── 更新持仓价格 ───────────────────────

    def update_positions_price(self, quotes: dict):
        """根据实时行情更新所有持仓的现价和浮动盈亏"""
        self.update_quotes_cache(quotes)
        cur = self.db.conn.cursor()
        cur.execute("SELECT account_id, code, quantity, avg_cost FROM paper_position WHERE quantity > 0")
        rows = cur.fetchall()
        for account_id, code, quantity, avg_cost in rows:
            quote = quotes.get(code)
            if not quote or not isinstance(quote, dict):
                continue
            current_price = quote.get("price", 0)
            if not current_price or current_price <= 0:
                continue
            unrealized_pnl = (current_price - avg_cost) * quantity
            cur.execute(
                """UPDATE paper_position
                   SET current_price=?, unrealized_pnl=?, updated_at=datetime('now')
                   WHERE account_id=? AND code=?""",
                (current_price, round(unrealized_pnl, 2), account_id, code),
            )
        self.db.conn.commit()
