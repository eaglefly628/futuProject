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

    def close(self):
        if self.conn:
            self.conn.close()
            logger.info("数据库连接已关闭")
