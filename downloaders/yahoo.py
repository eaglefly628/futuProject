"""
Yahoo Finance 行情接口直连

用途：当本机走海外代理（VPN / 网卡代理）导致国内行情源不可达时，
Yahoo 反而是通的，可作为 A 股数据的替代来源。

直接调 Yahoo 的 chart API，不依赖 yfinance 包。

代码映射：
    SZ.159338  ->  159338.SZ
    SH.512050  ->  512050.SS      注意沪市是 .SS 不是 .SH
"""
import random
import time
from typing import Optional

import pandas as pd
import requests
from loguru import logger

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# ktype -> (interval, 可取的最大 range)
# Yahoo 对分钟线的历史深度有硬性限制
INTERVAL_MAP = {
    "K_1M":  ("1m",  "7d"),      # 1分钟仅最近 7 天
    "K_5M":  ("5m",  "60d"),     # 分钟级最多 60 天
    "K_15M": ("15m", "60d"),
    "K_30M": ("30m", "60d"),
    "K_60M": ("60m", "730d"),    # 小时线可到 2 年
    "K_DAY": ("1d",  "max"),
    "K_WEEK": ("1wk", "max"),
    "K_MON": ("1mo", "max"),
}


def to_yahoo_symbol(code: str) -> str:
    """SZ.159338 -> 159338.SZ ；SH.512050 -> 512050.SS"""
    c = (code or "").strip().upper()
    if "." in c:
        prefix, bare = c.split(".", 1)
        if prefix == "SZ":
            return f"{bare}.SZ"
        if prefix == "SH":
            return f"{bare}.SS"          # 沪市在 Yahoo 是 .SS
        if prefix == "HK":
            return f"{bare.lstrip('0').zfill(4)}.HK"
        if prefix == "US":
            return bare
        return c

    if c.isdigit() and len(c) == 6:
        return f"{c}.SS" if c.startswith(("5", "6", "9")) else f"{c}.SZ"
    return c


class YahooClient:
    """Yahoo Finance 行情客户端"""

    def __init__(self, timeout: int = 20, min_gap: float = 0.5):
        self.timeout = timeout
        self.min_gap = min_gap
        self._last_call = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def _pace(self):
        elapsed = time.time() - self._last_call
        gap = self.min_gap + random.uniform(0, 0.3)
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last_call = time.time()

    def get_kline(self, code: str, ktype: str,
                  start_date: str = None, end_date: str = None
                  ) -> Optional[pd.DataFrame]:
        """
        拉取 K 线，返回本项目 schema 的 DataFrame。

        注意 Yahoo 对分钟线有历史深度限制（见 INTERVAL_MAP），
        请求再长的区间也只会返回上限内的数据。
        """
        if ktype not in INTERVAL_MAP:
            raise ValueError(f"Yahoo 不支持的K线类型: {ktype}")

        symbol = to_yahoo_symbol(code)
        interval, rng = INTERVAL_MAP[ktype]

        # Yahoo 限流较严，429 需要退避重试
        data = None
        last_err = None
        for attempt in range(1, 5):
            self._pace()
            self._session.headers["User-Agent"] = random.choice(USER_AGENTS)
            try:
                resp = self._session.get(
                    CHART_URL.format(symbol=symbol),
                    params={"interval": interval, "range": rng,
                            "includePrePost": "false", "events": "div,split"},
                    timeout=self.timeout)
                if resp.status_code == 429:
                    wait = 2.0 * (2 ** (attempt - 1)) + random.uniform(0, 1)
                    logger.warning(
                        f"[Yahoo] {symbol} 触发限流，{wait:.1f}s 后重试 "
                        f"({attempt}/4)")
                    time.sleep(wait)
                    last_err = RuntimeError("429 Too Many Requests")
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.exceptions.RequestException as e:
                last_err = e
                if attempt >= 4:
                    break
                time.sleep(1.5 * attempt)

        if data is None:
            raise RuntimeError(f"Yahoo 请求失败 ({symbol}): {last_err}")

        chart = (data or {}).get("chart") or {}
        if chart.get("error"):
            raise RuntimeError(f"Yahoo 返回错误: {chart['error']}")

        results = chart.get("result") or []
        if not results:
            return None

        r = results[0]
        stamps = r.get("timestamp") or []
        quote = ((r.get("indicators") or {}).get("quote") or [{}])[0]
        if not stamps or not quote:
            return None

        # 必须转成普通 list：pd.to_datetime 返回的是 Index，
        # 与 list 混在同一个 dict 里构造 DataFrame 时 pandas 会按 Index 对齐
        # 而不是按位置，导致列数据错位。
        times = list(
            pd.to_datetime(stamps, unit="s", utc=True)
              .tz_convert("Asia/Shanghai")
              .strftime("%Y-%m-%d %H:%M:%S"))

        n = len(times)

        def col(name):
            v = quote.get(name) or []
            v = list(v)
            # 长度对不上就补齐，避免静默错位
            if len(v) < n:
                v = v + [None] * (n - len(v))
            return v[:n]

        df = pd.DataFrame({
            "time_key": times,
            "open": col("open"),
            "high": col("high"),
            "low": col("low"),
            "close": col("close"),
            "volume": col("volume"),
        })

        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

        # Yahoo 对当日未完成 / 停牌的 K 线会返回 null，
        # OHLC 任一缺失都不是有效K线，整行丢弃
        df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
        df["volume"] = df["volume"].fillna(0)
        if df.empty:
            return None

        # 兜底校验：high/low 必须包住 open/close，否则数据有问题
        bad = ((df["high"] < df[["open", "close"]].max(axis=1)) |
               (df["low"] > df[["open", "close"]].min(axis=1)))
        if bad.any():
            logger.warning(f"[Yahoo] {symbol} 丢弃 {int(bad.sum())} 根 OHLC 不自洽的K线")
            df = df[~bad].reset_index(drop=True)
        if df.empty:
            return None

        # 补齐本项目 schema 需要的列
        df["turnover"] = df["close"] * df["volume"]     # Yahoo 不给成交额，估算
        df["last_close"] = df["close"].shift(1)
        df["change_rate"] = (
            (df["close"] - df["last_close"]) / df["last_close"] * 100).round(4)
        df["pe_ratio"] = None
        df["turnover_rate"] = None

        # 本地裁剪日期
        if start_date or end_date:
            ts = pd.to_datetime(df["time_key"])
            mask = pd.Series(True, index=df.index)
            if start_date:
                mask &= ts >= pd.Timestamp(f"{start_date} 00:00:00")
            if end_date:
                mask &= ts <= pd.Timestamp(f"{end_date} 23:59:59")
            df = df[mask].reset_index(drop=True)

        keep = ["time_key", "open", "high", "low", "close", "volume",
                "turnover", "pe_ratio", "turnover_rate", "change_rate", "last_close"]
        df = df[keep]
        logger.info(f"[Yahoo] {symbol} {ktype} 获取 {len(df)} 条")
        return df if not df.empty else None

    def close(self):
        try:
            self._session.close()
        except Exception:
            pass
