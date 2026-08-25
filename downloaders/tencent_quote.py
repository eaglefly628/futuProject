"""
腾讯财经实时行情接口

免费、无需注册、无频率限制（合理使用）。
返回最新价、涨跌、买卖五档、成交量额、换手率、市盈率、量比等。

接口:  https://qt.gtimg.cn/q=sz159338,sh512050
返回:  v_sz159338="51~中证A500ETF~159338~1.224~...";

注意：腾讯是国内服务，本机挂海外代理时可能不可达，
因此默认绕过系统代理直连（与东财同样的处理）。
"""
import random
import re
import time
from typing import Optional, List, Dict

import requests
from loguru import logger

QUOTE_URL = "https://qt.gtimg.cn/q="

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# 腾讯返回字段的位置（~ 分隔）
F_NAME, F_CODE, F_PRICE, F_PREV_CLOSE, F_OPEN = 1, 2, 3, 4, 5
F_VOLUME = 6                 # 成交量(手)
F_BID1, F_BID1_VOL = 9, 10   # 买一价 / 量，之后每 2 个一档
F_ASK1, F_ASK1_VOL = 19, 20  # 卖一价 / 量
F_TIME = 30                  # YYYYMMDDHHMMSS
F_CHANGE, F_CHANGE_PCT = 31, 32
F_HIGH, F_LOW = 33, 34
F_TURNOVER = 37              # 成交额(万元)
F_TURNOVER_RATE = 38
F_PE = 39
F_AMPLITUDE = 43
F_CIRC_MV, F_TOTAL_MV = 44, 45   # 流通市值 / 总市值（亿元）
F_PB = 46
F_LIMIT_UP, F_LIMIT_DOWN = 47, 48
F_VOLUME_RATIO = 49

_LINE_RE = re.compile(r'v_([a-zA-Z]{2}\d{6})="([^"]*)"')


def to_tencent_code(code: str) -> str:
    """SZ.159338 -> sz159338 ；SH.512050 -> sh512050"""
    c = (code or "").strip().upper()
    if "." in c:
        prefix, bare = c.split(".", 1)
        if prefix in ("SH", "SZ"):
            return f"{prefix.lower()}{bare}"
        if prefix == "HK":
            return f"hk{bare}"
        if prefix == "US":
            return f"us{bare}"
        c = bare
    if c.isdigit() and len(c) == 6:
        return f"{'sh' if c.startswith(('5', '6', '9')) else 'sz'}{c}"
    return c.lower()


def _f(parts: List[str], idx: int, default=None) -> Optional[float]:
    """按位置安全取浮点值"""
    try:
        v = parts[idx].strip()
        return float(v) if v else default
    except (IndexError, ValueError):
        return default


class TencentQuoteClient:
    """腾讯实时行情客户端"""

    def __init__(self, timeout: int = 8, use_proxy: Optional[bool] = None):
        self.timeout = timeout
        self._use_proxy = use_proxy
        self._proxy_mode = "direct" if use_proxy in (None, False) else "proxy"
        self._session = self._make_session(self._proxy_mode == "proxy")

    def _make_session(self, trust_env: bool) -> requests.Session:
        s = requests.Session()
        s.trust_env = trust_env
        if not trust_env:
            s.proxies = {"http": None, "https": None}
        s.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": "https://finance.qq.com/",
        })
        return s

    def _switch_proxy_mode(self) -> bool:
        if self._use_proxy is not None:
            return False
        self._proxy_mode = "proxy" if self._proxy_mode == "direct" else "direct"
        self._session = self._make_session(self._proxy_mode == "proxy")
        logger.info(f"腾讯行情切换为 {self._proxy_mode} 模式重试")
        return True

    # ═══════════════════════════════════════
    def get_quotes(self, codes: List[str]) -> Dict[str, dict]:
        """
        批量拉取实时行情。一次请求可查多只，腾讯对此没有明显限制。

        Returns:
            {原始代码: 行情字典}
        """
        if not codes:
            return {}

        # 原始代码 <-> 腾讯代码 的映射，便于回填
        mapping = {to_tencent_code(c): c for c in codes}
        url = QUOTE_URL + ",".join(mapping.keys())

        text = None
        for _ in range(2):
            try:
                self._session.headers["User-Agent"] = random.choice(USER_AGENTS)
                resp = self._session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                # 腾讯返回 GBK 编码
                resp.encoding = "gbk"
                text = resp.text
                break
            except (requests.exceptions.ProxyError,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.SSLError) as e:
                if not self._switch_proxy_mode():
                    raise
                logger.debug(f"腾讯行情请求失败({type(e).__name__})，换模式重试")

        if text is None:
            raise RuntimeError("腾讯行情请求失败")

        result = {}
        for tc_code, payload in _LINE_RE.findall(text):
            orig = mapping.get(tc_code, tc_code)
            parts = payload.split("~")
            if len(parts) < 40:
                continue

            price = _f(parts, F_PRICE)
            if not price:
                continue

            # 成交额腾讯给的是万元，统一成元
            turnover = _f(parts, F_TURNOVER)
            if turnover is not None:
                turnover *= 10000
            # 市值给的是亿元
            total_mv = _f(parts, F_TOTAL_MV)
            circ_mv = _f(parts, F_CIRC_MV)

            ts = parts[F_TIME].strip() if len(parts) > F_TIME else ""
            if len(ts) == 14:
                ts = (f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} "
                      f"{ts[8:10]}:{ts[10:12]}:{ts[12:14]}")

            # 买卖五档
            bids, asks = [], []
            for i in range(5):
                bp = _f(parts, F_BID1 + i * 2)
                bv = _f(parts, F_BID1_VOL + i * 2)
                ap = _f(parts, F_ASK1 + i * 2)
                av = _f(parts, F_ASK1_VOL + i * 2)
                if bp:
                    bids.append((bp, bv))
                if ap:
                    asks.append((ap, av))

            result[orig] = {
                "code": orig,
                "name": parts[F_NAME].strip(),
                "price": price,
                "prev_close": _f(parts, F_PREV_CLOSE),
                "open": _f(parts, F_OPEN),
                "high": _f(parts, F_HIGH),
                "low": _f(parts, F_LOW),
                "change": _f(parts, F_CHANGE),
                "change_rate": _f(parts, F_CHANGE_PCT),
                "volume": _f(parts, F_VOLUME),          # 手
                "turnover": turnover,                    # 元
                "turnover_rate": _f(parts, F_TURNOVER_RATE),
                "amplitude": _f(parts, F_AMPLITUDE),
                "volume_ratio": _f(parts, F_VOLUME_RATIO),
                "pe_ratio": _f(parts, F_PE),
                "pb_ratio": _f(parts, F_PB),
                "total_mv": total_mv * 1e8 if total_mv else None,
                "circ_mv": circ_mv * 1e8 if circ_mv else None,
                "limit_up": _f(parts, F_LIMIT_UP),
                "limit_down": _f(parts, F_LIMIT_DOWN),
                "bid": bids[0][0] if bids else None,
                "ask": asks[0][0] if asks else None,
                "bid_vol": bids[0][1] if bids else None,
                "ask_vol": asks[0][1] if asks else None,
                "bids": bids,
                "asks": asks,
                "time": ts,
                "source": "腾讯",
            }

        return result

    def get_quote(self, code: str) -> Optional[dict]:
        return self.get_quotes([code]).get(code)

    def close(self):
        try:
            self._session.close()
        except Exception:
            pass
