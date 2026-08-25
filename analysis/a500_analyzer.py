#!/usr/bin/env python3
"""
中证A500 量价分析与概率性趋势预测

分析维度:
1. 多周期成交量结构分析（1M/5M/15M/60M/DAY）
2. 量价背离/共振检测
3. 资金流向推断（主力大单 vs 散户）
4. 基于统计学的中长期走势概率预测
5. 关键支撑/阻力位计算

用法:
    python analysis/a500_analyzer.py SZ.159338
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent

from loguru import logger


@dataclass
class TrendPrediction:
    """趋势预测结果"""
    direction: str  # "bullish" / "bearish" / "neutral"
    confidence: float  # 0.0 ~ 1.0
    target_price: float
    support_price: float
    resistance_price: float
    timeframe: str  # "short" / "medium" / "long"
    signals: List[str] = field(default_factory=list)
    risk_level: str = "medium"  # "low" / "medium" / "high"


class A500Analyzer:
    """中证A500 ETF 量价分析器"""

    def __init__(self, db):
        self.db = db

    def full_analysis(self, code: str) -> dict:
        """完整分析报告"""
        logger.info(f"开始分析: {code}")

        # 加载各周期数据
        df_day = self._load_kline(code, "K_DAY")
        df_60m = self._load_kline(code, "K_60M")
        df_15m = self._load_kline(code, "K_15M")
        df_5m = self._load_kline(code, "K_5M")
        df_1m = self._load_kline(code, "K_1M")

        if df_day is None or len(df_day) < 20:
            return {"error": f"{code} 日线数据不足（需要至少20条）"}

        report = {
            "code": code,
            "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "latest_price": float(df_day["close"].iloc[-1]),
            "data_coverage": {
                "K_DAY": len(df_day) if df_day is not None else 0,
                "K_60M": len(df_60m) if df_60m is not None else 0,
                "K_15M": len(df_15m) if df_15m is not None else 0,
                "K_5M": len(df_5m) if df_5m is not None else 0,
                "K_1M": len(df_1m) if df_1m is not None else 0,
            },
        }

        # 1. 成交量结构分析
        report["volume_analysis"] = self.analyze_volume_structure(df_day, df_60m)

        # 2. 量价关系
        report["volume_price"] = self.analyze_volume_price_relation(df_day)

        # 3. 技术形态
        report["technicals"] = self.compute_technicals(df_day)

        # 4. 支撑阻力
        report["levels"] = self.compute_support_resistance(df_day)

        # 5. 中长期趋势预测
        report["prediction_medium"] = self.predict_trend(df_day, "medium")
        report["prediction_long"] = self.predict_trend(df_day, "long")

        # 6. 综合评分
        report["score"] = self.compute_composite_score(report)

        return report

    def _load_kline(self, code: str, ktype: str) -> Optional[pd.DataFrame]:
        """加载K线数据"""
        df = self.db.get_kline(code, ktype)
        if df.empty:
            return None
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["close"]).sort_values("time_key").reset_index(drop=True)
        return df

    # ═══════════════════════════════════════════
    #  1. 成交量结构分析
    # ═══════════════════════════════════════════
    def analyze_volume_structure(self, df_day: pd.DataFrame,
                                  df_60m: Optional[pd.DataFrame]) -> dict:
        """分析成交量结构特征"""
        vol = df_day["volume"].values
        close = df_day["close"].values

        # 近期量能变化
        vol_5 = np.mean(vol[-5:])
        vol_20 = np.mean(vol[-20:])
        vol_60 = np.mean(vol[-min(60, len(vol)):])
        vol_ratio_5_20 = vol_5 / vol_20 if vol_20 > 0 else 1.0
        vol_ratio_5_60 = vol_5 / vol_60 if vol_60 > 0 else 1.0

        # 量能趋势（线性回归斜率）
        recent_vol = vol[-20:]
        x = np.arange(len(recent_vol))
        if len(recent_vol) > 1:
            slope = np.polyfit(x, recent_vol, 1)[0]
            vol_trend = "increasing" if slope > 0 else "decreasing"
        else:
            slope = 0
            vol_trend = "flat"

        # 放量/缩量判断
        if vol_ratio_5_20 > 1.5:
            vol_status = "显著放量"
        elif vol_ratio_5_20 > 1.2:
            vol_status = "温和放量"
        elif vol_ratio_5_20 < 0.6:
            vol_status = "显著缩量"
        elif vol_ratio_5_20 < 0.8:
            vol_status = "温和缩量"
        else:
            vol_status = "量能平稳"

        # 日内量能分布（如果有60分钟数据）
        intraday_pattern = None
        if df_60m is not None and len(df_60m) >= 4:
            recent_60m = df_60m.tail(20)
            if "time_key" in recent_60m.columns:
                recent_60m = recent_60m.copy()
                recent_60m["hour"] = pd.to_datetime(recent_60m["time_key"]).dt.hour
                hourly_vol = recent_60m.groupby("hour")["volume"].mean()
                if len(hourly_vol) > 0:
                    peak_hour = hourly_vol.idxmax()
                    intraday_pattern = {
                        "peak_hour": int(peak_hour),
                        "hourly_distribution": {str(k): round(float(v), 0) for k, v in hourly_vol.items()},
                    }

        return {
            "vol_5d_avg": round(float(vol_5), 0),
            "vol_20d_avg": round(float(vol_20), 0),
            "vol_60d_avg": round(float(vol_60), 0),
            "vol_ratio_5_20": round(float(vol_ratio_5_20), 3),
            "vol_ratio_5_60": round(float(vol_ratio_5_60), 3),
            "vol_status": vol_status,
            "vol_trend": vol_trend,
            "vol_trend_slope": round(float(slope), 2),
            "intraday_pattern": intraday_pattern,
        }

    # ═══════════════════════════════════════════
    #  2. 量价关系分析
    # ═══════════════════════════════════════════
    def analyze_volume_price_relation(self, df: pd.DataFrame) -> dict:
        """分析量价背离/共振"""
        close = df["close"].values
        volume = df["volume"].values
        n = min(20, len(df))

        # 价格趋势
        price_change_20 = (close[-1] - close[-n]) / close[-n] * 100
        price_trend = "up" if price_change_20 > 1 else "down" if price_change_20 < -1 else "flat"

        # 成交量趋势
        vol_first_half = np.mean(volume[-n:-n//2]) if n > 2 else volume[-1]
        vol_second_half = np.mean(volume[-n//2:]) if n > 2 else volume[-1]
        vol_change = (vol_second_half - vol_first_half) / vol_first_half * 100 if vol_first_half > 0 else 0

        # 量价关系判断
        if price_trend == "up" and vol_change > 10:
            vp_relation = "量价齐升（健康上涨）"
            vp_signal = "bullish"
        elif price_trend == "up" and vol_change < -10:
            vp_relation = "价涨量缩（顶背离警告）"
            vp_signal = "bearish_divergence"
        elif price_trend == "down" and vol_change > 10:
            vp_relation = "价跌量增（恐慌抛售或主力吸筹）"
            vp_signal = "neutral"
        elif price_trend == "down" and vol_change < -10:
            vp_relation = "价跌量缩（下跌动能衰竭）"
            vp_signal = "bullish_divergence"
        else:
            vp_relation = "量价平稳"
            vp_signal = "neutral"

        # OBV 能量潮
        obv = [0.0]
        for i in range(1, len(close)):
            if close[i] > close[i-1]:
                obv.append(obv[-1] + volume[i])
            elif close[i] < close[i-1]:
                obv.append(obv[-1] - volume[i])
            else:
                obv.append(obv[-1])
        obv = np.array(obv)

        # OBV 趋势
        obv_recent = obv[-20:]
        if len(obv_recent) > 1:
            obv_slope = np.polyfit(np.arange(len(obv_recent)), obv_recent, 1)[0]
            obv_trend = "up" if obv_slope > 0 else "down"
        else:
            obv_slope = 0
            obv_trend = "flat"

        return {
            "price_change_20d": round(float(price_change_20), 2),
            "price_trend": price_trend,
            "vol_change_pct": round(float(vol_change), 2),
            "vp_relation": vp_relation,
            "vp_signal": vp_signal,
            "obv_trend": obv_trend,
        }

    # ═══════════════════════════════════════════
    #  3. 技术指标
    # ═══════════════════════════════════════════
    def compute_technicals(self, df: pd.DataFrame) -> dict:
        """计算主要技术指标"""
        close = df["close"]
        high = df["high"]
        low = df["low"]

        # 均线
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()

        # 均线多头/空头排列
        latest = close.iloc[-1]
        ma_values = {
            "MA5": float(ma5.iloc[-1]) if not np.isnan(ma5.iloc[-1]) else None,
            "MA10": float(ma10.iloc[-1]) if not np.isnan(ma10.iloc[-1]) else None,
            "MA20": float(ma20.iloc[-1]) if not np.isnan(ma20.iloc[-1]) else None,
            "MA60": float(ma60.iloc[-1]) if len(df) >= 60 and not np.isnan(ma60.iloc[-1]) else None,
        }

        ma_list = [v for v in [ma_values.get("MA5"), ma_values.get("MA10"),
                                ma_values.get("MA20"), ma_values.get("MA60")] if v is not None]
        if len(ma_list) >= 3:
            if ma_list == sorted(ma_list, reverse=True):
                ma_arrangement = "多头排列（强势）"
            elif ma_list == sorted(ma_list):
                ma_arrangement = "空头排列（弱势）"
            else:
                ma_arrangement = "交叉缠绕（震荡）"
        else:
            ma_arrangement = "数据不足"

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_hist = 2 * (dif - dea)

        macd_signal = "golden_cross" if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2] else \
                      "dead_cross" if dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2] else \
                      "above_zero" if dif.iloc[-1] > 0 else "below_zero"

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta).where(delta < 0, 0.0).rolling(14).mean()
        rs = gain / loss.replace(0, np.inf)
        rsi = 100 - (100 / (1 + rs))
        rsi_val = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50

        # KDJ
        low_9 = low.rolling(9).min()
        high_9 = high.rolling(9).max()
        rsv = (close - low_9) / (high_9 - low_9).replace(0, 1) * 100
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        j = 3 * k - 2 * d

        # BOLL
        boll_mid = close.rolling(20).mean()
        boll_std = close.rolling(20).std()
        boll_upper = boll_mid + 2 * boll_std
        boll_lower = boll_mid - 2 * boll_std

        boll_position = "above_upper" if latest > boll_upper.iloc[-1] else \
                        "below_lower" if latest < boll_lower.iloc[-1] else \
                        "upper_half" if latest > boll_mid.iloc[-1] else "lower_half"

        return {
            "ma_values": ma_values,
            "ma_arrangement": ma_arrangement,
            "price_vs_ma20": round(float((latest - ma20.iloc[-1]) / ma20.iloc[-1] * 100), 2) if not np.isnan(ma20.iloc[-1]) else None,
            "macd": {
                "dif": round(float(dif.iloc[-1]), 4),
                "dea": round(float(dea.iloc[-1]), 4),
                "hist": round(float(macd_hist.iloc[-1]), 4),
                "signal": macd_signal,
            },
            "rsi_14": round(rsi_val, 2),
            "rsi_zone": "超买" if rsi_val > 70 else "超卖" if rsi_val < 30 else "中性",
            "kdj": {
                "k": round(float(k.iloc[-1]), 2),
                "d": round(float(d.iloc[-1]), 2),
                "j": round(float(j.iloc[-1]), 2),
            },
            "boll": {
                "upper": round(float(boll_upper.iloc[-1]), 4),
                "mid": round(float(boll_mid.iloc[-1]), 4),
                "lower": round(float(boll_lower.iloc[-1]), 4),
                "position": boll_position,
            },
        }

    # ═══════════════════════════════════════════
    #  4. 支撑阻力位
    # ═══════════════════════════════════════════
    def compute_support_resistance(self, df: pd.DataFrame, lookback: int = 60) -> dict:
        """基于成交密集区计算支撑阻力"""
        df_recent = df.tail(lookback)
        close = df_recent["close"].values
        volume = df_recent["volume"].values
        high = df_recent["high"].values
        low = df_recent["low"].values
        latest = close[-1]

        # 成交量加权价格分布
        price_min = float(np.min(low))
        price_max = float(np.max(high))
        n_bins = 50
        bins = np.linspace(price_min, price_max, n_bins + 1)
        vol_profile = np.zeros(n_bins)

        for i in range(len(close)):
            bin_idx = int((close[i] - price_min) / (price_max - price_min) * (n_bins - 1))
            bin_idx = max(0, min(bin_idx, n_bins - 1))
            vol_profile[bin_idx] += volume[i]

        # 找最大成交量价格区（价值区）
        peak_bin = np.argmax(vol_profile)
        poc_price = (bins[peak_bin] + bins[peak_bin + 1]) / 2  # Point of Control

        # 支撑位：当前价格下方成交密集区
        support_bins = [i for i in range(n_bins) if bins[i+1] < latest and vol_profile[i] > np.mean(vol_profile)]
        support = float((bins[support_bins[-1]] + bins[support_bins[-1]+1]) / 2) if support_bins else float(np.min(low[-20:]))

        # 阻力位：当前价格上方成交密集区
        resist_bins = [i for i in range(n_bins) if bins[i] > latest and vol_profile[i] > np.mean(vol_profile)]
        resistance = float((bins[resist_bins[0]] + bins[resist_bins[0]+1]) / 2) if resist_bins else float(np.max(high[-20:]))

        return {
            "poc_price": round(poc_price, 4),
            "support_1": round(support, 4),
            "resistance_1": round(resistance, 4),
            "recent_high": round(float(np.max(high[-20:])), 4),
            "recent_low": round(float(np.min(low[-20:])), 4),
        }

    # ═══════════════════════════════════════════
    #  5. 概率性趋势预测
    # ═══════════════════════════════════════════
    def predict_trend(self, df: pd.DataFrame, timeframe: str = "medium") -> dict:
        """
        基于多因子的概率性趋势预测

        中期: 未来 20-60 个交易日
        长期: 未来 60-120 个交易日

        因子权重:
        - 均线系统 25%
        - 量价关系 25%
        - 动量指标 20%
        - 波动率结构 15%
        - 统计回归 15%
        """
        close = df["close"].values
        volume = df["volume"].values
        latest = close[-1]

        if timeframe == "medium":
            lookback = 60
            forecast_days = "20-60个交易日"
        else:
            lookback = 120
            forecast_days = "60-120个交易日"

        scores = {}
        signals = []

        # ─── 因子1: 均线系统 (权重 25%) ───
        ma20 = np.mean(close[-20:])
        ma60 = np.mean(close[-min(60, len(close)):])
        ma120 = np.mean(close[-min(120, len(close)):])

        ma_score = 0
        if latest > ma20:
            ma_score += 30
            signals.append("价格在MA20上方")
        else:
            ma_score -= 30
            signals.append("价格在MA20下方")

        if latest > ma60:
            ma_score += 20
        else:
            ma_score -= 20

        if ma20 > ma60:
            ma_score += 25
            signals.append("MA20 > MA60 中期多头")
        else:
            ma_score -= 25
            signals.append("MA20 < MA60 中期空头")

        # 均线斜率
        ma20_5ago = np.mean(close[-25:-5]) if len(close) > 25 else ma20
        if ma20 > ma20_5ago:
            ma_score += 25
        else:
            ma_score -= 25

        scores["ma_system"] = max(-100, min(100, ma_score))

        # ─── 因子2: 量价关系 (权重 25%) ───
        vp_score = 0
        vol_recent = np.mean(volume[-5:])
        vol_avg = np.mean(volume[-20:])
        price_up = close[-1] > close[-5]

        if price_up and vol_recent > vol_avg:
            vp_score += 50
            signals.append("量价齐升")
        elif price_up and vol_recent < vol_avg * 0.8:
            vp_score -= 20
            signals.append("价涨量缩（背离）")
        elif not price_up and vol_recent < vol_avg * 0.7:
            vp_score += 30
            signals.append("缩量回调（健康调整）")
        elif not price_up and vol_recent > vol_avg * 1.3:
            vp_score -= 40
            signals.append("放量下跌（警惕）")

        # OBV 确认
        obv_change = sum([volume[i] if close[i] > close[i-1] else -volume[i]
                         for i in range(max(len(close)-20, 1), len(close))])
        if obv_change > 0:
            vp_score += 25
        else:
            vp_score -= 25

        scores["volume_price"] = max(-100, min(100, vp_score))

        # ─── 因子3: 动量指标 (权重 20%) ───
        momentum_score = 0

        # RSI
        delta = pd.Series(close).diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta).where(delta < 0, 0.0).rolling(14).mean()
        rs = gain / loss.replace(0, np.inf)
        rsi = (100 - (100 / (1 + rs))).iloc[-1]

        if 40 < rsi < 60:
            momentum_score += 10
        elif rsi > 70:
            momentum_score -= 30
            signals.append(f"RSI超买({rsi:.0f})")
        elif rsi < 30:
            momentum_score += 40
            signals.append(f"RSI超卖({rsi:.0f})")
        elif rsi > 50:
            momentum_score += 20
        else:
            momentum_score -= 10

        # 价格动量（近期涨幅）
        ret_5 = (close[-1] / close[-5] - 1) * 100
        ret_20 = (close[-1] / close[-20] - 1) * 100

        if 0 < ret_20 < 10:
            momentum_score += 20
        elif ret_20 > 15:
            momentum_score -= 20
            signals.append(f"近20日涨幅过大({ret_20:.1f}%)")
        elif ret_20 < -10:
            momentum_score += 15
            signals.append(f"近20日跌幅较大({ret_20:.1f}%)，或有反弹")

        scores["momentum"] = max(-100, min(100, momentum_score))

        # ─── 因子4: 波动率结构 (权重 15%) ───
        vol_score = 0
        returns = np.diff(close) / close[:-1]
        vol_20 = np.std(returns[-20:]) * np.sqrt(252) * 100  # 年化波动率
        vol_60 = np.std(returns[-min(60, len(returns)):]) * np.sqrt(252) * 100

        if vol_20 < vol_60 * 0.7:
            vol_score += 30
            signals.append("波动率收敛（可能酝酿突破）")
        elif vol_20 > vol_60 * 1.5:
            vol_score -= 20
            signals.append("波动率放大（风险增加）")
        else:
            vol_score += 10

        scores["volatility"] = max(-100, min(100, vol_score))

        # ─── 因子5: 统计回归 (权重 15%) ───
        regression_score = 0

        # 均值回归概率
        mean_60 = np.mean(close[-min(60, len(close)):])
        deviation = (latest - mean_60) / mean_60 * 100

        if abs(deviation) < 2:
            regression_score += 10
        elif deviation > 5:
            regression_score -= 25
            signals.append(f"偏离60日均值 +{deviation:.1f}%，回归压力")
        elif deviation < -5:
            regression_score += 25
            signals.append(f"偏离60日均值 {deviation:.1f}%，回归动力")

        # 历史波动率分位
        if len(returns) >= 60:
            current_vol = np.std(returns[-20:])
            historical_vols = [np.std(returns[i:i+20]) for i in range(0, len(returns)-20, 5)]
            if historical_vols:
                vol_percentile = sum(1 for v in historical_vols if v < current_vol) / len(historical_vols) * 100
                if vol_percentile < 20:
                    regression_score += 20
                    signals.append("波动率处于历史低位")
                elif vol_percentile > 80:
                    regression_score -= 15

        scores["regression"] = max(-100, min(100, regression_score))

        # ─── 综合评分 ───
        weights = {
            "ma_system": 0.25,
            "volume_price": 0.25,
            "momentum": 0.20,
            "volatility": 0.15,
            "regression": 0.15,
        }

        composite = sum(scores[k] * weights[k] for k in weights)
        # 转换为概率 (sigmoid-like)
        prob_up = 1 / (1 + np.exp(-composite / 30))

        if prob_up > 0.65:
            direction = "看涨"
            risk = "低" if prob_up > 0.75 else "中"
        elif prob_up < 0.35:
            direction = "看跌"
            risk = "低" if prob_up < 0.25 else "中"
        else:
            direction = "震荡"
            risk = "中"

        # 目标价估算
        avg_daily_return = np.mean(returns[-60:])
        daily_std = np.std(returns[-60:])
        forecast_n = 40 if timeframe == "medium" else 90

        target_up = latest * (1 + avg_daily_return * forecast_n + daily_std * forecast_n**0.5)
        target_down = latest * (1 + avg_daily_return * forecast_n - daily_std * forecast_n**0.5)

        return {
            "timeframe": forecast_days,
            "direction": direction,
            "probability_up": round(float(prob_up), 3),
            "probability_down": round(float(1 - prob_up), 3),
            "risk_level": risk,
            "target_up": round(float(target_up), 4),
            "target_down": round(float(target_down), 4),
            "composite_score": round(float(composite), 2),
            "factor_scores": {k: round(float(v), 2) for k, v in scores.items()},
            "signals": signals[:8],
        }

    # ═══════════════════════════════════════════
    #  6. 综合评分
    # ═══════════════════════════════════════════
    def compute_composite_score(self, report: dict) -> dict:
        """基于所有分析生成综合评分"""
        score = 50  # 基准分

        # 量价关系
        vp = report.get("volume_price", {})
        if vp.get("vp_signal") == "bullish":
            score += 10
        elif vp.get("vp_signal") == "bearish_divergence":
            score -= 10
        elif vp.get("vp_signal") == "bullish_divergence":
            score += 5

        # 技术面
        tech = report.get("technicals", {})
        if "多头" in tech.get("ma_arrangement", ""):
            score += 10
        elif "空头" in tech.get("ma_arrangement", ""):
            score -= 10

        rsi = tech.get("rsi_14", 50)
        if rsi > 70:
            score -= 5
        elif rsi < 30:
            score += 5

        # 中期预测
        pred = report.get("prediction_medium", {})
        if pred.get("direction") == "看涨":
            score += 15
        elif pred.get("direction") == "看跌":
            score -= 15

        score = max(0, min(100, score))

        if score >= 70:
            recommendation = "积极买入"
        elif score >= 55:
            recommendation = "谨慎看多"
        elif score >= 45:
            recommendation = "观望等待"
        elif score >= 30:
            recommendation = "谨慎看空"
        else:
            recommendation = "建议回避"

        return {
            "total_score": score,
            "recommendation": recommendation,
        }


def print_report(report: dict):
    """格式化打印分析报告"""
    if "error" in report:
        print(f"\n❌ {report['error']}")
        return

    print(f"\n{'='*60}")
    print(f"  中证A500 ETF 量价分析报告")
    print(f"  标的: {report['code']}")
    print(f"  分析时间: {report['analysis_time']}")
    print(f"  最新价: {report['latest_price']}")
    print(f"{'='*60}")

    # 数据覆盖
    dc = report["data_coverage"]
    print(f"\n📊 数据覆盖:")
    for k, v in dc.items():
        print(f"   {k}: {v:,}条")

    # 成交量分析
    va = report["volume_analysis"]
    print(f"\n📈 成交量结构:")
    print(f"   5日均量: {va['vol_5d_avg']:,.0f}")
    print(f"   20日均量: {va['vol_20d_avg']:,.0f}")
    print(f"   量比(5/20): {va['vol_ratio_5_20']:.3f}")
    print(f"   状态: {va['vol_status']}")
    print(f"   趋势: {va['vol_trend']}")

    # 量价关系
    vp = report["volume_price"]
    print(f"\n🔄 量价关系:")
    print(f"   20日涨跌: {vp['price_change_20d']:.2f}%")
    print(f"   关系: {vp['vp_relation']}")
    print(f"   OBV趋势: {vp['obv_trend']}")

    # 技术面
    tech = report["technicals"]
    print(f"\n📐 技术指标:")
    print(f"   均线排列: {tech['ma_arrangement']}")
    print(f"   偏离MA20: {tech.get('price_vs_ma20', 'N/A')}%")
    print(f"   MACD: DIF={tech['macd']['dif']:.4f}, 信号={tech['macd']['signal']}")
    print(f"   RSI(14): {tech['rsi_14']:.1f} ({tech['rsi_zone']})")
    print(f"   BOLL位置: {tech['boll']['position']}")

    # 支撑阻力
    lvl = report["levels"]
    print(f"\n🎯 支撑阻力:")
    print(f"   阻力位: {lvl['resistance_1']}")
    print(f"   主力成本: {lvl['poc_price']}")
    print(f"   支撑位: {lvl['support_1']}")

    # 中期预测
    for label, key in [("中期", "prediction_medium"), ("长期", "prediction_long")]:
        pred = report.get(key, {})
        if pred:
            print(f"\n🔮 {label}趋势预测 ({pred['timeframe']}):")
            print(f"   方向: {pred['direction']}")
            print(f"   上涨概率: {pred['probability_up']*100:.1f}%")
            print(f"   下跌概率: {pred['probability_down']*100:.1f}%")
            print(f"   风险等级: {pred['risk_level']}")
            print(f"   乐观目标: {pred['target_up']}")
            print(f"   悲观目标: {pred['target_down']}")
            print(f"   综合评分: {pred['composite_score']}")
            if pred.get("signals"):
                print(f"   信号:")
                for s in pred["signals"]:
                    print(f"     · {s}")

    # 综合评分
    sc = report["score"]
    print(f"\n{'='*60}")
    print(f"  综合评分: {sc['total_score']}/100")
    print(f"  建议: {sc['recommendation']}")
    print(f"{'='*60}")


def cli_main():
    """命令行入口"""
    code = sys.argv[1] if len(sys.argv) > 1 else "SZ.159338"

    config_path = str(PROJECT_ROOT / "config" / "default.yaml")
    from config import Config
    config = Config(config_path)
    from storage.database import Database
    db = Database(config.get("storage", "sqlite_path"))

    analyzer = A500Analyzer(db)
    report = analyzer.full_analysis(code)
    print_report(report)
    db.close()


if __name__ == "__main__":
    cli_main()

    db.close()
