"""
全市场标的清单

要下载「所有 A 股日线」，第一步得先知道「所有 A 股」是哪些。
本项目原来只有手工维护的监控列表，没有全市场清单。

清单来源按可用性排：
  1. 东财 clist 接口   一次几百只，翻页拿全，带名称和市场
  2. akshare           兜底，懒加载
  3. 本地 CSV          前两个都不通时的退路，见 load_csv()

拿到后写进 stock_meta 表，之后离线可用。
"""
import csv
import time
from typing import Dict, List, Optional

import pandas as pd
from loguru import logger

from downloaders.cancel import StopFn, ProgressFn, stopped, report

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"

# 东财板块筛选串。t 是板块类型，m 是市场（0=深 1=沪）
FS_A_SHARE = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
FS_ETF = "b:MK0021,b:MK0022,b:MK0023,b:MK0024"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}


def _norm(market_flag, bare: str) -> str:
    """东财 f13: 0=深 1=沪 -> 本项目的 SZ./SH. 前缀"""
    prefix = "SH" if str(market_flag) == "1" else "SZ"
    return f"{prefix}.{bare}"


class UniverseFetcher:
    """全市场清单获取"""

    def __init__(self, timeout: int = 15, min_gap: float = 0.4):
        self.timeout = timeout
        self.min_gap = min_gap
        self._last = 0.0
        self.last_source = ""
        self.last_error = ""

    def _pace(self):
        gap = self.min_gap - (time.time() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.time()

    # ─── 东财 ───
    def _fetch_eastmoney(self, fs: str, should_stop: StopFn = None,
                         on_progress: ProgressFn = None) -> List[dict]:
        import requests
        s = requests.Session()
        # 和项目其它 HTTP 客户端一致：默认绕过系统代理
        s.trust_env = False
        s.proxies = {"http": None, "https": None}
        s.headers.update(BROWSER_HEADERS)

        out, page, page_size = [], 1, 100
        try:
            while True:
                if stopped(should_stop):
                    break
                self._pace()
                r = s.get(CLIST_URL, timeout=self.timeout, params={
                    "pn": page, "pz": page_size, "po": "0", "np": "1",
                    "fltt": "2", "invt": "2", "fid": "f12",
                    "fs": fs, "fields": "f12,f13,f14",
                })
                r.raise_for_status()
                data = (r.json() or {}).get("data") or {}
                diff = data.get("diff") or []
                if isinstance(diff, dict):        # 某些参数下返回 dict
                    diff = list(diff.values())
                if not diff:
                    break

                for it in diff:
                    bare, mk, name = it.get("f12"), it.get("f13"), it.get("f14")
                    if not bare:
                        continue
                    out.append({"code": _norm(mk, str(bare)),
                                "name": name or "", "market": "SH" if str(mk) == "1" else "SZ"})

                report(on_progress, f"  已取 {len(out)} 只（第 {page} 页）")
                total = int(data.get("total") or 0)
                if total and len(out) >= total:
                    break
                if len(diff) < page_size:
                    break
                page += 1
        finally:
            s.close()
        return out

    # ─── akshare 兜底 ───
    def _fetch_akshare(self) -> List[dict]:
        from downloaders.akshare_source import _get_ak
        ak = _get_ak()
        if ak is None:
            raise RuntimeError("akshare 未安装")
        df = ak.stock_zh_a_spot_em()
        out = []
        for _, row in df.iterrows():
            bare = str(row.get("代码") or "").strip()
            if not bare or not bare.isdigit():
                continue
            prefix = "SH" if bare[0] in ("6", "9") else "SZ"
            out.append({"code": f"{prefix}.{bare}",
                        "name": str(row.get("名称") or ""), "market": prefix})
        return out

    # ─── 对外 ───
    def fetch(self, include_etf: bool = True, should_stop: StopFn = None,
              on_progress: ProgressFn = None) -> List[dict]:
        """
        取全市场清单。失败时抛异常，原因在 self.last_error。

        Returns:
            [{"code": "SH.600519", "name": "贵州茅台", "market": "SH"}, ...]
        """
        self.last_source = ""
        self.last_error = ""
        notes = []

        # 1) 东财
        try:
            report(on_progress, "从东财取全市场清单…")
            rows = self._fetch_eastmoney(FS_A_SHARE, should_stop, on_progress)
            if include_etf and not stopped(should_stop):
                report(on_progress, "取 ETF 清单…")
                rows += self._fetch_eastmoney(FS_ETF, should_stop, on_progress)
            if rows:
                self.last_source = "东财"
                return _dedup(rows)
            notes.append("东财: 返回空")
        except Exception as e:
            notes.append(f"东财: {type(e).__name__}: {e}")
            logger.warning(f"[universe] 东财失败: {e}")

        if stopped(should_stop):
            self.last_error = "已停止"
            return []

        # 2) akshare
        try:
            report(on_progress, "改用 akshare（首次要加载依赖，较慢）…")
            rows = self._fetch_akshare()
            if rows:
                self.last_source = "akshare"
                return _dedup(rows)
            notes.append("akshare: 返回空")
        except Exception as e:
            notes.append(f"akshare: {type(e).__name__}: {e}")
            logger.warning(f"[universe] akshare 失败: {e}")

        self.last_error = "；".join(notes)
        raise RuntimeError(self.last_error)


def _dedup(rows: List[dict]) -> List[dict]:
    seen, out = set(), []
    for r in rows:
        if r["code"] in seen:
            continue
        seen.add(r["code"])
        out.append(r)
    return sorted(out, key=lambda r: r["code"])


# ═══════════════════════════════════════
#  本地 CSV —— 网络拿不到清单时的退路
# ═══════════════════════════════════════
def load_csv(path: str) -> List[dict]:
    """
    从 CSV 读清单。至少要有 code 列，可选 name。

    code 可以是 SH.600519 或裸码 600519（按首位数字判market）。
    """
    out = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw = (row.get("code") or row.get("代码") or "").strip()
            if not raw:
                continue
            code = normalize_code(raw)
            if code:
                out.append({"code": code,
                            "name": (row.get("name") or row.get("名称") or "").strip(),
                            "market": code.split(".")[0]})
    return _dedup(out)


def normalize_code(raw: str) -> Optional[str]:
    """600519 / sh600519 / SH.600519 -> SH.600519"""
    c = (raw or "").strip().upper().replace(" ", "")
    if not c:
        return None
    if "." in c:
        pre, bare = c.split(".", 1)
        if pre in ("SH", "SZ") and bare.isdigit():
            return f"{pre}.{bare}"
        c = bare
    if c.startswith(("SH", "SZ")) and c[2:].isdigit():
        return f"{c[:2]}.{c[2:]}"
    if c.isdigit() and len(c) == 6:
        # 沪市: 6xxxxx 股票 / 5xxxxx ETF基金 / 9xxxxx B股
        # 深市: 0xxxxx 3xxxxx 股票 / 1xxxxx ETF基金 / 2xxxxx B股
        # 北交所 4xxxxx 8xxxxx 归到 SZ —— 东财按深市市场号取数，这条能通
        return f"{'SH' if c[0] in ('5', '6', '9') else 'SZ'}.{c}"
    return None


# ═══════════════════════════════════════
#  落库
# ═══════════════════════════════════════
def save(db, rows: List[dict]) -> int:
    """写入 stock_meta（已存在则更新名称）"""
    if not rows:
        return 0
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.conn.cursor()
    cur.executemany(
        """INSERT INTO stock_meta (code, name, market, stock_type, last_updated)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(code) DO UPDATE SET
             name=excluded.name, market=excluded.market,
             stock_type=excluded.stock_type, last_updated=excluded.last_updated""",
        [(r["code"], r.get("name", ""), r.get("market", ""),
          _guess_type(r["code"]), now) for r in rows])
    db.conn.commit()
    return len(rows)


def _guess_type(code: str) -> str:
    """按代码段猜类型，够用即可"""
    bare = code.split(".")[-1]
    if bare.startswith(("51", "52", "56", "58", "15", "16", "18")):
        return "ETF"
    if bare.startswith(("68",)):
        return "STAR"       # 科创板
    if bare.startswith(("30",)):
        return "GEM"        # 创业板
    if bare.startswith(("8", "4")):
        return "BSE"        # 北交所
    return "STOCK"


def load(db, market: str = None, stock_type: str = None) -> List[dict]:
    """从 stock_meta 读清单"""
    sql = "SELECT code, name, market, stock_type FROM stock_meta WHERE 1=1"
    args = []
    if market:
        sql += " AND market = ?"
        args.append(market)
    if stock_type:
        sql += " AND stock_type = ?"
        args.append(stock_type)
    sql += " ORDER BY code"
    cur = db.conn.cursor()
    cur.execute(sql, args)
    return [{"code": r[0], "name": r[1], "market": r[2], "stock_type": r[3]}
            for r in cur.fetchall()]
