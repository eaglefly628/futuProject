#!/usr/bin/env python3
"""
东财直连快速测试 —— 不启动 GUI，直接验证能不能拉到数据

    python -m scripts.test_em
    python -m scripts.test_em SZ.159338
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

OK = "\033[92m✓\033[0m"
NO = "\033[91m✗\033[0m"


def main():
    code = sys.argv[1] if len(sys.argv) > 1 else "SZ.159338"

    print("=" * 62)
    print(f"  东财直连测试: {code}")
    print("=" * 62)

    from downloaders.eastmoney import EastmoneyClient, to_secid

    try:
        secid = to_secid(code)
        print(f"  secid = {secid}\n")
    except Exception as e:
        print(f"{NO} 代码解析失败: {e}")
        return 1

    client = EastmoneyClient()
    ktypes = ["K_DAY", "K_60M", "K_30M", "K_15M", "K_5M", "K_1M"]
    ok_count = 0

    for kt in ktypes:
        try:
            df = client.get_kline(code, kt,
                                  start_date="2026-01-01", end_date="2026-12-31")
            if df is None or df.empty:
                print(f"{NO} {kt:7s} 无数据")
                continue
            ok_count += 1
            print(f"{OK} {kt:7s} {len(df):6,d} 条   "
                  f"{df['time_key'].iloc[0]}  ~  {df['time_key'].iloc[-1]}")
            if kt == "K_DAY":
                last = df.iloc[-1]
                print(f"          最新: 开{last['open']:.3f} 高{last['high']:.3f} "
                      f"低{last['low']:.3f} 收{last['close']:.3f} "
                      f"量{last['volume']:,.0f}")
        except Exception as e:
            print(f"{NO} {kt:7s} {type(e).__name__}: {str(e)[:70]}")

    client.close()

    print()
    print("=" * 62)
    if ok_count == len(ktypes):
        print(f"  {OK} 全部 {ok_count} 个周期正常")
    elif ok_count:
        print(f"  {ok_count}/{len(ktypes)} 个周期可用")
    else:
        print(f"  {NO} 全部失败 —— 把输出发出来定位")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
