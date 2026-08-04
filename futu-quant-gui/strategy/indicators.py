"""技术指标计算引擎 - 纯 pandas 实现，无外部 TA 库依赖"""
import pandas as pd
import numpy as np
from loguru import logger


class IndicatorEngine:
    """技术指标计算集合"""

    @staticmethod
    def ma(df, period=20, col="close"):
        """简单移动平均线 (SMA)"""
        return df[col].rolling(window=period, min_periods=1).mean()

    @staticmethod
    def ema(df, period=20, col="close"):
        """指数移动平均线 (EMA)"""
        return df[col].ewm(span=period, adjust=False).mean()

    @staticmethod
    def macd(df, fast=12, slow=26, signal=9, col="close"):
        """
        MACD 指标

        Returns:
            tuple: (dif, dea, macd_hist)
        """
        ema_fast = df[col].ewm(span=fast, adjust=False).mean()
        ema_slow = df[col].ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        macd_hist = 2 * (dif - dea)
        return dif, dea, macd_hist

    @staticmethod
    def rsi(df, period=14, col="close"):
        """RSI 相对强弱指标"""
        delta = df[col].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=period, min_periods=1).mean()
        avg_loss = loss.rolling(window=period, min_periods=1).mean()
        rs = avg_gain / avg_loss.replace(0, np.inf)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def kdj(df, n=9, m1=3, m2=3):
        """
        KDJ 随机指标

        Returns:
            tuple: (k, d, j)
        """
        low_n = df["low"].rolling(window=n, min_periods=1).min()
        high_n = df["high"].rolling(window=n, min_periods=1).max()
        denom = (high_n - low_n).replace(0, 1)
        rsv = (df["close"] - low_n) / denom * 100
        k = rsv.ewm(com=m1 - 1, adjust=False).mean()
        d = k.ewm(com=m2 - 1, adjust=False).mean()
        j = 3 * k - 2 * d
        return k, d, j

    @staticmethod
    def boll(df, period=20, std_n=2, col="close"):
        """
        布林带 (Bollinger Bands)

        Returns:
            tuple: (upper, mid, lower)
        """
        mid = df[col].rolling(window=period, min_periods=1).mean()
        std = df[col].rolling(window=period, min_periods=1).std()
        upper = mid + std_n * std
        lower = mid - std_n * std
        return upper, mid, lower

    @staticmethod
    def volume_ratio(df, period=5):
        """量比"""
        avg_vol = df["volume"].rolling(window=period, min_periods=1).mean()
        return df["volume"] / avg_vol.replace(0, 1)

    @staticmethod
    def atr(df, period=14):
        """平均真实波幅 (ATR)"""
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period, min_periods=1).mean()

    @staticmethod
    def cci(df, period=14):
        """顺势指标 (CCI)"""
        tp = (df["high"] + df["low"] + df["close"]) / 3
        ma = tp.rolling(window=period, min_periods=1).mean()
        md = tp.rolling(window=period, min_periods=1).apply(
            lambda x: np.abs(x - x.mean()).mean(), raw=True
        )
        md = md.replace(0, 1)
        return (tp - ma) / (0.015 * md)

    @staticmethod
    def obv(df):
        """能量潮 (OBV)"""
        direction = np.where(df["close"] > df["close"].shift(1), 1,
                    np.where(df["close"] < df["close"].shift(1), -1, 0))
        signed_vol = df["volume"] * direction
        return signed_vol.cumsum()
