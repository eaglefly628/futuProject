"""
逐笔成交数据采集器
支持实时订阅和历史逐笔数据获取
"""
import time
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Optional
from loguru import logger

try:
    from futu import SubType, RET_OK, TickerHandlerBase
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False


class TickCollector:
    """逐笔成交数据采集器"""

    def __init__(self, futu_client, database, config):
        self.client = futu_client
        self.db = database
        self.config = config
        self.interval = config.get("tick", "collect_interval", default=0.3)
        self.max_count = config.get("tick", "max_count", default=1000)
        self._subscriptions = set()

    def get_history_ticks(self, code: str, count: int = None,
                          start: str = None, end: str = None) -> int:
        """
        获取历史逐笔数据

        注意: 富途API对历史逐笔有限制
        - 需要先订阅 SubType.TICKER
        - 最多获取最近1000条
        """
        if count is None:
            count = self.max_count

        ctx = self.client.quote_ctx

        # 确保已订阅
        if code not in self._subscriptions:
            ret, data = ctx.subscribe([code], [SubType.TICKER])
            if ret != RET_OK:
                logger.error(f"订阅失败: {code} - {data}")
                return 0
            self._subscriptions.add(code)
            time.sleep(0.5)

        ret, data = ctx.get_rt_ticker(code=code, num=count)
        if ret != RET_OK:
            logger.error(f"获取逐笔失败: {code} - {data}")
            self.db.log_download(code, "tick", error_msg=str(data), status="error")
            return 0

        if data.empty:
            logger.info(f"无逐笔数据: {code}")
            return 0

        saved = self.db.save_tick(code, data)
        time_range = f"{data['time'].iloc[0]} ~ {data['time'].iloc[-1]}"
        logger.info(f"逐笔采集: {code} -> {saved}条 [{time_range}]")

        self.db.log_download(
            code, "tick", start_time=str(data["time"].iloc[0]),
            end_time=str(data["time"].iloc[-1]),
            record_count=saved, status="success"
        )
        return saved

    def subscribe_realtime(self, codes: List[str]):
        """
        订阅实时逐笔数据 (需配合回调处理)
        """
        ctx = self.client.quote_ctx

        # 注册回调
        handler = _TickHandler(self.db)
        ctx.set_handler(handler)

        ret, data = ctx.subscribe(codes, [SubType.TICKER])
        if ret != RET_OK:
            logger.error(f"实时订阅失败: {data}")
            return False

        self._subscriptions.update(codes)
        logger.info(f"已订阅实时逐笔: {codes}")
        return True

    def unsubscribe(self, codes: List[str] = None):
        """取消订阅"""
        if codes is None:
            codes = list(self._subscriptions)
        ctx = self.client.quote_ctx
        ret, data = ctx.unsubscribe(codes, [SubType.TICKER])
        if ret == RET_OK:
            for c in codes:
                self._subscriptions.discard(c)
            logger.info(f"已取消订阅: {codes}")

    def batch_collect(self, codes: List[str], count: int = None) -> dict:
        """批量采集多只股票的逐笔数据"""
        results = {}
        for code in codes:
            saved = self.get_history_ticks(code, count)
            results[code] = saved
            time.sleep(self.interval)
        return results


class _TickHandler:
    """实时逐笔数据回调处理器"""
    def __init__(self, database):
        self.db = database

    if FUTU_AVAILABLE:
        class _Inner(TickerHandlerBase):
            def __init__(self, db):
                super().__init__()
                self.db = db

            def on_recv_rsp(self, rsp_pb):
                ret, data = super().on_recv_rsp(rsp_pb)
                if ret == RET_OK and not data.empty:
                    code = data["code"].iloc[0]
                    self.db.save_tick(code, data)
                    logger.debug(f"实时逐笔: {code} +{len(data)}条")
                return ret, data
