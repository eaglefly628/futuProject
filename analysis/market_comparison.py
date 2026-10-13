"""同日期、同窗口的收益对比；缺失数据不填零。"""
import pandas as pd
import numpy as np


def product_category(code, name):
    """按当前行情简称分组；具体策略以基金文件为准。"""
    from core.market_universe import BENCHMARKS
    if code in {c for c, _ in BENCHMARKS}:
        return "指数"
    if "增强" in name:
        return "增强"
    if "红利" in name or "低波" in name:
        return "红利低波"
    return "普通A500"


def rank_comparisons(rows, mode="desc"):
    """有效数据先排序，缺失项始终置后。"""
    valid = [row for row in rows if row[2] is not None]
    missing = [row for row in rows if row[2] is None]
    key = lambda row: abs(row[2]["excess"]) if mode == "abs" else row[2]["excess"]
    return sorted(valid, key=key, reverse=mode != "asc") + missing


def close_series(frame):
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    dates = pd.to_datetime(frame["time_key"], errors="coerce").dt.normalize()
    prices = pd.to_numeric(frame["close"], errors="coerce")
    result = pd.Series(prices.to_numpy(), index=dates)
    result = result[result.index.notna() & np.isfinite(result) & (result > 0)]
    return result[~result.index.duplicated(keep="last")].sort_index()


def compare_returns(asset, benchmark, sessions):
    left, right = close_series(asset), close_series(benchmark)
    if right.empty:
        return None
    # 采用基准最近 N 个交易日的固定端点，不能把停牌的旧数据当最新。
    dates = right.index[-(sessions + 1):]
    if len(dates) != sessions + 1 or not dates.isin(left.index).all():
        return None
    start, end = dates[0], dates[-1]
    asset_return = (left.loc[end] / left.loc[start] - 1) * 100
    index_return = (right.loc[end] / right.loc[start] - 1) * 100
    return {"return": float(asset_return), "benchmark_return": float(index_return),
            "excess": float(asset_return - index_return),
            "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")}


def normalized_curves(frames, sessions=60):
    series = {name: close_series(frame) for name, frame in frames.items()}
    series = {name: value for name, value in series.items() if not value.empty}
    if not series:
        return pd.DataFrame()
    aligned = pd.concat(series, axis=1, join="inner").tail(sessions + 1)
    if len(aligned) < 2:
        return pd.DataFrame()
    return aligned.divide(aligned.iloc[0]).multiply(100)
