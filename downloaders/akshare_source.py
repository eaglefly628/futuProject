"""
AkShare A股数据源 (东方财富)

用于 A 股 ETF / 股票的 K 线采集 —— 免费，无需行情权限。
补 Futu OpenAPI 的 A 股 ETF 行情权限缺口。

数据落库 schema 与 Futu 路径完全一致，下游图表/分析无需改动。
"""
import random
import time
from datetime import datetime, timedelta
from typing import Optional, List

import pandas as pd
from loguru import logger

# 东方财富会限流，需要重试 + 退避
MAX_RETRIES = 4
BASE_BACKOFF = 1.5      # 秒，指数退避基数
MIN_GAP = 0.8           # 相邻请求最小间隔

# 连接被重置类错误，值得重试
RETRIABLE_HINTS = (
    "RemoteDisconnected",
    "Connection aborted",
    "Connection reset",
    "ConnectionError",
    "timed out",
    "Read timed out",
    "Max retries exceeded",
    "Temporary failure",
)


def _is_retriable(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return any(h.lower() in text.lower() for h in RETRIABLE_HINTS)

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    logger.debug("akshare 未安装，A股免费数据源不可用: pip install akshare")


# 本项目 ktype -> akshare 分钟线 period 参数
MIN_PERIOD_MAP = {
    "K_1M": "1",
    "K_5M": "5",
    "K_15M": "15",
    "K_30M": "30",
    "K_60M": "60",
}

# 本项目 ktype -> akshare 日线级 period 参数
DAY_PERIOD_MAP = {
    "K_DAY": "daily",
    "K_WEEK": "weekly",
    "K_MON": "monthly",
}

# akshare 中文列 -> 本项目 schema
COLUMN_MAP = {
    "时间": "time_key",
    "日期": "time_key",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "turnover",
    "涨跌幅": "change_rate",
    "换手率": "turnover_rate",
}


def is_a_share(code: str) -> bool:
    """判断是否为 A 股代码（SH./SZ. 前缀，或纯 6 位数字）"""
    c = (code or "").strip().upper()
    if c.startswith(("SH.", "SZ.")):
        return True
    bare = c.replace(".", "")
    return bare.isdigit() and len(bare) == 6


def to_bare_code(code: str) -> str:
    """SZ.159338 -> 159338"""
    c = (code or "").strip().upper()
    if "." in c:
        c = c.split(".", 1)[1]
    return c


def is_etf_code(bare: str) -> bool:
    """
    A 股 ETF 代码规则（保守判断）:
      沪市 ETF: 51x 52x 56x 58x
      深市 ETF: 15x 16x 18x
    """
    return bare.startswith(("51", "52", "56", "58", "15", "16", "18"))


class AkshareSource:
    """AkShare A 股 K 线采集器（接口对齐 KlineDownloader）"""

    def __init__(self, database, config):
        self.db = database
        self.config = config
        self.interval = max(MIN_GAP,
                            float(config.get("kline", "request_interval", default=0.8)))
        self._last_call = 0.0

        if not AKSHARE_AVAILABLE:
            raise ImportError("请先安装 akshare:  pip install akshare")

    def _pace(self):
        """限流：保证相邻请求之间有最小间隔"""
        elapsed = time.time() - self._last_call
        gap = self.interval + random.uniform(0, 0.4)
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last_call = time.time()

    # ═══════════════════════════════════════
    def download_history(self, code: str, ktype_str: str,
                         start_date: str = None, end_date: str = None,
                         incremental: bool = True) -> int:
        """
        下载 A 股 K 线并落库。

        Args:
            code: 如 "SZ.159338"（也接受裸码 "159338"）
            ktype_str: K_1M / K_5M / K_15M / K_30M / K_60M / K_DAY / K_WEEK / K_MON
            start_date: YYYY-MM-DD，None 则按配置回溯
            end_date: YYYY-MM-DD，None 则今天
            incremental: 增量模式，从库中最新时间续

        Returns:
            落库条数
        """
        if ktype_str not in MIN_PERIOD_MAP and ktype_str not in DAY_PERIOD_MAP:
            logger.error(f"不支持的K线类型: {ktype_str}")
            return 0

        bare = to_bare_code(code)

        # 增量：从库里最新时间开始
        if incremental and start_date is None:
            latest = self.db.get_latest_time(code, ktype_str)
            if latest:
                start_date = str(latest)[:10]
                logger.info(f"增量模式: {code} {ktype_str} 从 {start_date} 继续")

        if start_date is None:
            lookback = self.config.get("kline", "lookback_days", ktype_str, default=90)
            start_date = (datetime.now() - timedelta(days=lookback)).strftime("%Y-%m-%d")
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        logger.info(f"[akshare] 开始下载: {code} {ktype_str} [{start_date} ~ {end_date}]")

        df = None
        last_err = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                df = self._fetch(bare, ktype_str, start_date, end_date)
                break
            except Exception as e:
                last_err = e
                if attempt >= MAX_RETRIES or not _is_retriable(e):
                    logger.error(f"[akshare] 下载异常: {code} {ktype_str} - {e}")
                    self.db.log_download(code, "kline", ktype_str,
                                         start_date, end_date, 0, "error", str(e))
                    return 0
                # 指数退避 + 抖动，避开东财限流
                wait = BASE_BACKOFF * (2 ** (attempt - 1)) + random.uniform(0, 1.0)
                logger.warning(
                    f"[akshare] {code} {ktype_str} 第{attempt}次失败({type(e).__name__})，"
                    f"{wait:.1f}s 后重试")
                time.sleep(wait)

        if df is None:
            logger.error(f"[akshare] 重试耗尽: {code} {ktype_str} - {last_err}")
            self.db.log_download(code, "kline", ktype_str, start_date, end_date,
                                 0, "error", str(last_err))
            return 0

        if df is None or df.empty:
            logger.info(f"[akshare] 无数据: {code} {ktype_str}")
            self.db.log_download(code, "kline", ktype_str, start_date, end_date,
                                 0, "success", "无数据")
            return 0

        saved = self.db.save_kline(code, ktype_str, df)
        self.db.log_download(code, "kline", ktype_str, start_date, end_date,
                             saved, "success")
        logger.info(f"[akshare] 下载完成: {code} {ktype_str} -> 共 {saved} 条")
        return saved

    # ─── 实际抓取 ───
    def _fetch(self, bare: str, ktype_str: str,
               start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        self._pace()
        etf = is_etf_code(bare)

        if ktype_str in MIN_PERIOD_MAP:
            period = MIN_PERIOD_MAP[ktype_str]
            # 分钟线接口要求 "YYYY-MM-DD HH:MM:SS"
            start_dt = f"{start_date} 09:00:00"
            end_dt = f"{end_date} 16:00:00"
            if etf:
                raw = ak.fund_etf_hist_min_em(
                    symbol=bare, period=period, adjust="qfq",
                    start_date=start_dt, end_date=end_dt)
            else:
                raw = ak.stock_zh_a_hist_min_em(
                    symbol=bare, period=period, adjust="qfq",
                    start_date=start_dt, end_date=end_dt)
        else:
            period = DAY_PERIOD_MAP[ktype_str]
            s = start_date.replace("-", "")
            e = end_date.replace("-", "")
            if etf:
                raw = ak.fund_etf_hist_em(
                    symbol=bare, period=period, adjust="qfq",
                    start_date=s, end_date=e)
            else:
                raw = ak.stock_zh_a_hist(
                    symbol=bare, period=period, adjust="qfq",
                    start_date=s, end_date=e)

        return self._normalize(raw)

    @staticmethod
    def _normalize(raw: pd.DataFrame) -> Optional[pd.DataFrame]:
        """akshare 中文列 -> 本项目 schema"""
        if raw is None or raw.empty:
            return None

        df = raw.rename(columns=COLUMN_MAP)

        if "time_key" not in df.columns:
            logger.warning(f"[akshare] 返回列异常: {list(raw.columns)}")
            return None

        # 日线返回的是日期，补全为 datetime 字符串，与 Futu 的 time_key 对齐
        df["time_key"] = df["time_key"].astype(str)
        mask = df["time_key"].str.len() <= 10
        df.loc[mask, "time_key"] = df.loc[mask, "time_key"] + " 00:00:00"

        for col in ["open", "high", "low", "close", "volume",
                    "turnover", "change_rate", "turnover_rate"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                df[col] = None

        # 与 Futu schema 对齐的补充列
        if "last_close" not in df.columns:
            df["last_close"] = df["close"].shift(1)
        if "pe_ratio" not in df.columns:
            df["pe_ratio"] = None

        keep = ["time_key", "open", "high", "low", "close", "volume",
                "turnover", "pe_ratio", "turnover_rate", "change_rate", "last_close"]
        df = df[[c for c in keep if c in df.columns]]

        return df.dropna(subset=["close"]).reset_index(drop=True)

    # ─── 批量 ───
    def download_all_types(self, code: str, ktypes: List[str] = None,
                           incremental: bool = True) -> dict:
        if ktypes is None:
            ktypes = self.config.get("kline", "default_types",
                                     default=["K_5M", "K_DAY"])
        return {kt: self.download_history(code, kt, incremental=incremental)
                for kt in ktypes}

    def batch_download(self, codes: List[str], ktypes: List[str] = None,
                       incremental: bool = True) -> dict:
        results = {}
        for code in codes:
            logger.info(f"[akshare] ===== 批量下载: {code} =====")
            results[code] = self.download_all_types(code, ktypes, incremental)
        return results


class MarketRouter:
    """
    按市场路由到合适的数据源。

      A 股 (SH./SZ.)  -> AkshareSource   免费，无权限限制
      港股/美股       -> KlineDownloader Futu OpenAPI
    """

    def __init__(self, futu_downloader=None, akshare_source=None):
        self.futu = futu_downloader
        self.akshare = akshare_source

    def pick(self, code: str):
        """返回该标的应使用的下载器，无可用源时返回 None"""
        if is_a_share(code) and self.akshare is not None:
            return self.akshare
        return self.futu

    def source_name(self, code: str) -> str:
        src = self.pick(code)
        if src is None:
            return "无可用数据源"
        return "akshare(东财)" if src is self.akshare else "Futu OpenAPI"

    def download_history(self, code: str, ktype_str: str,
                         start_date: str = None, end_date: str = None,
                         incremental: bool = True) -> int:
        src = self.pick(code)
        if src is None:
            logger.error(f"无可用数据源: {code}")
            return 0
        return src.download_history(code, ktype_str, start_date, end_date, incremental)
