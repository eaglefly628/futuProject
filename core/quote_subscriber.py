"""实时行情订阅器"""
import time
from typing import Optional, Dict, List
from loguru import logger

try:
    from futu import OpenQuoteContext, SubType, RET_OK, StockQuoteHandlerBase
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False


class QuoteSubscriber:
    """管理实时行情订阅"""

    def __init__(self, futu_client):
        self.client = futu_client
        self.quotes: Dict[str, dict] = {}  # {code: {price, change_rate, ...}}
        self._subscribed_codes: List[str] = []
        self._handler = None

    def subscribe(self, codes: list):
        """订阅股票实时行情"""
        if not codes:
            return
        ctx = self.client.quote_ctx
        # 设置回调处理器
        if self._handler is None:
            self._handler = _QuoteHandler(self)
            ctx.set_handler(self._handler)

        new_codes = [c for c in codes if c not in self._subscribed_codes]
        if new_codes:
            ret, err = ctx.subscribe(new_codes, [SubType.QUOTE])
            if ret == RET_OK:
                self._subscribed_codes.extend(new_codes)
                logger.info(f"已订阅实时行情: {new_codes}")
            else:
                logger.warning(f"订阅失败: {err}")

    def unsubscribe(self, codes: list = None):
        """取消订阅"""
        if codes is None:
            codes = self._subscribed_codes[:]
        if not codes:
            return
        ctx = self.client.quote_ctx
        ret, err = ctx.unsubscribe(codes, [SubType.QUOTE])
        if ret == RET_OK:
            for c in codes:
                self._subscribed_codes = [x for x in self._subscribed_codes if x != c]
                self.quotes.pop(c, None)

    def get_snapshot(self, codes: list) -> dict:
        """获取最新快照"""
        ctx = self.client.quote_ctx
        ret, data = ctx.get_stock_quote(codes)
        if ret != RET_OK or data is None or data.empty:
            return self.quotes
        for _, row in data.iterrows():
            code = str(row.get("code", ""))
            self.quotes[code] = {
                "code": code,
                "name": str(row.get("stock_name", "")),
                "price": row.get("last_price"),
                "change_rate": row.get("price_spread"),
                "change_val": row.get("price_spread"),
                "volume": row.get("volume"),
                "turnover": row.get("turnover"),
                "amplitude": row.get("amplitude"),
                "high": row.get("high_price"),
                "low": row.get("low_price"),
                "open": row.get("open_price"),
                "prev_close": row.get("prev_close_price"),
                "pe_ratio": row.get("pe_ratio"),
                "pb_ratio": row.get("pb_ratio"),
                "volume_ratio": row.get("volume_ratio"),
                "turnover_rate": row.get("turnover_rate"),
            }
        return self.quotes

    def close(self):
        """关闭订阅"""
        self.unsubscribe()


class _QuoteHandler(StockQuoteHandlerBase if FUTU_AVAILABLE else object):
    """实时行情推送回调"""

    def __init__(self, subscriber: QuoteSubscriber):
        if FUTU_AVAILABLE:
            super().__init__()
        self._sub = subscriber

    def on_recv_rsp(self, rsp_pb):
        """收到实时行情推送"""
        ret, data = super().on_recv_rsp(rsp_pb)
        if ret == RET_OK and data is not None and not data.empty:
            for _, row in data.iterrows():
                code = str(row.get("code", ""))
                self._sub.quotes[code] = {
                    "code": code,
                    "name": str(row.get("stock_name", "")),
                    "price": row.get("last_price"),
                    "change_rate": row.get("price_spread"),
                    "change_val": row.get("price_spread"),
                    "volume": row.get("volume"),
                    "turnover": row.get("turnover"),
                    "high": row.get("high_price"),
                    "low": row.get("low_price"),
                    "open": row.get("open_price"),
                    "prev_close": row.get("prev_close_price"),
                }
        return ret, data
