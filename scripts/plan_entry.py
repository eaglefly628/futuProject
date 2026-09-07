"""
建仓方案测算

  python -m scripts.plan_entry --cash 3200000
  python -m scripts.plan_entry --cash 3200000 --codes SZ.159338
  python -m scripts.plan_entry --cash 3200000 --batches 24 --interval 10

回答「这笔钱怎么买入」，不回答「买什么会涨」。
所有数字都来自你自己库里的历史数据，跑之前先把数据采齐。
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _fmt(n, w=14):
    return f"{n:>{w},.2f}"


def main():
    ap = argparse.ArgumentParser(description="建仓方案测算")
    ap.add_argument("--cash", type=float, default=3_200_000, help="可用资金")
    ap.add_argument("--codes", nargs="*", default=None,
                    help="标的代码，默认用 A500 清单")
    ap.add_argument("--start", default=None, help="回测起始 YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="回测结束 YYYY-MM-DD")
    ap.add_argument("--batches", type=int, default=12, help="分批数")
    ap.add_argument("--interval", type=int, default=20, help="定投间隔(交易日)")
    ap.add_argument("--dip", type=float, default=5.0, help="逢跌买入触发跌幅%%")
    ap.add_argument("--ma", type=int, default=20, help="逢跌模式的均线周期")
    ap.add_argument("--db", default=None, help="指定数据库路径，默认用配置里的")
    args = ap.parse_args()

    from loguru import logger
    logger.remove()

    from config import Config
    from storage.database import Database
    from trading.fee_calculator import FeeCalculator
    from strategy.allocation import (
        equal_weight_plan, compare_entries, correlation, redundancy_report,
        commission_floor, split_cost, max_splits_before_floor)

    cfg = Config(str(PROJECT_ROOT / "config" / "default.yaml"))
    db = Database(args.db or cfg.get("storage", "sqlite_path"))
    fee_calc = FeeCalculator(cfg)

    from gui.panels.a500_center import A500_ETFS
    name_map = dict(A500_ETFS)
    codes = args.codes if args.codes else [c for c, _ in A500_ETFS]

    print(f"\n可用资金: {args.cash:,.2f} 元")
    print(f"候选标的: {len(codes)} 只\n")

    # ── 1. 相关性：这些标的是不是同一个东西 ──
    print("═" * 74)
    print(" 一、相关性检查  —— 分散到多只，到底分散了没有")
    print("═" * 74)
    corr = correlation(db, codes, args.start, args.end)
    if corr is None:
        print("  可用数据不足（至少要 2 只、各 20 根日线）。")
        print("  先去「A500中心 → 数据采集」把日线拉齐，或跑:")
        print("      python -m scripts.doctor    # 先确认数据源通不通\n")
    else:
        rep = redundancy_report(corr, threshold=0.98)
        vals = corr.values[~(corr.values == 1.0)]
        if len(vals):
            print(f"  {rep['n']} 只之间的相关系数: "
                  f"最低 {vals.min():.4f}  中位 {sorted(vals)[len(vals)//2]:.4f}  "
                  f"最高 {vals.max():.4f}")
        if rep["pairs"]:
            print(f"\n  相关系数 ≥ {rep['threshold']} 的组合（几乎是同一个东西）:")
            for a, b, c in rep["pairs"][:12]:
                print(f"    {a} ←→ {b}   {c:.4f}")
            if len(rep["pairs"]) > 12:
                print(f"    …… 还有 {len(rep['pairs'])-12} 对")
            print("\n  这些标的跟踪同一个指数，均分到它们身上不构成分散 ——")
            print("  收益曲线几乎重合，风险一点没降。")
            print("  代价不在佣金（按比例收，切几份总额一样，见下一节），")
            print("  而在买卖价差：规模小、成交淡的那几只，冲击成本更高。")
        else:
            print("  没有发现高度重复的标的。")
        print()

    # ── 2. 等权建仓：钱具体怎么落到手数上 ──
    print("═" * 74)
    print(" 二、等权建仓测算  —— 按最新收盘价，每只买几手")
    print("═" * 74)
    prices = {}
    for code in codes:
        try:
            df = db.get_kline(code, "K_DAY")
            if df is not None and not df.empty:
                prices[code] = float(df["close"].iloc[-1])
        except Exception:
            pass

    if not prices:
        print("  库里没有日线数据，无法测算。先采集数据。\n")
    else:
        plan = equal_weight_plan(prices, args.cash, fee_calc, name_map)
        print(f"  {'代码':<12}{'名称':<22}{'现价':>8}{'手数':>8}"
              f"{'金额':>14}{'费用':>9}")
        print("  " + "─" * 72)
        for l in plan.lots:
            print(f"  {l.code:<12}{l.name:<22}{l.price:>8.3f}{l.hands:>8,}"
                  f"{l.amount:>14,.0f}{l.fee:>9,.0f}")
        print("  " + "─" * 72)
        print(f"  实际投入 {_fmt(plan.invested)}   "
              f"资金利用率 {plan.deploy_rate:.2%}")
        print(f"  交易费用 {_fmt(plan.total_fee)}   "
              f"占股票金额 {plan.fee_rate:.4%}")
        print(f"  剩余现金 {_fmt(plan.leftover)}")
        if plan.skipped:
            print(f"  钱不够一手，跳过: {', '.join(plan.skipped)}")

        print()

    # ── 2.5 切多细才不亏手续费 ──
    print("═" * 74)
    print(" 三、拆单粒度  —— 切成多少笔之前，手续费还是划算的")
    print("═" * 74)
    rate, floor, thr = commission_floor(cfg)
    cap = max_splits_before_floor(args.cash, cfg)
    print(f"  佣金 {rate:.4%}，最低 {floor:.0f} 元/笔")
    print(f"  → 单笔低于 {thr:,.0f} 元就被最低佣金咬住，实际费率开始上升")
    print(f"  → {args.cash:,.0f} 元最多切 {cap:,} 笔\n")

    print(f"  {'方案':<26}{'笔数':>7}{'每笔金额':>13}{'实际费率':>11}{'多付':>10}")
    print("  " + "─" * 68)
    n_codes = len(prices) or len(codes)
    for nsym, nb, tag in [
        (1, 1, "只买1只，一次性"),
        (n_codes, 1, f"{n_codes}只等权，一次性"),
        (1, args.batches, f"只买1只，分{args.batches}批"),
        (n_codes, args.batches, f"{n_codes}只 × {args.batches}批"),
        (n_codes, args.batches * 2, f"{n_codes}只 × {args.batches*2}批"),
    ]:
        r = split_cost(args.cash, nsym, nb, cfg)
        flag = "  ← 触发" if r["hit_floor"] else ""
        print(f"  {tag:<26}{r['orders']:>7,}{r['per_order']:>13,.0f}"
              f"{r['effective_rate']:>11.4%}{r['extra']:>10,.0f}{flag}")
    print("  " + "─" * 68)
    print("  注意：按比例的佣金不会因为分散而变多 —— 切成几份总额一样。")
    print("  真正多花的钱在两处：一是单笔太小时被最低佣金咬住（上表）；")
    print("  二是买卖价差，规模小、成交淡的 ETF 价差更宽，这项不在费率表里。")
    print()

    # ── 3. 建仓方式对比 ──
    print("═" * 74)
    print(" 四、建仓方式对比  —— 同一段历史，同样的钱，三种买法")
    print("═" * 74)
    main_code = codes[0]
    try:
        df = db.get_kline(main_code, "K_DAY", start=args.start, end=args.end)
    except Exception:
        df = None

    if df is None or df.empty:
        print(f"  {main_code} 没有日线数据，跳过。\n")
    else:
        span = f"{str(df['time_key'].iloc[0])[:10]} ~ {str(df['time_key'].iloc[-1])[:10]}"
        print(f"  标的: {main_code} {name_map.get(main_code,'')}   "
              f"区间: {span}   {len(df)} 个交易日\n")
        results = compare_entries(
            df, args.cash, code=main_code, fee_calc=fee_calc,
            batches=args.batches, interval=args.interval,
            dip_pct=args.dip, ma_period=args.ma)

        print(f"  {'建仓方式':<34}{'成交':>5}{'均价':>9}"
              f"{'期末权益':>15}{'收益':>9}{'最大回撤':>10}")
        print("  " + "─" * 72)
        for r in results:
            print(f"  {r.label:<34}{r.buys:>5}{r.avg_cost:>9.3f}"
                  f"{r.final_equity:>15,.0f}{r.return_rate:>8.2%}"
                  f"{r.max_drawdown:>10.2%}")
        print("  " + "─" * 72)
        print("  成交价按当日收盘价，不含滑点和买卖价差；真实成交只会更差。")
        print("  这是一段特定历史上的结果，换个区间结论可能反过来 ——")
        print("  它能告诉你这几种买法的性格差异，不能预测下一段行情。\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
