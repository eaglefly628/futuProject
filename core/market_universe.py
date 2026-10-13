"""A500 场内 ETF 名单及指数基准；本地缓存支持断网启动。"""
import json
from pathlib import Path

from downloaders.eastmoney import EastmoneyClient

BENCHMARKS = [
    ("SH.000001", "上证综指"),
    ("SZ.399001", "深证成指"),
    ("SH.000300", "沪深300"),
    ("SH.000510", "中证A500"),
]
FALLBACK_ETFS = [("SH.560530", "中证A500ETF摩根"),
                 ("SZ.159338", "中证A500ETF国泰")]


def is_plain_a500(name):
    """普通中证 A500 ETF，排除衍生策略和联接基金。"""
    name = str(name).upper()
    excluded = ("增强", "红利", "低波", "等权", "ESG", "成长", "价值",
                "动量", "质量", "优选", "精选", "杠杆", "反向", "联接")
    return "A500" in name and "ETF" in name and not any(word in name for word in excluded)


def filter_a500(rows):
    found = {}
    for row in rows:
        bare, name = str(row.get("f12", "")), str(row.get("f14", ""))
        market = str(row.get("f13", ""))
        if (is_plain_a500(name) and
                bare.isdigit() and len(bare) == 6 and market in ("0", "1")):
            found[f"{'SH' if market == '1' else 'SZ'}.{bare}"] = name
    return sorted(found.items())


def discover_a500():
    """分页扫描 ETF 市场，避免第一页截断遗漏标的。"""
    client = EastmoneyClient(timeout=8, min_gap=0.3)
    rows = []
    try:
        for page in range(1, 101):
            payload = client._get("https://push2delay.eastmoney.com/api/qt/clist/get", {
                "pn": page, "pz": 100, "po": 1, "np": 1,
                "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": 2,
                "invt": 2, "fid": "f12", "fields": "f12,f13,f14",
                "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024,b:MK0827",
            })
            data = payload.get("data") or {}
            batch = data.get("diff") or []
            if isinstance(batch, dict):
                batch = list(batch.values())
            if not batch:
                raise RuntimeError("ETF 名单返回不完整，保留上次名单")
            if int(data.get("total", 0)) <= 0:
                raise RuntimeError("ETF 名单缺少总数，保留上次名单")
            rows.extend(batch)
            if len(rows) >= int(data.get("total", 0)):
                result = filter_a500(rows)
                if not result:
                    raise RuntimeError("ETF 名单中未找到 A500")
                return result
        raise RuntimeError("ETF 名单超过分页上限，保留上次名单")
    finally:
        client._session.close()


def load_universe(path):
    for candidate in (Path(path), Path(__file__).resolve().parents[1] / "config" / "a500_universe.json"):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            items = [(str(c), str(n)) for c, n in data["etfs"] if is_plain_a500(n)]
            if items:
                return items
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return list(FALLBACK_ETFS)


def save_universe(path, items):
    items = [(c, n) for c, n in items if is_plain_a500(n)]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"etfs": items}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
