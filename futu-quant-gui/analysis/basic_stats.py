"""
基础数据分析
提供数据质量检查、基本统计指标
"""
import pandas as pd
from typing import Optional
from loguru import logger


class BasicAnalyzer:
    """基础数据分析器"""

    def __init__(self, database):
        self.db = database

    def data_quality_check(self, code: str, ktype: str) -> dict:
        """数据质量检查"""
        df = self.db.get_kline(code, ktype)
        if df.empty:
            return {"status": "empty", "code": code, "ktype": ktype}

        report = {
            "code": code,
            "ktype": ktype,
            "total_records": len(df),
            "date_range": f"{df['time_key'].iloc[0]} ~ {df['time_key'].iloc[-1]}",
            "null_count": int(df.isnull().sum().sum()),
            "duplicate_count": int(df.duplicated(subset=["time_key"]).sum()),
        }

        # 检查价格异常
        if "close" in df.columns:
            close = df["close"].dropna()
            if len(close) > 1:
                pct_change = close.pct_change().dropna()
                report["max_daily_change"] = f"{pct_change.max():.2%}"
                report["min_daily_change"] = f"{pct_change.min():.2%}"
                report["price_range"] = f"{close.min():.2f} ~ {close.max():.2f}"
                # 检测异常跳价 (>20% 单根K线涨跌)
                anomalies = pct_change[pct_change.abs() > 0.2]
                report["anomaly_count"] = len(anomalies)

        if "volume" in df.columns:
            vol = df["volume"].dropna()
            report["avg_volume"] = f"{vol.mean():.0f}"
            report["zero_volume_count"] = int((vol == 0).sum())

        return report

    def get_summary(self, code: str, ktype: str = "K_DAY") -> dict:
        """获取股票数据摘要"""
        df = self.db.get_kline(code, ktype)
        if df.empty:
            return {}

        latest = df.iloc[-1]
        return {
            "code": code,
            "latest_close": latest.get("close"),
            "latest_time": latest.get("time_key"),
            "total_records": len(df),
            "change_rate": latest.get("change_rate"),
        }
