#!/usr/bin/env python3
"""
Futu OpenD 数据权限诊断

逐项测试到底哪些数据能拉，把真实的 API 返回码和错误信息打出来。

用法（OpenD 已登录后）:
    python -m scripts.diagnose
    python -m scripts.diagnose SZ.159338     指定标的
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent

DEFAULT_TESTS = [
    ("SZ.159338", "中证A500ETF(国泰) - 深"),
    ("SH.512050", "中证A500ETF(国泰) - 沪"),
    ("SH.000905", "中证500指数"),
    ("HK.00700", "腾讯控股 - 港股对照组"),
]

KTYPES = ["K_DAY", "K_60M", "K_15M", "K_5M", "K_1M"]

OK = "\033[92m✓\033[0m"
NO = "\033[91m✗\033[0m"
WARN = "\033[93m!\033[0m"


def main():
    from config import Config
    cfg = Config(str(PROJECT_ROOT / "config" / "default.yaml"))
    host = cfg.get("opend", "host", default="127.0.0.1")
    port = int(cfg.get("opend", "port", default=11111))

    print("=" * 66)
    print("  Futu OpenD 数据权限诊断")
    print(f"  目标: {host}:{port}")
    print("=" * 66)

    try:
        from futu import OpenQuoteContext, RET_OK, KLType, AuType, SubType
    except ImportError:
        print(f"{NO} futu-api 未安装:  pip install futu-api")
        return 1

    try:
        ctx = OpenQuoteContext(host=host, port=port)
    except Exception as e:
        print(f"{NO} 无法连接 OpenD: {e}")
        print("   请确认 OpenD 已启动并完成登录")
        return 1
    print(f"{OK} 已连接 OpenD\n")

    codes = [(sys.argv[1], "命令行指定")] if len(sys.argv) > 1 else DEFAULT_TESTS

    # ── 1. 全局状态 ──
    print("─" * 66)
    print("【1】OpenD 全局状态")
    print("─" * 66)
    try:
        ret, data = ctx.get_global_state()
        if ret == RET_OK:
            for k in ("market_sz", "market_sh", "market_hk", "market_us",
                      "quote_logined", "trd_logined"):
                if k in data:
                    print(f"    {k:16s}: {data[k]}")
        else:
            print(f"{NO} get_global_state 失败: {data}")
    except Exception as e:
        print(f"{NO} get_global_state 异常: {e}")

    # ── 2. 快照 ──
    print()
    print("─" * 66)
    print("【2】实时快照 get_market_snapshot")
    print("─" * 66)
    for code, desc in codes:
        try:
            ret, data = ctx.get_market_snapshot([code])
            if ret == RET_OK and data is not None and not data.empty:
                row = data.iloc[0]
                name = row.get("name", "")
                price = row.get("last_price", "?")
                print(f"{OK} {code:14s} {desc}")
                print(f"     名称={name}  最新价={price}")
            else:
                print(f"{NO} {code:14s} {desc}")
                print(f"     {data}")
        except Exception as e:
            print(f"{NO} {code:14s} 异常: {e}")

    # ── 3. 历史K线 ──
    print()
    print("─" * 66)
    print("【3】历史K线 request_history_kline（重点）")
    print("─" * 66)
    ktype_map = {
        "K_DAY": KLType.K_DAY, "K_60M": KLType.K_60M,
        "K_15M": KLType.K_15M, "K_5M": KLType.K_5M, "K_1M": KLType.K_1M,
    }
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    results = {}
    for code, desc in codes:
        print(f"\n  {code}  ({desc})")
        results[code] = {}
        for kt in KTYPES:
            try:
                ret, data, _ = ctx.request_history_kline(
                    code=code, ktype=ktype_map[kt],
                    start=start, end=end, max_count=10, autype=AuType.QFQ)
                if ret == RET_OK and data is not None and not data.empty:
                    first = data["time_key"].iloc[0]
                    last = data["time_key"].iloc[-1]
                    print(f"    {OK} {kt:7s} {len(data):3d}条  {first} ~ {last}")
                    results[code][kt] = len(data)
                else:
                    print(f"    {NO} {kt:7s} {data}")
                    results[code][kt] = 0
            except Exception as e:
                print(f"    {NO} {kt:7s} 异常: {e}")
                results[code][kt] = 0

    # ── 4. 订阅 ──
    print()
    print("─" * 66)
    print("【4】实时订阅 subscribe")
    print("─" * 66)
    for code, desc in codes[:2]:
        try:
            ret, data = ctx.subscribe([code], [SubType.QUOTE])
            if ret == RET_OK:
                print(f"{OK} {code:14s} 订阅成功")
                ctx.unsubscribe([code], [SubType.QUOTE])
            else:
                print(f"{NO} {code:14s} {data}")
        except Exception as e:
            print(f"{NO} {code:14s} 异常: {e}")

    # ── 汇总 ──
    print()
    print("=" * 66)
    print("  结论")
    print("=" * 66)
    any_ok = False
    for code, desc in codes:
        r = results.get(code, {})
        ok_kt = [k for k, v in r.items() if v > 0]
        if ok_kt:
            any_ok = True
            print(f"{OK} {code:14s} 可拉取: {', '.join(ok_kt)}")
        else:
            print(f"{NO} {code:14s} 全部周期无数据")

    print()
    if any_ok:
        print("  → 有数据可拉，直接在 GUI「A500中心 → 数据采集」开始采集")
    else:
        print("  → 全部失败。把上面的完整输出发出来，据此定位原因")
        print("     （权限 / 代码格式 / OpenD 登录状态）")

    ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
