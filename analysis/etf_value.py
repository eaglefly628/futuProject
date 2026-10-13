"""交易价格相对参考净值的偏离，统一为正溢价、负折价。"""
import math


def number(value, positive=False):
    try:
        value = float(value)
        if math.isfinite(value) and (not positive or value > 0):
            return value
    except (TypeError, ValueError):
        pass
    return None


def deviation(price, reference):
    price, reference = number(price, True), number(reference, True)
    return (price / reference - 1) * 100 if price and reference else None


def value_metrics(row):
    price, iopv = number(row.get("price"), True), number(row.get("iopv"), True)
    bid, ask = number(row.get("bid"), True), number(row.get("ask"), True)
    premium = deviation(price, iopv)
    ask_premium = deviation(ask, iopv)
    if bid and ask and ask < bid:
        ask_premium = None
    spread = ((ask - bid) / ((ask + bid) / 2) * 100
              if bid and ask and ask >= bid else None)
    # 正式净值必须与价格属于同一交易日，不能用昨日净值制造假折价。
    nav_premium = (deviation(price, row.get("nav"))
                   if row.get("nav_date") and row.get("nav_date") == row.get("market_date") else None)
    return {"premium_pct": premium, "ask_premium_pct": ask_premium,
            "spread_pct": spread, "nav_premium_pct": nav_premium}
