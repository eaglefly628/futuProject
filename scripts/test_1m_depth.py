#!/usr/bin/env python3
"""
探测各数据源 1 分钟线的实际历史深度

    python -m scripts.test_1m_depth
    python -m scripts.test_1m_depth SZ.159338
"""
import sys


def main():
    code = sys.argv[1] if len(sys.argv) > 1 else "SZ.159338"
    print("=" * 62)
    print(f"  1分钟线历史深度探测: {code}")
    print("=" * 62)

    import pandas as pd

    # ── 东财 ──
    try:
        from downloaders.eastmoney import EastmoneyClient
        c = EastmoneyClient()
        secid = __import__("downloaders.eastmoney", fromlist=["to_secid"]).to_secid(code)

        for label, fn in (
            ("kline klt=1", lambda: c._get_kline(secid, "1", "1")),
            ("trends2 ndays=5", lambda: c._get_trends(secid, ndays=5)),
            ("trends2 ndays=10", lambda: c._get_trends(secid, ndays=10)),
        ):
            try:
                df = fn()
                if df is None or df.empty:
                    print(f"  东财 {label:18s} 空")
                else:
                    t = pd.to_datetime(df["time_key"])
                    days = t.dt.date.nunique()
                    print(f"  东财 {label:18s} {len(df):6,d} 条 · {days} 个交易日 · "
                          f"{df['time_key'].iloc[0][:16]} ~ {df['time_key'].iloc[-1][:16]}")
            except Exception as e:
                print(f"  东财 {label:18s} {type(e).__name__}: {str(e)[:50]}")
        c.close()
    except Exception as e:
        print(f"  东财 不可用: {e}")

    # ── Yahoo ──
    try:
        from downloaders.yahoo import YahooClient
        y = YahooClient()
        df = y.get_kline(code, "K_1M")
        if df is None or df.empty:
            print(f"  Yahoo {'1m range=7d':18s} 空")
        else:
            t = pd.to_datetime(df["time_key"])
            days = t.dt.date.nunique()
            print(f"  Yahoo {'1m range=7d':18s} {len(df):6,d} 条 · {days} 个交易日 · "
                  f"{df['time_key'].iloc[0][:16]} ~ {df['time_key'].iloc[-1][:16]}")
        y.close()
    except Exception as e:
        print(f"  Yahoo 不可用: {e}")

    print()
    print("  说明: 1分钟线各家都只给很短的历史，做中长期分析建议用 5分钟以上")
    return 0


if __name__ == "__main__":
    sys.exit(main())
