"""交易费用计算器 - 支持 A股/港股/美股 真实费率"""
import math
from loguru import logger


class FeeCalculator:
    """根据市场计算交易费用"""

    def __init__(self, config):
        self.config = config

    def _detect_market(self, code: str) -> str:
        """根据代码判断市场: SH/SZ/HK/US"""
        code = code.upper()
        if code.startswith("SH.") or code.startswith("SH"):
            return "SH"
        if code.startswith("SZ.") or code.startswith("SZ"):
            return "SZ"
        if code.startswith("HK.") or code.startswith("HK"):
            return "HK"
        if code.startswith("US.") or code.startswith("US"):
            return "US"
        # 带点分隔的代码
        if '.' in code:
            prefix = code.split('.')[0]
            if prefix in ('SH', 'SZ', 'HK', 'US'):
                return prefix
        # 纯数字代码根据规则判断
        c = code.replace('.', '')
        if c.isdigit() and len(c) == 6:
            if c.startswith(('6', '9', '5')):
                return "SH"
            return "SZ"
        # 默认当作美股（如 AAPL 之类的字母代码）
        return "US"

    def calculate(self, code: str, direction: str, quantity: int, price: float) -> dict:
        """
        计算交易费用

        Args:
            code: 股票代码 (如 "SH.600519")
            direction: "BUY" 或 "SELL"
            quantity: 股数
            price: 每股成交价

        Returns:
            dict: commission, tax, fees, total_cost, fx_rate, currency
        """
        market = self._detect_market(code)
        amount = quantity * price

        fees_cfg = self.config.get("paper_trading", "fees", market, default={})
        fx_cfg = self.config.get("paper_trading", "fx_rate", default={})

        if market in ("SH", "SZ"):
            return self._calc_cn(market, direction, amount, fees_cfg)
        elif market == "HK":
            fx_rate = fx_cfg.get("HKD_CNY", 0.92) if isinstance(fx_cfg, dict) else 0.92
            return self._calc_hk(direction, amount, fees_cfg, fx_rate)
        else:  # US
            fx_rate = fx_cfg.get("USD_CNY", 7.25) if isinstance(fx_cfg, dict) else 7.25
            return self._calc_us(direction, quantity, amount, fees_cfg, fx_rate)

    def _calc_cn(self, market, direction, amount, cfg):
        """A股费用计算"""
        if not isinstance(cfg, dict):
            cfg = {}
        rate = cfg.get("commission_rate", 0.00025)
        min_comm = cfg.get("min_commission", 5)
        commission = max(amount * rate, min_comm)

        tax = 0
        if direction == "SELL":
            tax = amount * cfg.get("stamp_tax_rate", 0.001)

        fees = 0
        if market == "SH":
            fees = amount * cfg.get("transfer_fee_rate", 0.000002)

        return {
            "commission": round(commission, 2),
            "tax": round(tax, 2),
            "fees": round(fees, 2),
            "total_cost": round(commission + tax + fees, 2),
            "fx_rate": 1.0,
            "currency": "CNY",
        }

    def _calc_hk(self, direction, amount, cfg, fx_rate):
        """港股费用计算"""
        if not isinstance(cfg, dict):
            cfg = {}
        commission = max(
            amount * cfg.get("commission_rate", 0.0003),
            cfg.get("min_commission", 3),
        )
        platform_fee = cfg.get("platform_fee", 15)
        stamp_duty = math.ceil(amount * cfg.get("stamp_duty_rate", 0.0013))
        trading_fee = amount * cfg.get("trading_fee_rate", 0.00005)
        settlement_fee = max(
            amount * cfg.get("settlement_fee_rate", 0.00002), 2
        )

        total_hkd = commission + platform_fee + stamp_duty + trading_fee + settlement_fee
        total_cny = total_hkd * fx_rate

        return {
            "commission": round(commission * fx_rate, 2),
            "tax": round(stamp_duty * fx_rate, 2),
            "fees": round((platform_fee + trading_fee + settlement_fee) * fx_rate, 2),
            "total_cost": round(total_cny, 2),
            "fx_rate": fx_rate,
            "currency": "HKD",
        }

    def _calc_us(self, direction, quantity, amount, cfg, fx_rate):
        """美股费用计算"""
        if not isinstance(cfg, dict):
            cfg = {}
        commission = max(
            quantity * cfg.get("commission_per_share", 0.005),
            cfg.get("min_commission", 1),
        )

        sec_fee = 0
        if direction == "SELL":
            sec_fee = amount * cfg.get("sec_fee_rate", 0.0000278)

        taf_fee = max(
            quantity * cfg.get("taf_fee_per_share", 0.000166), 0.01
        )

        total_usd = commission + sec_fee + taf_fee
        total_cny = total_usd * fx_rate

        return {
            "commission": round(commission * fx_rate, 2),
            "tax": round(sec_fee * fx_rate, 2),
            "fees": round(taf_fee * fx_rate, 2),
            "total_cost": round(total_cny, 2),
            "fx_rate": fx_rate,
            "currency": "USD",
        }
