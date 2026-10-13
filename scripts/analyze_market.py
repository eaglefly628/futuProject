"""导出普通 A500 ETF 相对四个指数的收益排名；指数不参与基金排名。"""
import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd

from analysis.market_comparison import compare_returns, product_category
from core.market_universe import BENCHMARKS, load_universe, is_plain_a500


def analyze(db_path, items, sessions):
    items = [(code, name) for code, name in items if is_plain_a500(name)]
    with sqlite3.connect(db_path) as conn:
        frames = {code: pd.read_sql_query(
            "SELECT time_key, close FROM kline WHERE code=? AND ktype='K_DAY' ORDER BY time_key",
            conn, params=(code,)) for code, _ in items + BENCHMARKS}
    rows = []
    for code, name in items:
        row = {"代码": code, "名称": name, "类型": product_category(code, name)}
        for benchmark_code, benchmark_name in BENCHMARKS:
            result = compare_returns(frames[code], frames[benchmark_code], sessions)
            row[f"相对{benchmark_name}(百分点)"] = result["excess"] if result else None
            if benchmark_code == "SH.000510":
                row.update({"窗口收益(%)": result["return"] if result else None,
                            "比较开始": result["start"] if result else None,
                            "比较结束": result["end"] if result else None})
        rows.append(row)
    table = pd.DataFrame(rows)
    for _, name in BENCHMARKS:
        table[f"{name}排名"] = table[f"相对{name}(百分点)"].rank(
            method="min", ascending=False).astype("Int64")
    return table.sort_values("相对中证A500(百分点)", ascending=False, na_position="last")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, choices=(1, 5, 20, 60), default=20)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    db_path = root / "data" / "futu_quant.db"
    items = load_universe(root / "data" / "a500_universe.json")
    table = analyze(db_path, items, args.days)
    output = root / "data" / "reports"
    output.mkdir(exist_ok=True)
    filename = output / f"a500_ranking_{args.days}d.csv"
    table.round(4).to_csv(filename, index=False, encoding="utf-8-sig")
    print(table.round(2).to_string(index=False))
    valid = table[table["类型"] != "指数"].dropna(subset=["窗口收益(%)"])
    groups = []
    for kind, group in valid.groupby("类型"):
        groups.append({"type": kind, "count": len(group),
                       "up": int((group["窗口收益(%)"] > 0).sum()),
                       "down": int((group["窗口收益(%)"] < 0).sum()),
                       "mean_return": round(float(group["窗口收益(%)"].mean()), 2),
                       "mean_excess": round(float(group["相对中证A500(百分点)"].mean()), 2)})
    print(json.dumps({"file": str(filename), "etfs": len(valid), "groups": groups}, ensure_ascii=False))


if __name__ == "__main__":
    main()
