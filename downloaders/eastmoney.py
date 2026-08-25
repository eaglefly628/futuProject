"""
东方财富行情接口直连

绕开 akshare 的两个坑：
  1. akshare 的分钟线会先调 get_market_id() 多打一次网络请求
  2. akshare 内部 requests.get() 不带 User-Agent，东财会直接断连

这里自己拼 secid（按代码规则本地推导，零额外请求）、带完整浏览器头、
用同一个 Session 复用连接。
"""
import random
import time
from typing import Optional, List

import pandas as pd
import requests
from loguru import logger

KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
TRENDS_URL = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
UT = "7eea3edcaed734bea9cbfc24409ed989"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

# ktype -> 东财 klt 参数
KLT_MAP = {
    "K_1M": "1", "K_5M": "5", "K_15M": "15", "K_30M": "30", "K_60M": "60",
    "K_DAY": "101", "K_WEEK": "102", "K_MON": "103",
}

# 复权: 0=不复权 1=前复权 2=后复权
FQT_QFQ = "1"

KLINE_COLUMNS = [
    "time_key", "open", "close", "high", "low",
    "volume", "turnover", "amplitude", "change_rate", "change_amount", "turnover_rate",
]

TRENDS_COLUMNS = [
    "time_key", "open", "close", "high", "low", "volume", "turnover", "avg_price",
]


def to_secid(code: str) -> str:
    """
    本地推导东财 secid，不发网络请求。

      沪市(1.): 6xxxxx 股票, 5xxxxx ETF, 000xxx/9xxxxx 指数
      深市(0.): 0xxxxx 3xxxxx 股票, 1xxxxx ETF, 39xxxx 指数
    """
    c = (code or "").strip().upper()
    if "." in c:
        prefix, bare = c.split(".", 1)
        if prefix == "SH":
            return f"1.{bare}"
        if prefix == "SZ":
            return f"0.{bare}"
        c = bare

    if not c.isdigit():
        raise ValueError(f"无法识别的A股代码: {code}")

    if c.startswith(("5", "6", "9")) or c.startswith("000") and len(c) == 6 and c[:3] == "000":
        # 000xxx 既可能是深市股票也可能是沪市指数，默认按深市股票处理
        return f"1.{c}" if c.startswith(("5", "6", "9")) else f"0.{c}"
    return f"0.{c}"


class EastmoneyClient:
    """东财行情客户端"""

    def __init__(self, timeout: int = 15, min_gap: float = 0.6):
        self.timeout = timeout
        self.min_gap = min_gap
        self._last_call = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://quote.eastmoney.com/",
            "Connection": "keep-alive",
        })

    def _pace(self):
        elapsed = time.time() - self._last_call
        gap = self.min_gap + random.uniform(0, 0.3)
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last_call = time.time()

    def _get(self, url: str, params: dict) -> dict:
        self._pace()
        # 每次换个 UA，降低被识别为脚本的概率
        self._session.headers["User-Agent"] = random.choice(USER_AGENTS)
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    # ═══════════════════════════════════════
    def get_kline(self, code: str, ktype: str,
                  start_date: str = None, end_date: str = None,
                  adjust: str = FQT_QFQ) -> Optional[pd.DataFrame]:
        """
        拉取 K 线。

        Args:
            code: SZ.159338 / SH.512050 / 159338
            ktype: K_1M ... K_MON
            start_date / end_date: YYYY-MM-DD，用于本地裁剪
        """
        if ktype not in KLT_MAP:
            raise ValueError(f"不支持的K线类型: {ktype}")

        secid = to_secid(code)

        if ktype == "K_1M":
            df = self._get_trends(secid)
        else:
            df = self._get_kline(secid, KLT_MAP[ktype], adjust)

        if df is None or df.empty:
            return None

        # 本地按日期裁剪
        if start_date or end_date:
            ts = pd.to_datetime(df["time_key"], errors="coerce")
            mask = pd.Series(True, index=df.index)
            if start_date:
                mask &= ts >= pd.Timestamp(f"{start_date} 00:00:00")
            if end_date:
                mask &= ts <= pd.Timestamp(f"{end_date} 23:59:59")
            df = df[mask].reset_index(drop=True)

        return df if not df.empty else None

    def _get_kline(self, secid: str, klt: str, fqt: str) -> Optional[pd.DataFrame]:
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": UT,
            "klt": klt,
            "fqt": fqt,
            "secid": secid,
            "beg": "0",
            "end": "20500000",
        }
        data = self._get(KLINE_URL, params)
        klines = (data.get("data") or {}).get("klines") or []
        if not klines:
            return None

        rows = [item.split(",") for item in klines]
        df = pd.DataFrame(rows, columns=KLINE_COLUMNS[:len(rows[0])])
        return self._to_numeric(df)

    def _get_trends(self, secid: str, ndays: int = 5) -> Optional[pd.DataFrame]:
        """1分钟线走 trends2 接口，东财只提供最近几天"""
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ut": UT,
            "ndays": str(ndays),
            "iscr": "0",
            "secid": secid,
        }
        data = self._get(TRENDS_URL, params)
        trends = (data.get("data") or {}).get("trends") or []
        if not trends:
            return None

        rows = [item.split(",") for item in trends]
        df = pd.DataFrame(rows, columns=TRENDS_COLUMNS[:len(rows[0])])
        return self._to_numeric(df)

    @staticmethod
    def _to_numeric(df: pd.DataFrame) -> pd.DataFrame:
        for col in df.columns:
            if col == "time_key":
                continue
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["time_key"] = df["time_key"].astype(str)
        # 日线只有日期，补时间以对齐 Futu 的 time_key 格式
        mask = df["time_key"].str.len() <= 10
        df.loc[mask, "time_key"] = df.loc[mask, "time_key"] + " 00:00:00"
        return df.dropna(subset=["close"]).reset_index(drop=True)

    def close(self):
        try:
            self._session.close()
        except Exception:
            pass
