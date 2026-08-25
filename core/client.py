"""
Futu OpenD 客户端封装
管理与 OpenD 网关的连接、重连、并发控制
"""
import time
from typing import Optional, Tuple
from loguru import logger

try:
    from futu import (
        OpenQuoteContext, OpenSecTradeContext,
        RET_OK, RET_ERROR,
        KLType, KL_FIELD, SubType, AuType,
        SysConfig
    )
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    logger.warning("futu-api 未安装，请运行: pip install futu-api")


class FutuClient:
    """Futu OpenD 客户端封装"""

    def __init__(self, host: str = "127.0.0.1", port: int = 11111,
                 is_encrypt: bool = False, rsa_key_path: str = ""):
        self.host = host
        self.port = port
        self.is_encrypt = is_encrypt
        self.rsa_key_path = rsa_key_path
        self._quote_ctx: Optional[OpenQuoteContext] = None
        self._trade_ctx: Optional[OpenSecTradeContext] = None

        if not FUTU_AVAILABLE:
            raise ImportError("请先安装 futu-api: pip install futu-api")

        if rsa_key_path:
            SysConfig.set_init_rsa_file(rsa_key_path)
        if is_encrypt:
            SysConfig.enable_proto_encrypt(True)

    def connect_quote(self) -> "OpenQuoteContext":
        """建立行情连接"""
        if self._quote_ctx is None:
            self._quote_ctx = OpenQuoteContext(
                host=self.host, port=self.port
            )
            logger.info(f"行情连接已建立 -> {self.host}:{self.port}")
        return self._quote_ctx

    def connect_trade(self, market: str = "HK",
                      security_firm=None) -> "OpenSecTradeContext":
        """建立交易连接 (未来扩展用)"""
        if self._trade_ctx is None:
            from futu import TrdMarket, SecurityFirm
            trd_market_map = {
                "HK": TrdMarket.HK,
                "US": TrdMarket.US,
                "SH": TrdMarket.SH,
                "SZ": TrdMarket.SZ,
            }
            trd_market = trd_market_map.get(market.upper(), TrdMarket.HK)
            self._trade_ctx = OpenSecTradeContext(
                host=self.host, port=self.port,
                trd_market=trd_market,
                security_firm=security_firm
            )
            logger.info(f"交易连接已建立 -> {market}")
        return self._trade_ctx

    def close(self):
        """关闭所有连接"""
        if self._quote_ctx:
            self._quote_ctx.close()
            self._quote_ctx = None
            logger.info("行情连接已关闭")
        if self._trade_ctx:
            self._trade_ctx.close()
            self._trade_ctx = None
            logger.info("交易连接已关闭")

    def __enter__(self):
        self.connect_quote()
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def quote_ctx(self):
        if self._quote_ctx is None:
            self.connect_quote()
        return self._quote_ctx
