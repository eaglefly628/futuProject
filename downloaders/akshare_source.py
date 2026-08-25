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

# akshare 依赖树很大，import 要十几秒，放到真正用到时再加载，
# 否则会拖慢 GUI 启动（看起来像卡死）
_ak = None
_ak_loaded = False


def _get_ak():
    """懒加载 akshare，返回模块或 None"""
    global _ak, _ak_loaded
    if _ak_loaded:
        return _ak
    _ak_loaded = True
    try:
        import akshare as ak
        _ak = ak
        logger.info("akshare 已加载")
    except ImportError:
        _ak = None
        logger.debug("akshare 未安装，A股回退源不可用: pip install akshare")
    return _ak


def akshare_available() -> bool:
    """探测 akshare 是否可用（会触发一次加载）"""
    return _get_ak() is not None


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

# 可选数据源（GUI 下拉直接用这张表）
#   key          显示名               说明
SOURCE_OPTIONS = [
    ("auto",      "自动（依次回退）",   "东财 → Yahoo → akshare，哪个通用哪个"),
    ("eastmoney", "东财直连",          "国内网络最好，分钟线历史最全；挂代理时常被拦"),
    ("yahoo",     "Yahoo",             "海外网络/挂代理时可通；60分钟约2年，1分钟仅7天"),
    ("akshare",   "akshare",           "兜底源，首次调用要加载依赖，较慢"),
]
SOURCE_KEYS = [k for k, _, _ in SOURCE_OPTIONS]
SOURCE_LABELS = {k: n for k, n, _ in SOURCE_OPTIONS}


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
        self.last_source = ""      # 上次命中的源（东财/Yahoo/akshare）
        self.last_error = ""       # 上次失败原因，给 GUI 展示用

        # 东财直连（主路径，需要国内网络）
        try:
            from downloaders.eastmoney import EastmoneyClient
            self._em = EastmoneyClient(min_gap=self.interval)
        except Exception as e:
            logger.warning(f"东财直连不可用: {e}")
            self._em = None

        # Yahoo（备用路径，走海外网络。本机挂 VPN/网卡代理时反而是它通）
        try:
            from downloaders.yahoo import YahooClient
            self._yahoo = YahooClient(min_gap=self.interval)
        except Exception as e:
            logger.warning(f"Yahoo 源不可用: {e}")
            self._yahoo = None

        if self._em is None and self._yahoo is None and not akshare_available():
            raise ImportError(
                "无可用A股数据源。请安装依赖:  pip install requests")

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
                         incremental: bool = True, prefer: str = "auto") -> int:
        """
        下载 A 股 K 线并落库。

        Args:
            code: 如 "SZ.159338"（也接受裸码 "159338"）
            ktype_str: K_1M / K_5M / K_15M / K_30M / K_60M / K_DAY / K_WEEK / K_MON
            start_date: YYYY-MM-DD，None 则按配置回溯
            end_date: YYYY-MM-DD，None 则今天
            incremental: 增量模式，从库中最新时间续
            prefer: 数据源，见 SOURCE_KEYS。"auto" 依次回退；
                    指定具体源时只用那一个，失败不静默换源（便于定位问题）

        Returns:
            落库条数。失败/无数据返回 0，原因写在 self.last_error
        """
        self.last_source = ""
        self.last_error = ""

        if ktype_str not in MIN_PERIOD_MAP and ktype_str not in DAY_PERIOD_MAP:
            self.last_error = f"不支持的K线类型: {ktype_str}"
            logger.error(self.last_error)
            return 0

        prefer = (prefer or "auto").lower()
        if prefer not in SOURCE_KEYS:
            self.last_error = f"未知数据源: {prefer}（可选 {'/'.join(SOURCE_KEYS)}）"
            logger.error(self.last_error)
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
        tries = 0
        for attempt in range(1, MAX_RETRIES + 1):
            tries = attempt
            try:
                df = self._fetch(bare, ktype_str, start_date, end_date,
                                 code_full=code, prefer=prefer)
                break
            except Exception as e:
                last_err = e
                if attempt >= MAX_RETRIES or not _is_retriable(e):
                    self.last_error = str(e)
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

        if df is None or df.empty:
            if last_err is not None:
                # 真的抛异常并重试到底了
                self.last_error = f"重试 {tries} 次仍失败: {last_err}"
                logger.error(f"[akshare] 重试耗尽: {code} {ktype_str} - {last_err}")
                self.db.log_download(code, "kline", ktype_str, start_date, end_date,
                                     0, "error", str(last_err))
                return 0

            # _fetch 已把每个源的失败/空原因写进 last_error，别覆盖它
            if not self.last_error:
                self.last_error = "数据源返回空（该周期无数据，或代码不存在/未上市）"
            logger.info(f"[akshare] 无数据: {code} {ktype_str} - {self.last_error}")
            self.db.log_download(code, "kline", ktype_str, start_date, end_date,
                                 0, "success", self.last_error)
            return 0

        saved = self.db.save_kline(code, ktype_str, df)
        self.db.log_download(code, "kline", ktype_str, start_date, end_date,
                             saved, "success")
        logger.info(f"[akshare] 下载完成: {code} {ktype_str} -> 共 {saved} 条")
        return saved

    # ─── 实际抓取 ───
    def _fetch(self, bare: str, ktype_str: str,
               start_date: str, end_date: str,
               code_full: str = "", prefer: str = "auto") -> Optional[pd.DataFrame]:
        """
        按 prefer 抓取。"auto" 时依次回退，指定源时只试那一个。

        每个源失败/空的原因都收集起来，最后写进 self.last_error，
        否则 GUI 只能看到「0 条」，没法判断是网络挡了还是本来就没数据。
        """
        notes = []
        retriable = False
        only = None if prefer == "auto" else prefer

        def _note(src, msg, exc=None):
            nonlocal retriable
            notes.append(f"{src}: {msg}")
            if exc is not None and _is_retriable(exc):
                retriable = True

        # 1) 东财直连（国内网络时最好，分钟线历史最全）
        if only in (None, "eastmoney"):
            if self._em is None:
                _note("东财", "客户端不可用")
            else:
                try:
                    df = self._em.get_kline(bare, ktype_str, start_date, end_date)
                    if df is not None and not df.empty:
                        self.last_source = "东财"
                        return self._normalize_em(df)
                    _note("东财", "无数据")
                    logger.debug(f"[东财] {bare} {ktype_str} 无数据，尝试下一个源")
                except Exception as e:
                    _note("东财", f"{type(e).__name__}: {e}", e)
                    logger.warning(
                        f"[东财] {bare} {ktype_str} 失败({type(e).__name__})，尝试下一个源")

        # 2) Yahoo（挂海外代理时这条通）
        if only in (None, "yahoo"):
            if self._yahoo is None:
                _note("Yahoo", "客户端不可用")
            else:
                try:
                    df = self._yahoo.get_kline(code_full, ktype_str, start_date, end_date)
                    if df is not None and not df.empty:
                        self.last_source = "Yahoo"
                        return df        # YahooClient 已按本项目 schema 返回
                    _note("Yahoo", "无数据")
                    logger.debug(f"[Yahoo] {bare} {ktype_str} 无数据，尝试下一个源")
                except Exception as e:
                    _note("Yahoo", f"{type(e).__name__}: {e}", e)
                    logger.warning(
                        f"[Yahoo] {bare} {ktype_str} 失败({type(e).__name__})，尝试下一个源")

        # 3) akshare（兜底，import 很慢，只在真正轮到它时加载）
        if only in (None, "akshare"):
            ak = _get_ak()
            if ak is None:
                _note("akshare", "未安装（pip install akshare）")
            else:
                try:
                    df = self._fetch_akshare(ak, bare, ktype_str,
                                             start_date, end_date)
                    if df is not None and not df.empty:
                        self.last_source = "akshare"
                        return df
                    _note("akshare", "无数据")
                except Exception as e:
                    _note("akshare", f"{type(e).__name__}: {e}", e)

        self.last_error = "；".join(notes) if notes else "所有数据源均无数据"

        # 所有源都没拿到，且其中有连接被重置这类瞬时错误 -> 抛给外层退避重试。
        # 注意要等所有源都试完再抛：auto 模式下东财常年 ProxyError，
        # 先抛的话每次都要空退避 4 轮才轮得到 Yahoo。
        if retriable:
            raise ConnectionError(self.last_error)
        return None

    def _fetch_akshare(self, ak, bare: str, ktype_str: str,
                       start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """akshare 兜底路径"""
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
    def _normalize_em(df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """东财直连返回 -> 本项目 schema（列名已是英文，仅需补齐）"""
        if df is None or df.empty:
            return None
        df = df.copy()
        if "last_close" not in df.columns:
            df["last_close"] = df["close"].shift(1)
        if "pe_ratio" not in df.columns:
            df["pe_ratio"] = None
        if "turnover_rate" not in df.columns:
            df["turnover_rate"] = None
        if "change_rate" not in df.columns:
            df["change_rate"] = None

        keep = ["time_key", "open", "high", "low", "close", "volume",
                "turnover", "pe_ratio", "turnover_rate", "change_rate", "last_close"]
        return df[[c for c in keep if c in df.columns]].reset_index(drop=True)

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
                           incremental: bool = True, prefer: str = "auto") -> dict:
        if ktypes is None:
            ktypes = self.config.get("kline", "default_types",
                                     default=["K_5M", "K_DAY"])
        return {kt: self.download_history(code, kt, incremental=incremental,
                                          prefer=prefer)
                for kt in ktypes}

    def batch_download(self, codes: List[str], ktypes: List[str] = None,
                       incremental: bool = True, prefer: str = "auto") -> dict:
        results = {}
        for code in codes:
            logger.info(f"[akshare] ===== 批量下载: {code} =====")
            results[code] = self.download_all_types(code, ktypes, incremental,
                                                    prefer=prefer)
        return results


class MarketRouter:
    """
    按市场路由到合适的数据源。

      A 股 (SH./SZ.)  -> AkshareSource   免费，无权限限制
      港股/美股       -> KlineDownloader Futu OpenAPI

    也可以用 prefer 手动指定，绕过自动路由：
      "auto"      按市场自动选（默认）
      "futu"      强制走 Futu（A 股账号无行情权限时会失败，属预期）
      其余 key    强制走 A 股源里的某一个，见 SOURCE_OPTIONS
    """

    # GUI 下拉用：在 A 股源之上补一个「Futu」
    SOURCE_OPTIONS = SOURCE_OPTIONS + [
        ("futu", "Futu OpenAPI", "港股/美股走这条；A 股需要账号有对应行情权限"),
    ]
    SOURCE_KEYS = [k for k, _, _ in SOURCE_OPTIONS]
    SOURCE_LABELS = {k: n for k, n, _ in SOURCE_OPTIONS}

    def __init__(self, futu_downloader=None, akshare_source=None):
        self.futu = futu_downloader
        self.akshare = akshare_source
        self.last_source = ""
        self.last_error = ""

    def pick(self, code: str, prefer: str = "auto"):
        """返回该标的应使用的下载器，无可用源时返回 None"""
        prefer = (prefer or "auto").lower()
        if prefer == "futu":
            return self.futu
        if prefer != "auto":
            # 指定了具体的 A 股源
            return self.akshare
        if is_a_share(code) and self.akshare is not None:
            return self.akshare
        return self.futu

    def source_name(self, code: str, prefer: str = "auto") -> str:
        src = self.pick(code, prefer)
        if src is None:
            return "无可用数据源"
        if src is self.akshare:
            prefer = (prefer or "auto").lower()
            return "A股源(自动)" if prefer == "auto" else f"A股源({SOURCE_LABELS.get(prefer, prefer)})"
        return "Futu OpenAPI"

    def requires_futu(self, code: str, prefer: str = "auto") -> bool:
        """这次下载是否需要 OpenD 已连接"""
        return self.pick(code, prefer) is self.futu

    def download_history(self, code: str, ktype_str: str,
                         start_date: str = None, end_date: str = None,
                         incremental: bool = True, prefer: str = "auto") -> int:
        self.last_source = ""
        self.last_error = ""

        prefer = (prefer or "auto").lower()
        src = self.pick(code, prefer)
        if src is None:
            self.last_error = (
                "Futu 未连接（侧栏 → 连接管理）" if prefer == "futu"
                else f"无可用数据源: {code}")
            logger.error(f"无可用数据源: {code} (prefer={prefer})")
            return 0

        if src is self.akshare:
            n = src.download_history(code, ktype_str, start_date, end_date,
                                     incremental, prefer=prefer)
        else:
            # Futu 侧不认 prefer，直接调
            n = src.download_history(code, ktype_str, start_date, end_date,
                                     incremental)

        self.last_source = getattr(src, "last_source", "") or self.source_name(code, prefer)
        self.last_error = getattr(src, "last_error", "")
        return n

    def download_all_types(self, code: str, ktypes: List[str] = None,
                           incremental: bool = True, prefer: str = "auto") -> dict:
        return {kt: self.download_history(code, kt, incremental=incremental,
                                          prefer=prefer)
                for kt in (ktypes or ["K_DAY"])}

    def batch_download(self, codes: List[str], ktypes: List[str] = None,
                       incremental: bool = True, prefer: str = "auto") -> dict:
        return {code: self.download_all_types(code, ktypes, incremental, prefer)
                for code in codes}
