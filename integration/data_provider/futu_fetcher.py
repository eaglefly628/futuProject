# -*- coding: utf-8 -*-
"""
===================================
FutuFetcher - Futu OpenD 数据源
===================================

数据来源：Futu OpenD 本地网关（通过 futu-api SDK）
特点：
1. 支持 A股/港股/美股 统一接口
2. 本地客户端，无封禁风险
3. 实时行情毫秒级延迟
4. 数据质量高（来自交易所直连）

前提条件：
1. 安装 futu-api: pip install futu-api
2. 运行 Futu OpenD 客户端（默认 127.0.0.1:11111）

配置项（.env）：
- FUTU_ENABLED=true          # 是否启用
- FUTU_OPEND_HOST=127.0.0.1  # OpenD 主机
- FUTU_OPEND_PORT=11111      # OpenD 端口
- FUTU_PRIORITY=-1           # 优先级（默认最高）

集成方式：
将此文件复制到 daily_stock_analysis_eagle/data_provider/ 目录下即可。
"""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import pandas as pd

from .base import (
    BaseFetcher,
    DataFetchError,
    STANDARD_COLUMNS,
    normalize_stock_code,
    _is_hk_market,
    _is_us_market,
)
from .realtime_types import (
    UnifiedRealtimeQuote,
    RealtimeSource,
    safe_float,
    safe_int,
)

logger = logging.getLogger(__name__)

# 尝试导入 futu-api
try:
    from futu import (
        OpenQuoteContext,
        RET_OK,
        KLType,
        KL_FIELD,
        AuType,
        SubType,
        Market,
    )
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    logger.debug("futu-api 未安装，FutuFetcher 不可用。安装: pip install futu-api")


def _to_futu_code(stock_code: str) -> str:
    """
    将标准化股票代码转换为 Futu API 格式。

    标准化格式 → Futu 格式:
    - '600519'   → 'SH.600519'
    - '000001'   → 'SZ.000001'
    - 'HK00700'  → 'HK.00700'
    - 'AAPL'     → 'US.AAPL'
    - '300750'   → 'SZ.300750'
    """
    code = normalize_stock_code(stock_code).strip()

    # 已经是 Futu 格式 (如 SH.600519)
    if '.' in code and code.split('.')[0] in ('SH', 'SZ', 'HK', 'US'):
        return code

    # 港股: HK00700 → HK.00700
    if code.upper().startswith('HK'):
        digits = code[2:]
        return f"HK.{digits}"

    # 美股: 纯字母
    if _is_us_market(code):
        return f"US.{code}"

    # A股: 根据代码规则判断交易所
    if code.isdigit() and len(code) == 6:
        # 上海: 6xx, 9xx, 5xx(ETF)
        if code.startswith(('6', '9', '5')):
            return f"SH.{code}"
        # 深圳: 0xx, 3xx, 1xx(ETF), 2xx
        return f"SZ.{code}"

    # 兜底
    return code


def _from_futu_code(futu_code: str) -> str:
    """
    将 Futu 代码转换回标准化格式。

    Futu 格式 → 标准化格式:
    - 'SH.600519' → '600519'
    - 'HK.00700'  → 'HK00700'
    - 'US.AAPL'   → 'AAPL'
    """
    if '.' not in futu_code:
        return futu_code
    prefix, digits = futu_code.split('.', 1)
    prefix = prefix.upper()
    if prefix in ('SH', 'SZ'):
        return digits
    if prefix == 'HK':
        return f"HK{digits}"
    if prefix == 'US':
        return digits
    return futu_code


class FutuFetcher(BaseFetcher):
    """
    Futu OpenD 数据源

    通过本地 OpenD 网关获取行情数据，支持 A股/港股/美股。
    需要 Futu OpenD 客户端运行在本地或可达的网络地址。
    """

    name = "FutuFetcher"

    def __init__(self):
        env_priority = os.environ.get("FUTU_PRIORITY")
        self.priority = int(env_priority) if env_priority else -1

        self._host = os.environ.get("FUTU_OPEND_HOST", "127.0.0.1")
        self._port = int(os.environ.get("FUTU_OPEND_PORT", "11111"))
        self._ctx: Optional["OpenQuoteContext"] = None
        self._available = FUTU_AVAILABLE
        self._connect_failed = False

        if not FUTU_AVAILABLE:
            logger.info("FutuFetcher: futu-api 未安装，已禁用")

    def _get_ctx(self) -> "OpenQuoteContext":
        """获取或创建 OpenQuoteContext（懒连接）"""
        if self._ctx is not None:
            return self._ctx
        if not self._available:
            raise DataFetchError("futu-api 未安装")
        if self._connect_failed:
            raise DataFetchError("FutuFetcher: OpenD 连接此前失败，跳过")
        try:
            self._ctx = OpenQuoteContext(host=self._host, port=self._port)
            logger.info(f"FutuFetcher: 已连接 OpenD -> {self._host}:{self._port}")
            return self._ctx
        except Exception as e:
            self._connect_failed = True
            raise DataFetchError(f"FutuFetcher: 无法连接 OpenD ({self._host}:{self._port}): {e}")

    def _close_ctx(self):
        """关闭连接"""
        if self._ctx is not None:
            try:
                self._ctx.close()
            except Exception:
                pass
            self._ctx = None

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        通过 Futu OpenD 获取日K线数据。

        Args:
            stock_code: 标准化股票代码 (如 '600519', 'HK00700', 'AAPL')
            start_date: 开始日期 'YYYY-MM-DD'
            end_date: 结束日期 'YYYY-MM-DD'

        Returns:
            原始 K线 DataFrame
        """
        futu_code = _to_futu_code(stock_code)
        ctx = self._get_ctx()

        all_data = []
        page_req_key = None
        max_retries = 3

        while True:
            retry_count = 0
            while retry_count < max_retries:
                try:
                    ret, data, page_req_key = ctx.request_history_kline(
                        code=futu_code,
                        ktype=KLType.K_DAY,
                        start=start_date,
                        end=end_date,
                        max_count=1000,
                        autype=AuType.QFQ,
                        fields=[KL_FIELD.ALL],
                        page_req_key=page_req_key,
                    )
                    if ret == RET_OK:
                        break
                    retry_count += 1
                    logger.warning(f"FutuFetcher: 请求失败 ({futu_code}): {data}, 重试 {retry_count}/{max_retries}")
                    time.sleep(0.5 * retry_count)
                except Exception as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        raise DataFetchError(f"FutuFetcher: 获取 {futu_code} K线异常: {e}")
                    time.sleep(0.5 * retry_count)

            if ret != RET_OK:
                raise DataFetchError(f"FutuFetcher: 获取 {futu_code} K线失败: {data}")

            if data is not None and not data.empty:
                all_data.append(data)

            # 无更多分页
            if page_req_key is None:
                break
            time.sleep(0.3)  # Futu API 频率限制

        if not all_data:
            raise DataFetchError(f"FutuFetcher: {futu_code} 无数据 ({start_date} ~ {end_date})")

        result = pd.concat(all_data, ignore_index=True)
        logger.info(f"FutuFetcher: {futu_code} 获取 {len(result)} 条日K数据")
        return result

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        标准化 Futu K线数据列名。

        Futu 返回列: time_key, open, close, high, low, volume, turnover,
                     pe_ratio, turnover_rate, change_rate, last_close, ...

        标准化为: date, open, high, low, close, volume, amount, pct_chg
        """
        column_map = {
            'time_key': 'date',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume',
            'turnover': 'amount',
            'change_rate': 'pct_chg',
        }

        df = df.rename(columns=column_map)

        # 确保标准列存在
        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = 0.0

        # 只保留标准列
        df = df[STANDARD_COLUMNS].copy()

        # 日期格式化
        df['date'] = pd.to_datetime(df['date'])

        # 数值类型
        for col in ['open', 'high', 'low', 'close', 'amount', 'pct_chg']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).astype(int)

        return df.sort_values('date').reset_index(drop=True)

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取实时行情报价。

        通过 Futu 订阅接口获取实时报价，包含量比、换手率、PE、PB 等。
        """
        futu_code = _to_futu_code(stock_code)
        try:
            ctx = self._get_ctx()

            # 订阅实时报价
            ret, err = ctx.subscribe([futu_code], [SubType.QUOTE])
            if ret != RET_OK:
                logger.warning(f"FutuFetcher: 订阅 {futu_code} 失败: {err}")
                return None

            # 获取快照
            ret, data = ctx.get_stock_quote([futu_code])
            if ret != RET_OK or data is None or data.empty:
                logger.warning(f"FutuFetcher: 获取 {futu_code} 报价失败")
                return None

            row = data.iloc[0]

            quote = UnifiedRealtimeQuote(
                code=normalize_stock_code(stock_code),
                name=str(row.get('stock_name', '')),
                source=RealtimeSource.FALLBACK,  # 无专用枚举，用 FALLBACK
                price=safe_float(row.get('last_price')),
                change_pct=safe_float(row.get('price_spread')),
                change_amount=safe_float(row.get('price_spread')),
                volume=safe_int(row.get('volume')),
                amount=safe_float(row.get('turnover')),
                volume_ratio=safe_float(row.get('volume_ratio')),
                turnover_rate=safe_float(row.get('turnover_rate')),
                amplitude=safe_float(row.get('amplitude')),
                open_price=safe_float(row.get('open_price')),
                high=safe_float(row.get('high_price')),
                low=safe_float(row.get('low_price')),
                pre_close=safe_float(row.get('prev_close_price')),
                pe_ratio=safe_float(row.get('pe_ratio')),
                pb_ratio=safe_float(row.get('pb_ratio')),
                total_mv=safe_float(row.get('total_market_val')),
                circ_mv=safe_float(row.get('circular_market_val')),
            )

            return quote

        except DataFetchError:
            raise
        except Exception as e:
            logger.warning(f"FutuFetcher: 获取 {futu_code} 实时报价异常: {e}")
            return None

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """获取股票中文名称"""
        futu_code = _to_futu_code(stock_code)
        try:
            ctx = self._get_ctx()
            ret, data = ctx.get_stock_basicinfo(
                Market.HK if futu_code.startswith('HK.') else
                Market.US if futu_code.startswith('US.') else
                Market.SH if futu_code.startswith('SH.') else
                Market.SZ,
                stock_type=None,
                code_list=[futu_code],
            )
            if ret == RET_OK and data is not None and not data.empty:
                return str(data.iloc[0].get('name', ''))
        except Exception as e:
            logger.debug(f"FutuFetcher: 获取 {futu_code} 名称失败: {e}")
        return None

    def get_main_indices(self, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
        """
        获取主要指数行情。

        仅支持有限指数，其他数据源可能更全面。
        """
        index_map = {
            "cn": [
                ("SH.000001", "上证指数"),
                ("SH.000300", "沪深300"),
                ("SZ.399001", "深证成指"),
                ("SZ.399006", "创业板指"),
            ],
            "hk": [
                ("HK.800000", "恒生指数"),
            ],
            "us": [
                ("US.DJI", "道琼斯"),
                ("US.IXIC", "纳斯达克"),
                ("US.INX", "标普500"),
            ],
        }

        codes = index_map.get(region, index_map["cn"])
        futu_codes = [c[0] for c in codes]

        try:
            ctx = self._get_ctx()
            ret, err = ctx.subscribe(futu_codes, [SubType.QUOTE])
            if ret != RET_OK:
                return None

            ret, data = ctx.get_stock_quote(futu_codes)
            if ret != RET_OK or data is None or data.empty:
                return None

            results = []
            for _, row in data.iterrows():
                results.append({
                    "code": _from_futu_code(str(row.get('code', ''))),
                    "name": str(row.get('stock_name', '')),
                    "current": safe_float(row.get('last_price'), 0.0),
                    "change": safe_float(row.get('price_spread'), 0.0),
                    "change_pct": safe_float(row.get('amplitude'), 0.0),
                    "volume": safe_int(row.get('volume'), 0),
                    "amount": safe_float(row.get('turnover'), 0.0),
                })
            return results
        except Exception as e:
            logger.debug(f"FutuFetcher: 获取指数行情失败: {e}")
            return None

    def __del__(self):
        """析构时关闭连接"""
        self._close_ctx()
