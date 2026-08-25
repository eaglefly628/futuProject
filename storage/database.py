"""
SQLite数据库管理
管理K线、逐笔和元数据的持久化存储
"""
import sqlite3
import pandas as pd
from pathlib import Path
from typing import Optional, List, Tuple
from datetime import datetime, timedelta
from loguru import logger


class Database:
    """SQLite数据库管理器"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._init_tables()

    def _connect(self):
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        logger.info(f"数据库连接: {self.db_path}")

    def _init_tables(self):
        cur = self.conn.cursor()

        # K线数据表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS kline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            ktype TEXT NOT NULL,
            time_key TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL,
            volume REAL, turnover REAL,
            pe_ratio REAL, turnover_rate REAL,
            change_rate REAL,
            last_close REAL,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(code, ktype, time_key)
        )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_kline_code_type ON kline(code, ktype)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_kline_time ON kline(time_key)")

        # 逐笔成交数据表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tick (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            time TEXT NOT NULL,
            price REAL,
            volume REAL,
            turnover REAL,
            ticker_direction TEXT,
            sequence BIGINT,
            type TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tick_code ON tick(code)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tick_time ON tick(time)")

        # 股票元数据表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_meta (
            code TEXT PRIMARY KEY,
            name TEXT,
            market TEXT,
            stock_type TEXT,
            lot_size INTEGER,
            list_date TEXT,
            last_updated TEXT,
            extra TEXT
        )
        """)

        # 下载任务记录表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS download_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            data_type TEXT NOT NULL,
            ktype TEXT,
            start_time TEXT,
            end_time TEXT,
            record_count INTEGER,
            status TEXT DEFAULT 'success',
            error_msg TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """)

        # 实时行情缓存表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS realtime_quote (
            code TEXT PRIMARY KEY,
            name TEXT, price REAL, change_rate REAL, change_val REAL,
            volume REAL, turnover REAL, amplitude REAL,
            high REAL, low REAL, open REAL, prev_close REAL,
            bid_price REAL, ask_price REAL, bid_vol REAL, ask_vol REAL,
            pe_ratio REAL, pb_ratio REAL, volume_ratio REAL,
            updated_at TEXT
        )
        """)

        # 价格预警表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS price_alert (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL, name TEXT,
            condition TEXT NOT NULL,
            target_price REAL NOT NULL,
            triggered INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            triggered_at TEXT
        )
        """)

        # 模拟账户表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS paper_account (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT DEFAULT '默认账户',
            initial_cash REAL DEFAULT 1000000,
            cash REAL DEFAULT 1000000,
            total_asset REAL DEFAULT 1000000,
            currency TEXT DEFAULT 'CNY',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """)

        # 模拟持仓表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS paper_position (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            code TEXT NOT NULL, name TEXT, market TEXT,
            quantity INTEGER DEFAULT 0,
            avg_cost REAL DEFAULT 0,
            current_price REAL DEFAULT 0,
            unrealized_pnl REAL DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(account_id, code)
        )
        """)

        # 模拟订单表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS paper_order (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            code TEXT NOT NULL, name TEXT, market TEXT,
            direction TEXT NOT NULL,
            order_type TEXT DEFAULT 'MARKET',
            quantity INTEGER NOT NULL,
            price REAL,
            filled_quantity INTEGER DEFAULT 0,
            filled_price REAL,
            commission REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            fees REAL DEFAULT 0,
            status TEXT DEFAULT 'PENDING',
            strategy_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            filled_at TEXT
        )
        """)

        # 策略表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS strategy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            type TEXT DEFAULT 'visual',
            target_codes TEXT,
            conditions TEXT,
            actions TEXT,
            script TEXT,
            enabled INTEGER DEFAULT 0,
            account_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """)

        # 策略日志表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS strategy_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            detail TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """)

        # 索引
        cur.execute("CREATE INDEX IF NOT EXISTS idx_paper_position_account ON paper_position(account_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_paper_order_account ON paper_order(account_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_paper_order_status ON paper_order(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_strategy_log_strategy ON strategy_log(strategy_id)")

        self.conn.commit()
        logger.info("数据表初始化完成")

    def save_kline(self, code: str, ktype: str, df: pd.DataFrame) -> int:
        """保存K线数据 (UPSERT)"""
        if df.empty:
            return 0
        records = []
        for _, row in df.iterrows():
            records.append((
                code, ktype, str(row.get("time_key", "")),
                row.get("open"), row.get("high"), row.get("low"), row.get("close"),
                row.get("volume"), row.get("turnover"),
                row.get("pe_ratio"), row.get("turnover_rate"),
                row.get("change_rate"), row.get("last_close"),
            ))
        cur = self.conn.cursor()
        cur.executemany("""
            INSERT OR REPLACE INTO kline
            (code, ktype, time_key, open, high, low, close,
             volume, turnover, pe_ratio, turnover_rate, change_rate, last_close)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        self.conn.commit()
        count = len(records)
        logger.debug(f"保存K线: {code} {ktype} -> {count}条")
        return count

    def save_tick(self, code: str, df: pd.DataFrame) -> int:
        """保存逐笔数据"""
        if df.empty:
            return 0
        records = []
        for _, row in df.iterrows():
            records.append((
                code, str(row.get("time", "")),
                row.get("price"), row.get("volume"), row.get("turnover"),
                str(row.get("ticker_direction", "")),
                row.get("sequence"), str(row.get("type", "")),
            ))
        cur = self.conn.cursor()
        cur.executemany("""
            INSERT INTO tick (code, time, price, volume, turnover,
                             ticker_direction, sequence, type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        self.conn.commit()
        count = len(records)
        logger.debug(f"保存逐笔: {code} -> {count}条")
        return count

    def get_kline(self, code: str, ktype: str,
                  start: str = None, end: str = None) -> pd.DataFrame:
        """查询K线数据"""
        query = "SELECT * FROM kline WHERE code=? AND ktype=?"
        params: list = [code, ktype]
        if start:
            query += " AND time_key >= ?"
            params.append(start)
        if end:
            query += " AND time_key <= ?"
            params.append(end)
        query += " ORDER BY time_key ASC"
        return pd.read_sql_query(query, self.conn, params=params)

    def get_tick(self, code: str, start: str = None, end: str = None) -> pd.DataFrame:
        """查询逐笔数据"""
        query = "SELECT * FROM tick WHERE code=?"
        params: list = [code]
        if start:
            query += " AND time >= ?"
            params.append(start)
        if end:
            query += " AND time <= ?"
            params.append(end)
        query += " ORDER BY time ASC"
        return pd.read_sql_query(query, self.conn, params=params)

    def get_latest_time(self, code: str, ktype: str) -> Optional[str]:
        """获取某只股票某K线类型的最新时间"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT MAX(time_key) FROM kline WHERE code=? AND ktype=?",
            (code, ktype)
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None

    def log_download(self, code: str, data_type: str, ktype: str = "",
                     start_time: str = "", end_time: str = "",
                     record_count: int = 0, status: str = "success",
                     error_msg: str = ""):
        """记录下载日志"""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO download_log
            (code, data_type, ktype, start_time, end_time, record_count, status, error_msg)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (code, data_type, ktype, start_time, end_time, record_count, status, error_msg))
        self.conn.commit()

    def get_stats(self) -> dict:
        """获取数据库统计信息"""
        cur = self.conn.cursor()
        stats = {}
        cur.execute("SELECT COUNT(*) FROM kline")
        stats["kline_total"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT code) FROM kline")
        stats["kline_stocks"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tick")
        stats["tick_total"] = cur.fetchone()[0]
        cur.execute("SELECT code, ktype, COUNT(*), MIN(time_key), MAX(time_key) FROM kline GROUP BY code, ktype")
        stats["kline_detail"] = cur.fetchall()
        # DB文件大小
        stats["db_size_mb"] = round(Path(self.db_path).stat().st_size / 1024 / 1024, 2)
        return stats

    def export_to_parquet(self, code: str, ktype: str, output_dir: str) -> str:
        """导出数据为Parquet格式"""
        df = self.get_kline(code, ktype)
        if df.empty:
            return ""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        fname = f"{code.replace('.','_')}_{ktype}.parquet"
        fpath = str(Path(output_dir) / fname)
        df.to_parquet(fpath, index=False, engine="pyarrow")
        logger.info(f"导出Parquet: {fpath} ({len(df)}条)")
        return fpath

    def export_to_csv(self, code: str, ktype: str, output_dir: str) -> str:
        """导出数据为CSV格式"""
        df = self.get_kline(code, ktype)
        if df.empty:
            return ""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        fname = f"{code.replace('.','_')}_{ktype}.csv"
        fpath = str(Path(output_dir) / fname)
        df.to_csv(fpath, index=False, encoding="utf-8-sig")
        logger.info(f"导出CSV: {fpath} ({len(df)}条)")
        return fpath

    # ─── 实时行情 ───

    def save_quotes(self, quotes: list):
        """批量保存实时行情"""
        if not quotes:
            return
        cur = self.conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for q in quotes:
            cur.execute("""
                INSERT OR REPLACE INTO realtime_quote
                (code, name, price, change_rate, change_val,
                 volume, turnover, amplitude, high, low, open, prev_close,
                 bid_price, ask_price, bid_vol, ask_vol,
                 pe_ratio, pb_ratio, volume_ratio, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                q.get("code"), q.get("name"), q.get("price"),
                q.get("change_rate"), q.get("change_val"),
                q.get("volume"), q.get("turnover"), q.get("amplitude"),
                q.get("high"), q.get("low"), q.get("open"), q.get("prev_close"),
                q.get("bid_price"), q.get("ask_price"),
                q.get("bid_vol"), q.get("ask_vol"),
                q.get("pe_ratio"), q.get("pb_ratio"), q.get("volume_ratio"),
                now,
            ))
        self.conn.commit()
        logger.debug(f"保存实时行情: {len(quotes)}条")

    def get_quotes(self) -> list:
        """获取所有缓存的实时行情"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM realtime_quote ORDER BY code")
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ─── 价格预警 ───

    def save_alert(self, code, name, condition, target_price) -> int:
        """保存价格预警"""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO price_alert (code, name, condition, target_price)
            VALUES (?, ?, ?, ?)
        """, (code, name, condition, target_price))
        self.conn.commit()
        alert_id = cur.lastrowid
        logger.info(f"新增价格预警: {code} {condition} {target_price}")
        return alert_id

    def get_alerts(self, triggered=None) -> list:
        """获取价格预警列表"""
        cur = self.conn.cursor()
        if triggered is not None:
            cur.execute("SELECT * FROM price_alert WHERE triggered=? ORDER BY created_at DESC",
                        (int(triggered),))
        else:
            cur.execute("SELECT * FROM price_alert ORDER BY created_at DESC")
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def trigger_alert(self, alert_id):
        """触发预警"""
        cur = self.conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("UPDATE price_alert SET triggered=1, triggered_at=? WHERE id=?",
                    (now, alert_id))
        self.conn.commit()
        logger.info(f"预警已触发: id={alert_id}")

    def delete_alert(self, alert_id):
        """删除预警"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM price_alert WHERE id=?", (alert_id,))
        self.conn.commit()
        logger.info(f"删除预警: id={alert_id}")

    # ─── 模拟账户 ───

    def create_paper_account(self, name="默认账户", initial_cash=1000000) -> int:
        """创建模拟账户"""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO paper_account (name, initial_cash, cash, total_asset)
            VALUES (?, ?, ?, ?)
        """, (name, initial_cash, initial_cash, initial_cash))
        self.conn.commit()
        account_id = cur.lastrowid
        logger.info(f"创建模拟账户: {name} 初始资金={initial_cash}")
        return account_id

    def get_paper_account(self, account_id) -> dict:
        """获取模拟账户"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM paper_account WHERE id=?", (account_id,))
        row = cur.fetchone()
        if not row:
            return {}
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))

    def update_paper_account(self, account_id, **kwargs):
        """更新模拟账户"""
        if not kwargs:
            return
        kwargs["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [account_id]
        cur = self.conn.cursor()
        cur.execute(f"UPDATE paper_account SET {sets} WHERE id=?", vals)
        self.conn.commit()
        logger.debug(f"更新模拟账户: id={account_id}")

    # ─── 模拟持仓 ───

    def get_positions(self, account_id) -> list:
        """获取模拟持仓列表"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM paper_position WHERE account_id=? ORDER BY code",
                    (account_id,))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def save_position(self, account_id, code, name, market, quantity, avg_cost, current_price=0):
        """保存/更新持仓 (UPSERT)"""
        unrealized_pnl = (current_price - avg_cost) * quantity if current_price else 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO paper_position
            (account_id, code, name, market, quantity, avg_cost, current_price, unrealized_pnl, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, code) DO UPDATE SET
                name=excluded.name, market=excluded.market,
                quantity=excluded.quantity, avg_cost=excluded.avg_cost,
                current_price=excluded.current_price,
                unrealized_pnl=excluded.unrealized_pnl,
                updated_at=excluded.updated_at
        """, (account_id, code, name, market, quantity, avg_cost, current_price, unrealized_pnl, now))
        self.conn.commit()
        logger.debug(f"保存持仓: {code} 数量={quantity} 均价={avg_cost}")

    def update_position(self, account_id, code, **kwargs):
        """更新持仓"""
        if not kwargs:
            return
        kwargs["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [account_id, code]
        cur = self.conn.cursor()
        cur.execute(f"UPDATE paper_position SET {sets} WHERE account_id=? AND code=?", vals)
        self.conn.commit()
        logger.debug(f"更新持仓: {code}")

    def delete_position(self, account_id, code):
        """删除持仓"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM paper_position WHERE account_id=? AND code=?",
                    (account_id, code))
        self.conn.commit()
        logger.debug(f"删除持仓: {code}")

    # ─── 模拟订单 ───

    def save_order(self, account_id, code, name, market, direction, order_type,
                   quantity, price=None, strategy_id=None) -> int:
        """保存订单"""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO paper_order
            (account_id, code, name, market, direction, order_type, quantity, price, strategy_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (account_id, code, name, market, direction, order_type, quantity, price, strategy_id))
        self.conn.commit()
        order_id = cur.lastrowid
        logger.info(f"新建订单: {direction} {code} x{quantity} id={order_id}")
        return order_id

    def update_order(self, order_id, **kwargs):
        """更新订单"""
        if not kwargs:
            return
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [order_id]
        cur = self.conn.cursor()
        cur.execute(f"UPDATE paper_order SET {sets} WHERE id=?", vals)
        self.conn.commit()
        logger.debug(f"更新订单: id={order_id}")

    def get_orders(self, account_id, status=None) -> list:
        """获取订单列表"""
        cur = self.conn.cursor()
        if status:
            cur.execute("SELECT * FROM paper_order WHERE account_id=? AND status=? ORDER BY created_at DESC",
                        (account_id, status))
        else:
            cur.execute("SELECT * FROM paper_order WHERE account_id=? ORDER BY created_at DESC",
                        (account_id,))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ─── 策略 ───

    def save_strategy(self, name, type_="visual", target_codes="", conditions="",
                      actions="", script="", account_id=None) -> int:
        """保存策略"""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO strategy
            (name, type, target_codes, conditions, actions, script, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, type_, target_codes, conditions, actions, script, account_id))
        self.conn.commit()
        strategy_id = cur.lastrowid
        logger.info(f"新建策略: {name} id={strategy_id}")
        return strategy_id

    def update_strategy(self, strategy_id, **kwargs):
        """更新策略"""
        if not kwargs:
            return
        kwargs["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [strategy_id]
        cur = self.conn.cursor()
        cur.execute(f"UPDATE strategy SET {sets} WHERE id=?", vals)
        self.conn.commit()
        logger.debug(f"更新策略: id={strategy_id}")

    def get_strategies(self) -> list:
        """获取所有策略"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM strategy ORDER BY created_at DESC")
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_strategy(self, strategy_id) -> dict:
        """获取单个策略"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM strategy WHERE id=?", (strategy_id,))
        row = cur.fetchone()
        if not row:
            return {}
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))

    def delete_strategy(self, strategy_id):
        """删除策略"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM strategy WHERE id=?", (strategy_id,))
        cur.execute("DELETE FROM strategy_log WHERE strategy_id=?", (strategy_id,))
        self.conn.commit()
        logger.info(f"删除策略: id={strategy_id}")

    # ─── 策略日志 ───

    def save_strategy_log(self, strategy_id, event, detail=""):
        """保存策略日志"""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO strategy_log (strategy_id, event, detail)
            VALUES (?, ?, ?)
        """, (strategy_id, event, detail))
        self.conn.commit()
        logger.debug(f"策略日志: strategy={strategy_id} event={event}")

    def get_strategy_logs(self, strategy_id, limit=100) -> list:
        """获取策略日志"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM strategy_log WHERE strategy_id=? ORDER BY created_at DESC LIMIT ?",
            (strategy_id, limit))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def close(self):
        if self.conn:
            self.conn.close()
            logger.info("数据库连接已关闭")
