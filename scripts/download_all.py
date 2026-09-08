"""
全市场 A 股日线下载

  python -m scripts.download_all --list-only          # 只拉清单，看有多少只
  python -m scripts.download_all                      # 下载全部（可中断，可续跑）
  python -m scripts.download_all --type ETF           # 只下 ETF
  python -m scripts.download_all --source yahoo       # 指定数据源
  python -m scripts.download_all --csv codes.csv      # 用自己的清单

断点续传：已经有数据的标的默认跳过，Ctrl+C 之后直接重跑即可接着下。
库里已有数据的会走增量，只补最新那段。
"""
import argparse
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

_STOP = {"flag": False}


def _install_sigint():
    """Ctrl+C 优雅停止：收尾当前标的再退，不留半截数据"""
    def handler(signum, frame):
        if _STOP["flag"]:
            print("\n再次收到中断，直接退出。")
            sys.exit(130)
        _STOP["flag"] = True
        print("\n\n收到中断，正在收尾当前标的… （再按一次强制退出）")
    signal.signal(signal.SIGINT, handler)


def _fmt_eta(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:
        return "--"
    s = int(seconds)
    if s < 60:
        return f"{s}秒"
    if s < 3600:
        return f"{s//60}分{s%60}秒"
    return f"{s//3600}小时{(s%3600)//60}分"


def main():
    ap = argparse.ArgumentParser(description="全市场 A 股日线下载")
    ap.add_argument("--source", default="auto",
                    help="数据源: auto/eastmoney/yahoo/akshare（默认 auto）")
    ap.add_argument("--type", default=None,
                    help="只下某类: STOCK/ETF/GEM/STAR/BSE")
    ap.add_argument("--market", default=None, help="只下某市场: SH/SZ")
    ap.add_argument("--include-bse", action="store_true",
                    help="包含北交所（默认排除：Yahoo 拿不到，只有东财能拿）")
    ap.add_argument("--csv", default=None, help="用本地 CSV 清单，需含 code 列")
    ap.add_argument("--limit", type=int, default=0, help="最多下载几只（调试用）")
    ap.add_argument("--start", default=None, help="起始日期，默认取全部历史")
    ap.add_argument("--refresh-list", action="store_true", help="强制重新拉清单")
    ap.add_argument("--list-only", action="store_true", help="只拉清单，不下载")
    ap.add_argument("--redownload", action="store_true",
                    help="已有数据的也重下（默认跳过）")
    ap.add_argument("--db", default=None, help="指定数据库路径")
    args = ap.parse_args()

    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    from config import Config
    from storage.database import Database
    from downloaders import universe
    from downloaders.akshare_source import AkshareSource, MarketRouter

    cfg = Config(str(PROJECT_ROOT / "config" / "default.yaml"))
    db = Database(args.db or cfg.get("storage", "sqlite_path"))

    # ── 1. 清单 ──
    rows = []
    if args.csv:
        raw = universe.load_csv(args.csv)
        print(f"从 {args.csv} 读到 {len(raw)} 只")
        universe.save(db, raw)
        # 从库里读回，这样才带上 stock_type，类型过滤才生效
        wanted = {r["code"] for r in raw}
        rows = [r for r in universe.load(db, market=args.market,
                                         stock_type=args.type)
                if r["code"] in wanted]
    else:
        if not args.refresh_list:
            rows = universe.load(db, market=args.market, stock_type=args.type)
            if rows:
                print(f"用库里已有清单: {len(rows)} 只"
                      f"（要更新加 --refresh-list）")
        if not rows:
            fetcher = universe.UniverseFetcher()
            try:
                fetched = fetcher.fetch(on_progress=lambda m: print(m))
            except Exception as e:
                print(f"\n拉取清单失败: {e}\n")
                print("清单拿不到就没法下全市场。三条路：")
                print("  1. 先跑 python -m scripts.doctor 看数据源通不通")
                print("  2. 代理配国内域名直连（东财是国内服务，走海外代理必失败）")
                print("  3. 自己准备一个 CSV（一列 code），用 --csv 传进来")
                return 1
            print(f"\n清单来源: {fetcher.last_source}，共 {len(fetched)} 只")
            universe.save(db, fetched)
            rows = universe.load(db, market=args.market, stock_type=args.type)

    # 北交所（83/87/88/430/920 开头）只有东财拿得到，Yahoo 不支持。
    # 默认排除，免得在 Yahoo 路径上刷一屏无数据。
    if not args.include_bse and args.type != "BSE":
        before = len(rows)
        rows = [r for r in rows if r.get("stock_type") != "BSE"]
        if before != len(rows):
            print(f"排除北交所 {before - len(rows)} 只"
                  f"（加 --include-bse 可包含，但需要东财可达）")

    if args.limit:
        rows = rows[:args.limit]

    # 按类型统计
    by_type = {}
    for r in rows:
        by_type[r.get("stock_type") or "?"] = by_type.get(r.get("stock_type") or "?", 0) + 1
    print("清单构成: " + "  ".join(f"{k} {v}" for k, v in sorted(by_type.items())))

    if args.list_only:
        print("\n只拉清单，未下载。去掉 --list-only 开始下载。")
        return 0

    if not rows:
        print("清单为空，无事可做。")
        return 1

    # ── 2. 跳过已有数据的 ──
    todo = []
    skipped = 0
    if args.redownload:
        todo = rows
    else:
        for r in rows:
            if db.get_latest_time(r["code"], "K_DAY"):
                skipped += 1
            else:
                todo.append(r)
        if skipped:
            print(f"已有日线数据，跳过 {skipped} 只（要重下加 --redownload）")

    if not todo:
        print("全部已下载完成。要补最新几天的话，用增量模式重下:"
              " --redownload")
        return 0

    # ── 3. 下载 ──
    try:
        ak_src = AkshareSource(db, cfg)
    except ImportError as e:
        print(f"A股数据源不可用: {e}")
        return 1
    router = MarketRouter(futu_downloader=None, akshare_source=ak_src)

    est = len(todo) * 1.2      # 每只约 1 个请求 + 限流间隔
    print(f"\n待下载 {len(todo)} 只，预计 {_fmt_eta(est)}（受限流和网络影响）")
    print(f"数据源: {args.source}   Ctrl+C 可随时中断，重跑接着下\n")

    _install_sigint()
    t0 = time.time()
    ok = fail = 0
    total_rows = 0
    failures = []

    for i, r in enumerate(todo, 1):
        if _STOP["flag"]:
            break
        code, name = r["code"], (r.get("name") or "")[:10]
        try:
            n = router.download_history(
                code=code, ktype_str="K_DAY",
                start_date=args.start, end_date=None,
                incremental=True, prefer=args.source,
                should_stop=lambda: _STOP["flag"])
        except Exception as e:
            n = 0
            router.last_error = f"{type(e).__name__}: {e}"

        if n > 0:
            ok += 1
            total_rows += n
            tag = f"{n:>6,} 条  {router.last_source or ''}"
        else:
            err = router.last_error or "无数据"
            if err == "已停止":
                break
            fail += 1
            failures.append((code, err))
            tag = f"     0 条  {err[:38]}"

        done = i
        rate = (time.time() - t0) / done
        eta = rate * (len(todo) - done)
        print(f"[{done:>5}/{len(todo)}] {code:<12}{name:<12}{tag}"
              f"   剩 {_fmt_eta(eta)}", flush=True)

    # ── 4. 收尾 ──
    elapsed = time.time() - t0
    print("\n" + "═" * 66)
    if _STOP["flag"]:
        print(f"已中断。本次完成 {ok} 只，失败 {fail} 只，落库 {total_rows:,} 行")
        print("直接重跑本命令即可接着下（已有数据的会自动跳过）。")
    else:
        print(f"下载完成。成功 {ok} 只，失败 {fail} 只，落库 {total_rows:,} 行")
    print(f"耗时 {_fmt_eta(elapsed)}")

    if failures:
        print(f"\n失败的 {len(failures)} 只（前 20）：")
        for code, err in failures[:20]:
            print(f"  {code:<12} {err[:56]}")
        # 失败清单落盘，方便重试
        out = PROJECT_ROOT / "data" / "failed_codes.csv"
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write("code,error\n")
                for code, err in failures:
                    f.write(f'{code},"{err.replace(chr(34), chr(39))}"\n')
            print(f"\n完整失败清单: {out}")
            print(f"重试: python -m scripts.download_all --csv {out}")
        except Exception:
            pass

    stats = db.get_stats() or {}
    print(f"\n库里现有: {stats.get('kline_stocks', 0):,} 只标的，"
          f"{stats.get('kline_total', 0):,} 行 K 线，"
          f"{stats.get('db_size_mb', 0):.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
