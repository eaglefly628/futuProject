"""
K线历史数据下载器
支持多种K线周期，增量下载，断点续传
"""
import time
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from loguru import logger

try:
    from futu import KLType, KL_FIELD, AuType, RET_OK
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False

# K线类型映射
KTYPE_MAP = {
    "K_1M": KLType.K_1M if FUTU_AVAILABLE else "K_1M",
    "K_3M": KLType.K_3M if FUTU_AVAILABLE else "K_3M",
    "K_5M": KLType.K_5M if FUTU_AVAILABLE else "K_5M",
    "K_15M": KLType.K_15M if FUTU_AVAILABLE else "K_15M",
    "K_30M": KLType.K_30M if FUTU_AVAILABLE else "K_30M",
    "K_60M": KLType.K_60M if FUTU_AVAILABLE else "K_60M",
    "K_DAY": KLType.K_DAY if FUTU_AVAILABLE else "K_DAY",
    "K_WEEK": KLType.K_WEEK if FUTU_AVAILABLE else "K_WEEK",
    "K_MON": KLType.K_MON if FUTU_AVAILABLE else "K_MON",
}


class KlineDownloader:
    """K线数据下载器"""

    def __init__(self, futu_client, database, config):
        self.client = futu_client
        self.db = database
        self.config = config
        self.max_count = config.get("kline", "max_count_per_request", default=1000)
        self.interval = config.get("kline", "request_interval", default=0.5)

    def download_history(self, code: str, ktype_str: str,
                         start_date: str = None, end_date: str = None,
                         incremental: bool = True) -> int:
        """
        下载历史K线数据

        Args:
            code: 股票代码, 如 "US.AAPL", "HK.00700"
            ktype_str: K线类型字符串
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            incremental: 增量模式(从上次最后记录继续)

        Returns:
            下载的记录总数
        """
        if ktype_str not in KTYPE_MAP:
            logger.error(f"不支持的K线类型: {ktype_str}")
            return 0

        ktype = KTYPE_MAP[ktype_str]

        # 增量模式: 从DB中最新记录开始
        if incremental and start_date is None:
            latest = self.db.get_latest_time(code, ktype_str)
            if latest:
                start_date = latest[:10]  # 取日期部分
                logger.info(f"增量模式: {code} {ktype_str} 从 {start_date} 继续")

        # 默认回溯天数
        if start_date is None:
            lookback = self.config.get("kline", "lookback_days", ktype_str, default=90)
            start_date = (datetime.now() - timedelta(days=lookback)).strftime("%Y-%m-%d")

        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        logger.info(f"开始下载: {code} {ktype_str} [{start_date} ~ {end_date}]")

        total_saved = 0
        page_start = start_date
        retry_count = 0
        max_retries = 3

        while True:
            try:
                ret, data, page_req_key = self.client.quote_ctx.request_history_kline(
                    code=code,
                    ktype=ktype,
                    start=page_start,
                    end=end_date,
                    max_count=self.max_count,
                    autype=AuType.QFQ,  # 前复权
                    fields=[
                        KL_FIELD.ALL
                    ] if FUTU_AVAILABLE else [],
                )

                if ret != RET_OK:
                    logger.error(f"请求失败: {data}")
                    retry_count += 1
                    if retry_count >= max_retries:
                        self.db.log_download(
                            code, "kline", ktype_str, start_date, end_date,
                            total_saved, "error", str(data)
                        )
                        break
                    time.sleep(self.interval * 2)
                    continue

                retry_count = 0

                if data.empty:
                    logger.info(f"无更多数据: {code} {ktype_str}")
                    break

                saved = self.db.save_kline(code, ktype_str, data)
                total_saved += saved

                logger.info(
                    f"  下载进度: {code} {ktype_str} | "
                    f"本批 {len(data)}条 | 累计 {total_saved}条 | "
                    f"范围 {data['time_key'].iloc[0]} ~ {data['time_key'].iloc[-1]}"
                )

                # 如果返回的数据不足max_count, 说明已到最后
                if len(data) < self.max_count:
                    break

                # 下一页: 用最后一条记录的时间
                page_start = str(data["time_key"].iloc[-1])[:10]
                time.sleep(self.interval)

            except Exception as e:
                logger.error(f"下载异常: {code} {ktype_str} - {e}")
                retry_count += 1
                if retry_count >= max_retries:
                    self.db.log_download(
                        code, "kline", ktype_str, start_date, end_date,
                        total_saved, "error", str(e)
                    )
                    break
                time.sleep(self.interval * 3)

        if total_saved > 0:
            self.db.log_download(
                code, "kline", ktype_str, start_date, end_date,
                total_saved, "success"
            )
        logger.info(f"下载完成: {code} {ktype_str} -> 共 {total_saved} 条")
        return total_saved

    def download_all_types(self, code: str, ktypes: List[str] = None,
                           incremental: bool = True) -> dict:
        """下载指定股票的所有K线类型"""
        if ktypes is None:
            ktypes = self.config.get("kline", "default_types", default=["K_1M", "K_DAY"])
        results = {}
        for kt in ktypes:
            count = self.download_history(code, kt, incremental=incremental)
            results[kt] = count
            time.sleep(self.interval)
        return results

    def batch_download(self, codes: List[str], ktypes: List[str] = None,
                       incremental: bool = True) -> dict:
        """批量下载多只股票的K线数据"""
        results = {}
        for code in codes:
            logger.info(f"========== 批量下载: {code} ==========")
            results[code] = self.download_all_types(code, ktypes, incremental)
            time.sleep(self.interval * 2)
        return results
