#!/usr/bin/env python3
"""
中证A500 ETF 分钟线数据批量采集脚本

用法:
1. 确保 Futu OpenD 已启动
2. 在项目根目录运行: python -m scripts.fetch_a500

采集标的: 主要中证A500 ETF（深交所+上交所）
采集周期: K_1M, K_5M, K_15M, K_60M, K_DAY
回看天数: 按 Futu API 上限
"""
import sys
import time
from pathlib import Path

from loguru import logger
from config import Config
from core.client import FutuClient
from downloaders.kline_downloader import KlineDownloader
from storage.database import Database

# ═══════════════════════════════════════════════
# 中证A500 ETF 标的列表（首批+二批 主要品种）
# ═══════════════════════════════════════════════
A500_ETFS = [
    # 深交所
    ("SZ.159338", "中证A500ETF(国泰, 规模最大)"),
    ("SZ.159361", "中证A500ETF(易方达)"),
    ("SZ.159352", "中证A500ETF(南方)"),
    ("SZ.159355", "中证A500ETF(招商)"),
    ("SZ.159339", "中证A500ETF(广发)"),
    # 上交所
    ("SH.512050", "中证A500ETF(国泰-上交所)"),
    ("SH.563360", "中证A500ETF(华泰柏瑞)"),
    ("SH.563220", "中证A500ETF(富国)"),
    ("SH.563800", "中证A500ETF(广发-上交所)"),
    ("SH.512370", "中证A500增强策略ETF(华夏)"),
    ("SH.563510", "中证A500红利低波ETF(易方达)"),
]

# 采集的K线周期及对应回看天数（Futu API 上限）
KLINE_CONFIGS = [
    ("K_1M", 90),     # 1分钟线: 最多90天
    ("K_5M", 180),    # 5分钟线: 最多180天
    ("K_15M", 365),   # 15分钟线: 最多365天
    ("K_60M", 730),   # 60分钟线: 最多730天
    ("K_DAY", 3650),  # 日线: 最多10年
]


def main():
    logger.info("=" * 60)
    logger.info("  中证A500 ETF 分钟线数据采集")
    logger.info("=" * 60)

    # 初始化
    project_root = Path(__file__).parent.parent
    config_path = str(project_root / "config" / "default.yaml")
    config = Config(config_path)

    db_path = config.get("storage", "sqlite_path")
    db = Database(db_path)

    host = config.get("opend", "host", default="127.0.0.1")
    port = config.get("opend", "port", default=11111)

    logger.info(f"连接 OpenD: {host}:{port}")
    client = FutuClient(host=host, port=port)
    client.connect_quote()

    downloader = KlineDownloader(client, db, config)

    # 采集统计
    total_records = 0
    results = {}

    for code, name in A500_ETFS:
        logger.info(f"\n{'='*50}")
        logger.info(f"采集: {code} ({name})")
        logger.info(f"{'='*50}")

        results[code] = {}

        for ktype, lookback in KLINE_CONFIGS:
            from datetime import datetime, timedelta
            start_date = (datetime.now() - timedelta(days=lookback)).strftime("%Y-%m-%d")
            end_date = datetime.now().strftime("%Y-%m-%d")

            logger.info(f"  {ktype}: {start_date} ~ {end_date} (回看{lookback}天)")

            try:
                count = downloader.download_history(
                    code=code,
                    ktype_str=ktype,
                    start_date=start_date,
                    end_date=end_date,
                    incremental=True
                )
                results[code][ktype] = count
                total_records += count
                logger.info(f"  {ktype}: 获取 {count} 条")
            except Exception as e:
                logger.error(f"  {ktype}: 失败 - {e}")
                results[code][ktype] = 0

            time.sleep(0.5)  # 频率限制

        time.sleep(1)  # 换股票间隔

    # 打印汇总
    logger.info(f"\n{'='*60}")
    logger.info(f"  采集完成 · 总计 {total_records:,} 条记录")
    logger.info(f"{'='*60}")

    for code, name in A500_ETFS:
        code_results = results.get(code, {})
        total = sum(code_results.values())
        detail = " | ".join([f"{k}:{v}" for k, v in code_results.items()])
        logger.info(f"  {code} ({name}): {total:,}条  [{detail}]")

    # 添加到监控列表
    for code, name in A500_ETFS:
        market = "SH" if code.startswith("SH.") else "SZ"
        config.add_to_watchlist(market, code)
    config.save()
    logger.info(f"\n已将 {len(A500_ETFS)} 只 A500 ETF 添加到监控列表")

    # 清理
    client.close()
    db.close()
    logger.info("完成，连接已关闭")


if __name__ == "__main__":
    main()
