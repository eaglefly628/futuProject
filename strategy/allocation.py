"""
建仓方案：把一笔钱变成具体的买入计划，并用历史数据检验不同建仓方式。

回答的是「这笔钱怎么买入」，不是「买什么会涨」——
后者没人算得出来，这个模块也不试图算。它只做三件事：

  1. 等权建仓计算   资金 → 每只买几手、花多少、剩多少（含真实费率和整手约束）
  2. 建仓方式回测   一次性 / 分批定投 / 逢跌加仓，在同一段历史上对比
  3. 相关性检查     选中的标的到底是不是同一个东西

第 3 条对 A500 尤其重要：市面上十几只「中证A500ETF」跟踪的是同一个指数，
均分到它们身上不构成分散，只是把一份手续费付了很多遍。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger

# A 股场内 ETF 最小交易单位（1 手 = 100 份）
LOT_SIZE = 100


# ═══════════════════════════════════════════════
#  一、等权建仓计算
# ═══════════════════════════════════════════════
@dataclass
class Lot:
    """单个标的的买入明细"""
    code: str
    name: str
    price: float
    shares: int          # 股数，必然是 LOT_SIZE 的整数倍
    amount: float        # 股票金额（不含费）
    fee: float           # 买入费用
    total: float         # 实际支出 = amount + fee

    @property
    def hands(self) -> int:
        return self.shares // LOT_SIZE


@dataclass
class Plan:
    """一次建仓的完整方案"""
    cash: float                       # 可用资金
    lots: List[Lot] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)   # 钱不够一手的标的

    @property
    def invested(self) -> float:
        """实际投出去的钱（含费）"""
        return sum(l.total for l in self.lots)

    @property
    def stock_amount(self) -> float:
        return sum(l.amount for l in self.lots)

    @property
    def total_fee(self) -> float:
        return sum(l.fee for l in self.lots)

    @property
    def leftover(self) -> float:
        """买不掉的零钱"""
        return self.cash - self.invested

    @property
    def deploy_rate(self) -> float:
        """资金利用率"""
        return self.invested / self.cash if self.cash else 0.0

    @property
    def fee_rate(self) -> float:
        """费用占比 —— 均分到很多同质标的时这个数会变难看"""
        return self.total_fee / self.stock_amount if self.stock_amount else 0.0


def equal_weight_plan(prices: Dict[str, float], cash: float,
                      fee_calc=None, names: Dict[str, str] = None,
                      lot_size: int = LOT_SIZE) -> Plan:
    """
    把 cash 等额分到 prices 里的每个标的，按整手向下取整。

    Args:
        prices: {code: 现价}
        cash: 总资金
        fee_calc: FeeCalculator，None 则不计费用
        names: {code: 名称}，仅用于显示
        lot_size: 每手股数

    Returns:
        Plan
    """
    names = names or {}
    plan = Plan(cash=cash)

    codes = [c for c, p in prices.items() if p and p > 0]
    if not codes:
        return plan

    # 每只的目标金额。留一点余量给手续费，否则最后一只可能差几块钱买不上
    per = cash / len(codes) * 0.999

    for code in codes:
        price = float(prices[code])
        lots_n = int(per // (price * lot_size))
        if lots_n < 1:
            plan.skipped.append(code)
            continue

        shares = lots_n * lot_size
        amount = shares * price
        fee = 0.0
        if fee_calc is not None:
            try:
                fee = float(fee_calc.calculate(code, "BUY", shares, price)["total_cost"])
            except Exception as e:
                logger.warning(f"费用计算失败 {code}: {e}")

        plan.lots.append(Lot(
            code=code, name=names.get(code, ""), price=price,
            shares=shares, amount=amount, fee=fee, total=amount + fee))

    return plan


# ═══════════════════════════════════════════════
#  二、建仓方式回测
# ═══════════════════════════════════════════════
@dataclass
class EntryResult:
    """一种建仓方式在一段历史上的表现"""
    mode: str
    label: str
    shares: int = 0
    spent: float = 0.0          # 含费总支出
    fee: float = 0.0
    buys: int = 0               # 实际成交笔数
    leftover: float = 0.0       # 没投出去的现金
    avg_cost: float = 0.0       # 每股平均成本（含费）
    last_price: float = 0.0
    market_value: float = 0.0
    final_equity: float = 0.0   # 市值 + 剩余现金
    max_drawdown: float = 0.0   # 建仓期间账户最大回撤
    equity_curve: List[float] = field(default_factory=list)

    @property
    def pnl(self) -> float:
        return self.final_equity - (self.spent + self.leftover)

    @property
    def return_rate(self) -> float:
        base = self.spent + self.leftover
        return self.pnl / base if base else 0.0


def _buy(price: float, budget: float, fee_calc, code: str,
         lot_size: int = LOT_SIZE):
    """
    用 budget 尽量买，返回 (股数, 金额, 费用)。买不起一手就返回 0。
    """
    if price <= 0 or budget <= 0:
        return 0, 0.0, 0.0
    lots_n = int(budget // (price * lot_size))
    if lots_n < 1:
        return 0, 0.0, 0.0

    shares = lots_n * lot_size
    amount = shares * price
    fee = 0.0
    if fee_calc is not None:
        try:
            fee = float(fee_calc.calculate(code, "BUY", shares, price)["total_cost"])
        except Exception:
            fee = 0.0
        # 费用可能把预算撑爆，退一手再试
        while shares > 0 and amount + fee > budget:
            shares -= lot_size
            if shares <= 0:
                return 0, 0.0, 0.0
            amount = shares * price
            try:
                fee = float(fee_calc.calculate(code, "BUY", shares, price)["total_cost"])
            except Exception:
                fee = 0.0
    return shares, amount, fee


def simulate_entry(df: pd.DataFrame, cash: float, mode: str = "lump",
                   batches: int = 12, interval: int = 20,
                   dip_pct: float = 5.0, ma_period: int = 20,
                   fee_calc=None, code: str = "", lot_size: int = LOT_SIZE
                   ) -> Optional[EntryResult]:
    """
    在一段日线行情上模拟建仓。

    Args:
        df: 日线，需含 time_key / close，按时间升序
        cash: 总资金
        mode:
            "lump"  第一天一次性全部买入
            "dca"   分 batches 批，每 interval 个交易日买一次（定投）
            "dip"   分 batches 批，但只在价格比 ma_period 均线低 dip_pct% 时才买
        batches: 分批数
        interval: 定投间隔（交易日）
        dip_pct: 逢跌买入的触发跌幅（%），相对均线
        ma_period: dip 模式用的均线周期
        fee_calc: FeeCalculator
        code: 标的代码，费率计算要用

    Returns:
        EntryResult，数据不足返回 None

    注意：成交价用当日收盘价，不含滑点和买卖价差。
    真实成交会比这个差，尤其是流动性弱的标的。
    """
    if df is None or df.empty or "close" not in df.columns:
        return None

    px = pd.to_numeric(df["close"], errors="coerce").dropna().reset_index(drop=True)
    if len(px) < 2:
        return None

    labels = {
        "lump": "一次性买入",
        "dca": f"分{batches}批定投（每{interval}个交易日）",
        "dip": f"逢跌加仓（低于{ma_period}日均线{dip_pct}%）",
    }
    res = EntryResult(mode=mode, label=labels.get(mode, mode))

    ma = px.rolling(ma_period, min_periods=1).mean()

    cash_left = cash
    shares = 0
    spent = 0.0
    fee_sum = 0.0
    buys = 0

    # 每批预算。dip 模式钱可能花不完，这是它的固有代价
    per_batch = cash / max(1, batches) if mode in ("dca", "dip") else cash

    for i in range(len(px)):
        price = float(px.iloc[i])
        do_buy = False

        if mode == "lump":
            do_buy = (i == 0)
        elif mode == "dca":
            do_buy = (i % interval == 0) and buys < batches
        elif mode == "dip":
            below = (price <= float(ma.iloc[i]) * (1 - dip_pct / 100.0))
            do_buy = below and buys < batches

        if do_buy and cash_left > 0:
            budget = min(per_batch, cash_left) if mode != "lump" else cash_left
            n, amt, fee = _buy(price, budget, fee_calc, code, lot_size)
            if n > 0:
                shares += n
                spent += amt + fee
                fee_sum += fee
                cash_left -= (amt + fee)
                buys += 1

        res.equity_curve.append(shares * price + cash_left)

    if shares == 0:
        return None

    curve = np.array(res.equity_curve, dtype=float)
    peak = np.maximum.accumulate(curve)
    dd = np.where(peak > 0, (peak - curve) / peak, 0.0)

    res.shares = shares
    res.spent = spent
    res.fee = fee_sum
    res.buys = buys
    res.leftover = cash_left
    res.avg_cost = spent / shares
    res.last_price = float(px.iloc[-1])
    res.market_value = shares * res.last_price
    res.final_equity = res.market_value + cash_left
    res.max_drawdown = float(dd.max())
    return res


def compare_entries(df: pd.DataFrame, cash: float, code: str = "",
                    fee_calc=None, batches: int = 12, interval: int = 20,
                    dip_pct: float = 5.0, ma_period: int = 20
                    ) -> List[EntryResult]:
    """在同一段行情上跑三种建仓方式，返回可直接对比的结果"""
    out = []
    for mode in ("lump", "dca", "dip"):
        r = simulate_entry(df, cash, mode=mode, batches=batches,
                           interval=interval, dip_pct=dip_pct,
                           ma_period=ma_period, fee_calc=fee_calc, code=code)
        if r is not None:
            out.append(r)
    return out


# ═══════════════════════════════════════════════
#  三、最低佣金临界点
# ═══════════════════════════════════════════════
def commission_floor(config, market: str = "SZ") -> tuple:
    """
    取佣金费率和最低佣金。

    Returns:
        (rate, min_commission, threshold)
        threshold 是临界金额：单笔低于它，最低佣金就会咬住，
        实际费率高于名义费率。
    """
    cfg = config.get("paper_trading", "fees", market, default={}) or {}
    rate = float(cfg.get("commission_rate", 0.00025))
    floor = float(cfg.get("min_commission", 5))
    threshold = floor / rate if rate > 0 else 0.0
    return rate, floor, threshold


def split_cost(cash: float, n_symbols: int, n_batches: int,
               config, market: str = "SZ") -> dict:
    """
    把一笔钱切成 n_symbols × n_batches 笔之后，佣金效率会怎样。

    分散本身不会多付按比例的佣金 —— 佣金是按成交金额算的，
    切成几份总额一样。真正会咬人的是「最低佣金」：单笔金额太小时
    按最低值收，实际费率就上去了。

    Returns:
        {orders, per_order, rate, floor, threshold, hit_floor,
         effective_rate, nominal_fee, actual_fee, extra}
    """
    rate, floor, threshold = commission_floor(config, market)
    orders = max(1, int(n_symbols) * int(n_batches))
    per_order = cash / orders

    nominal = per_order * rate
    actual = max(nominal, floor)
    hit = actual > nominal + 1e-9

    return {
        "orders": orders,
        "per_order": per_order,
        "rate": rate,
        "floor": floor,
        "threshold": threshold,
        "hit_floor": hit,
        "effective_rate": (actual / per_order) if per_order else 0.0,
        "nominal_fee": nominal * orders,
        "actual_fee": actual * orders,
        "extra": (actual - nominal) * orders,
    }


def max_splits_before_floor(cash: float, config, market: str = "SZ") -> int:
    """
    最多能切成几笔而不触发最低佣金。

    超过这个笔数，每多切一笔就是白送钱。
    """
    _, _, threshold = commission_floor(config, market)
    if threshold <= 0:
        return 10 ** 9
    return max(1, int(cash // threshold))


# ═══════════════════════════════════════════════
#  四、相关性检查
# ═══════════════════════════════════════════════
def correlation(db, codes: List[str], start: str = None, end: str = None,
                ktype: str = "K_DAY") -> Optional[pd.DataFrame]:
    """
    算这些标的日收益率的相关系数矩阵。

    用来回答「我这样分散到底分散了没有」：
    相关系数接近 1 说明它们是同一个东西，分开买只是多付手续费。

    Returns:
        相关系数 DataFrame，可用数据不足 2 只时返回 None
    """
    series = {}
    for code in codes:
        try:
            df = db.get_kline(code, ktype, start=start, end=end)
        except Exception as e:
            logger.warning(f"读取失败 {code}: {e}")
            continue
        if df is None or df.empty or "close" not in df.columns:
            continue
        s = pd.Series(
            pd.to_numeric(df["close"], errors="coerce").values,
            index=pd.to_datetime(df["time_key"].astype(str).str[:10]).values)
        s = s[~s.index.duplicated(keep="last")].dropna()
        if len(s) >= 20:
            series[code] = s.pct_change().dropna()

    if len(series) < 2:
        return None
    return pd.DataFrame(series).corr()


def redundancy_report(corr: pd.DataFrame, threshold: float = 0.98) -> dict:
    """
    从相关性矩阵里挑出高度重复的标的对。

    Returns:
        {"pairs": [(a, b, corr), ...], "threshold": ..., "n": ...}
    """
    pairs = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c = float(corr.iloc[i, j])
            if not np.isnan(c) and c >= threshold:
                pairs.append((cols[i], cols[j], c))
    pairs.sort(key=lambda x: -x[2])
    return {"pairs": pairs, "threshold": threshold, "n": len(cols)}
