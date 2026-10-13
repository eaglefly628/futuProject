"""采集全部普通 A500 ETF 的价值偏离信息并输出快照。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from analysis.etf_value import value_metrics
from core.market_universe import load_universe
from downloaders.etf_value import fetch_value_snapshot, fetch_fund_references


def export_value_csv(rows, path):
    table = pd.DataFrame(rows.values()).sort_values("ask_premium_pct", na_position="last")
    labels = {"code": "代码", "name": "名称", "price": "成交价", "iopv": "参考净值IOPV",
              "premium_pct": "成交价折溢价(%)", "bid": "买一价", "ask": "卖一价",
              "ask_premium_pct": "卖一价折溢价(%)", "spread_pct": "买卖价差(%)",
              "turnover": "成交额(元)", "volume_lots": "成交量(手)",
              "nav": "最近正式净值", "nav_date": "正式净值日期",
              "management_fee_pct": "管理费(%每年)", "custody_fee_pct": "托管费(%每年)",
              "fee_verified": "费率是否官方核验", "fee_source_url": "费率来源",
              "nav_source_url": "净值来源", "quote_time": "行情源更新时间",
              "market_date": "源数据日期", "iopv_time": "IOPV独立时间(未提供)",
              "fetched_at": "获取时间", "market_source_url": "行情来源"}
    table.round(6).rename(columns=labels).to_csv(path, index=False, encoding="utf-8-sig")


def main():
    root = Path(__file__).resolve().parents[1]
    items = load_universe(root / "data" / "a500_universe.json")
    market = fetch_value_snapshot(items)
    references = fetch_fund_references(items)
    reference_path = root / "data" / "reports" / "a500_fund_references.json"
    try:
        cached = json.loads(reference_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    for code, row in references.items():
        if row.get("nav") is None:
            row.pop("nav", None)
            row.pop("nav_date", None)
        else:
            cached.setdefault(code, {}).pop("nav_error", None)
        cached.setdefault(code, {}).update(row)
    references = cached
    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    for code, row in market.items():
        row.update(references.get(code, {}), fetched_at=now)
        row.update(value_metrics(row))
    directory = root / "data" / "reports"
    directory.mkdir(exist_ok=True)
    reference_path.write_text(json.dumps(references, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "a500_value_snapshot.json").write_text(
        json.dumps({"fetched_at": now, "rows": market}, ensure_ascii=False, indent=2), encoding="utf-8")
    table = pd.DataFrame(market.values()).sort_values("premium_pct", na_position="last")
    export_value_csv(market, directory / "a500_value_snapshot.csv")
    columns = ["code", "name", "price", "iopv", "premium_pct", "ask_premium_pct",
               "spread_pct", "nav", "nav_date", "management_fee_pct", "custody_fee_pct"]
    print(table[columns].round(4).to_string(index=False))
    print("IOPV 未提供独立时间戳，盘后快照不能作为即时买入信号。")


if __name__ == "__main__":
    main()
