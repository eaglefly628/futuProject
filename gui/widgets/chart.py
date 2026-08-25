"""
K线图表组件 - 纯 QPainter 绘制，无额外依赖
支持: K线蜡烛图、成交量柱状图、均线叠加、十字光标
"""
from typing import List, Optional
import pandas as pd
import numpy as np

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import (QPainter, QPen, QBrush, QColor, QFont,
                           QFontMetrics, QPolygonF)

from gui.theme import COLORS


class KLineChart(QWidget):
    """K线蜡烛图 + 成交量 + 均线 + 指标副图

    性能设计：
      · 可见窗口的数据一次性转成 numpy 数组并缓存，绘制时不碰 pandas
      · 折线走 QPolygonF + drawPolyline，避免逐段 drawLine
      · 蜡烛数超过阈值时自动切成折线渲染
    """

    crosshair_moved = Signal(dict)  # 十字光标移动时发出当前K线数据

    # 超过这个数量就不画蜡烛，改画收盘价折线
    MAX_CANDLES = 1200

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

        self._df: Optional[pd.DataFrame] = None
        self._raw_df: Optional[pd.DataFrame] = None
        self._ma_periods = [5, 10, 20, 60]
        self._ma_colors = [
            QColor("#F0883E"),  # MA5  橙
            QColor("#58A6FF"),  # MA10 蓝
            QColor("#A371F7"),  # MA20 紫
            QColor("#D29922"),  # MA60 黄
        ]
        self._mouse_x = -1
        self._mouse_y = -1
        self._hover_idx = -1

        # 显示范围（缩放/平移）
        self._visible_count = 120
        self._offset = 0

        # 拖拽平移
        self._dragging = False
        self._drag_start_x = 0
        self._drag_start_offset = 0

        # 指标副图: None / "MACD" / "KDJ" / "RSI"
        self._indicator = None

        # 可见窗口的 numpy 缓存
        self._cache = None
        self._cache_key = None
        self._data_version = 0

        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        self.setCursor(Qt.CrossCursor)

    # ═══════════════════════════════════════
    #  数据
    # ═══════════════════════════════════════
    def set_data(self, df: pd.DataFrame):
        """设置K线数据 (需含 open/high/low/close/volume/time_key)"""
        if df is None or df.empty:
            self._df = None
            self._raw_df = None
            self._invalidate()
            self.update()
            return

        self._raw_df = df
        df = df.copy()
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["close"]).reset_index(drop=True)

        for p in self._ma_periods:
            df[f"ma{p}"] = df["close"].rolling(p, min_periods=1).mean()

        self._df = df
        self._compute_indicators()
        self._offset = max(0, len(df) - self._visible_count)
        self._invalidate()
        self.update()

    def set_indicator(self, name: Optional[str]):
        """设置副图指标: None / MACD / KDJ / RSI"""
        self._indicator = name if name in ("MACD", "KDJ", "RSI") else None
        if self._df is not None:
            self._compute_indicators()
        self._invalidate()
        self.update()

    def set_ma_periods(self, periods: List[int]):
        """设置均线周期"""
        self._ma_periods = [p for p in periods if p > 0][:4]
        if self._raw_df is not None:
            self.set_data(self._raw_df)

    def set_visible_count(self, n: int):
        """设置显示的K线数量"""
        if self._df is None:
            return
        self._visible_count = max(20, min(n, len(self._df)))
        self._offset = max(0, len(self._df) - self._visible_count)
        self._invalidate()
        self.update()

    def _invalidate(self):
        self._cache = None
        self._cache_key = None
        self._data_version += 1

    def _compute_indicators(self):
        """按需计算副图指标"""
        df = self._df
        if df is None or df.empty:
            return
        c = df["close"]

        if self._indicator == "MACD":
            ema12 = c.ewm(span=12, adjust=False).mean()
            ema26 = c.ewm(span=26, adjust=False).mean()
            df["_dif"] = ema12 - ema26
            df["_dea"] = df["_dif"].ewm(span=9, adjust=False).mean()
            df["_macd"] = 2 * (df["_dif"] - df["_dea"])

        elif self._indicator == "KDJ":
            low9 = df["low"].rolling(9, min_periods=1).min()
            high9 = df["high"].rolling(9, min_periods=1).max()
            rsv = (c - low9) / (high9 - low9).replace(0, np.nan) * 100
            rsv = rsv.fillna(50)
            df["_k"] = rsv.ewm(com=2, adjust=False).mean()
            df["_d"] = df["_k"].ewm(com=2, adjust=False).mean()
            df["_j"] = 3 * df["_k"] - 2 * df["_d"]

        elif self._indicator == "RSI":
            delta = c.diff()
            gain = delta.where(delta > 0, 0.0).rolling(14, min_periods=1).mean()
            loss = (-delta).where(delta < 0, 0.0).rolling(14, min_periods=1).mean()
            rs = gain / loss.replace(0, np.nan)
            df["_rsi"] = (100 - 100 / (1 + rs)).fillna(50)

    # ═══════════════════════════════════════
    #  可见窗口缓存（性能核心）
    # ═══════════════════════════════════════
    def _ensure_cache(self):
        """把可见窗口转成 numpy 数组并缓存，绘制期间不再触碰 pandas"""
        if self._df is None or self._df.empty:
            self._cache = None
            return

        start = max(0, self._offset)
        end = min(len(self._df), start + self._visible_count)
        key = (start, end, self._data_version, self._indicator)
        if self._cache_key == key and self._cache is not None:
            return

        dfv = self._df.iloc[start:end]
        if dfv.empty:
            self._cache = None
            self._cache_key = key
            return

        def arr(col):
            return dfv[col].to_numpy(dtype=float, copy=False) \
                if col in dfv.columns else None

        c = {
            "n": len(dfv),
            "open": arr("open"),
            "high": arr("high"),
            "low": arr("low"),
            "close": arr("close"),
            "volume": arr("volume") if "volume" in dfv.columns
                      else np.zeros(len(dfv)),
            "time": dfv["time_key"].astype(str).to_numpy()
                    if "time_key" in dfv.columns
                    else np.array([""] * len(dfv)),
            "ma": {},
            "ind": {},
        }

        for p in self._ma_periods:
            col = f"ma{p}"
            if col in dfv.columns:
                c["ma"][p] = arr(col)

        if self._indicator == "MACD":
            for k in ("_dif", "_dea", "_macd"):
                if k in dfv.columns:
                    c["ind"][k] = arr(k)
        elif self._indicator == "KDJ":
            for k in ("_k", "_d", "_j"):
                if k in dfv.columns:
                    c["ind"][k] = arr(k)
        elif self._indicator == "RSI":
            if "_rsi" in dfv.columns:
                c["ind"]["_rsi"] = arr("_rsi")

        # 价格区间（含均线）
        p_high = float(np.nanmax(c["high"]))
        p_low = float(np.nanmin(c["low"]))
        for a in c["ma"].values():
            if a is not None and np.isfinite(a).any():
                p_high = max(p_high, float(np.nanmax(a)))
                p_low = min(p_low, float(np.nanmin(a)))
        c["p_high"], c["p_low"] = p_high, p_low
        c["v_max"] = float(np.nanmax(c["volume"])) if c["volume"].size else 1.0

        self._cache = c
        self._cache_key = key

    # ═══════════════════════════════════════
    #  交互
    # ═══════════════════════════════════════
    def wheelEvent(self, event):
        if self._df is None:
            return
        delta = event.angleDelta().y()
        right_edge = self._offset + self._visible_count  # 缩放锚定右端
        if delta > 0:
            self._visible_count = max(20, int(self._visible_count * 0.85))
        else:
            self._visible_count = min(len(self._df), int(self._visible_count * 1.18))
        self._offset = max(0, min(right_edge - self._visible_count,
                                  len(self._df) - self._visible_count))
        self._cache_key = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._df is not None:
            self._dragging = True
            self._drag_start_x = event.position().x()
            self._drag_start_offset = self._offset
            self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.setCursor(Qt.CrossCursor)

    def mouseMoveEvent(self, event):
        if self._dragging and self._df is not None:
            w = self.width() - 130
            if w > 0 and self._visible_count > 0:
                bar_w = w / self._visible_count
                delta_bars = int((self._drag_start_x - event.position().x())
                                 / max(bar_w, 0.5))
                max_off = max(0, len(self._df) - self._visible_count)
                new_off = max(0, min(max_off, self._drag_start_offset + delta_bars))
                if new_off != self._offset:
                    self._offset = new_off
                    self._cache_key = None
            self.update()
            return

        self._mouse_x = event.position().x()
        self._mouse_y = event.position().y()

        self._ensure_cache()
        c = self._cache
        if c:
            margin_l, margin_r = 60, 70
            chart_w = self.width() - margin_l - margin_r
            if chart_w > 0:
                rel = (self._mouse_x - margin_l) / chart_w
                idx = int(rel * c["n"])
                if 0 <= idx < c["n"]:
                    self._hover_idx = idx
                    self.crosshair_moved.emit({
                        "time": str(c["time"][idx]),
                        "open": float(c["open"][idx]),
                        "high": float(c["high"][idx]),
                        "low": float(c["low"][idx]),
                        "close": float(c["close"][idx]),
                        "volume": float(c["volume"][idx]),
                    })
                else:
                    self._hover_idx = -1
        self.update()

    def leaveEvent(self, event):
        self._mouse_x = -1
        self._mouse_y = -1
        self._hover_idx = -1
        self.update()

    # ═══════════════════════════════════════
    #  绘制
    # ═══════════════════════════════════════
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)  # 关抗锯齿，大量图元时更快

        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(COLORS["bg_card"]))

        self._ensure_cache()
        c = self._cache
        if not c or c["n"] == 0:
            painter.setPen(QColor(COLORS["text_muted"]))
            painter.setFont(QFont("PingFang SC", 13))
            painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter,
                             "暂无数据\n请先采集K线数据")
            return

        margin_l, margin_r, margin_t, margin_b = 60, 70, 20, 30
        chart_w = w - margin_l - margin_r
        total_h = h - margin_t - margin_b
        gap = 10
        if chart_w <= 0 or total_h <= 0:
            return

        if self._indicator:
            k_h = int(total_h * 0.54)
            v_h = int(total_h * 0.20)
            i_h = total_h - k_h - v_h - gap * 2
        else:
            k_h = int(total_h * 0.72)
            v_h = total_h - k_h - gap
            i_h = 0

        k_top = margin_t
        v_top = k_top + k_h + gap
        i_top = v_top + v_h + gap

        n = c["n"]
        bar_w = chart_w / n
        candle_w = max(1.0, bar_w * 0.7)

        p_high, p_low = c["p_high"], c["p_low"]
        p_range = p_high - p_low
        if p_range <= 0:
            p_range = abs(p_high) * 0.01 or 1.0
        p_high += p_range * 0.05
        p_low -= p_range * 0.05
        p_range = p_high - p_low

        def price_to_y(price):
            return k_top + (p_high - price) / p_range * k_h

        v_max = c["v_max"] or 1.0

        # ─── 网格 ───
        grid_pen = QPen(QColor(COLORS["border"]), 1, Qt.DotLine)
        painter.setFont(QFont("Menlo", 9))
        for i in range(5):
            y = k_top + i * k_h / 4
            painter.setPen(grid_pen)
            painter.drawLine(int(margin_l), int(y), int(w - margin_r), int(y))
            painter.setPen(QColor(COLORS["text_secondary"]))
            painter.drawText(QRectF(0, y - 8, margin_l - 6, 16),
                             Qt.AlignRight | Qt.AlignVCenter,
                             f"{p_high - (i / 4) * p_range:.3f}")

        for i in range(3):
            y = v_top + i * v_h / 2
            painter.setPen(grid_pen)
            painter.drawLine(int(margin_l), int(y), int(w - margin_r), int(y))
        painter.setPen(QColor(COLORS["text_secondary"]))
        painter.drawText(QRectF(0, v_top - 8, margin_l - 6, 16),
                         Qt.AlignRight | Qt.AlignVCenter, f"{v_max / 10000:.0f}万")

        o, hi, lo, cl, vol = c["open"], c["high"], c["low"], c["close"], c["volume"]
        green = QColor(COLORS["green"])
        red = QColor(COLORS["red"])
        dense = n > self.MAX_CANDLES

        if dense:
            # 数据过密：收盘价折线 + 成交量折线，避免几万个图元
            poly = QPolygonF()
            for i in range(n):
                poly.append(QPointF(margin_l + i * bar_w + bar_w / 2,
                                    price_to_y(cl[i])))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(COLORS["accent"]), 1.2))
            painter.drawPolyline(poly)

            vpoly = QPolygonF()
            vpoly.append(QPointF(margin_l, v_top + v_h))
            for i in range(n):
                vpoly.append(QPointF(margin_l + i * bar_w + bar_w / 2,
                                     v_top + v_h - (vol[i] / v_max) * v_h))
            vpoly.append(QPointF(margin_l + chart_w, v_top + v_h))
            fill = QColor(COLORS["accent"])
            fill.setAlpha(60)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(fill))
            painter.drawPolygon(vpoly)
        else:
            # 蜡烛：按涨跌分两批，减少画笔切换
            up_mask = cl >= o
            for mask, color in ((up_mask, green), (~up_mask, red)):
                idxs = np.nonzero(mask)[0]
                if idxs.size == 0:
                    continue
                painter.setPen(QPen(color, 1))
                painter.setBrush(QBrush(color))
                for i in idxs:
                    x = margin_l + i * bar_w + bar_w / 2
                    painter.drawLine(QPointF(x, price_to_y(hi[i])),
                                     QPointF(x, price_to_y(lo[i])))
                    y_top = price_to_y(max(o[i], cl[i]))
                    y_bot = price_to_y(min(o[i], cl[i]))
                    painter.drawRect(QRectF(x - candle_w / 2, y_top,
                                            candle_w, max(1.0, y_bot - y_top)))

                vcolor = QColor(color)
                vcolor.setAlpha(160)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(vcolor))
                for i in idxs:
                    x = margin_l + i * bar_w + bar_w / 2
                    vh = (vol[i] / v_max) * v_h
                    painter.drawRect(QRectF(x - candle_w / 2, v_top + v_h - vh,
                                            candle_w, vh))

        # ─── 均线 ───
        painter.setBrush(Qt.NoBrush)
        for pi, period in enumerate(self._ma_periods):
            a = c["ma"].get(period)
            if a is None:
                continue
            poly = QPolygonF()
            for i in range(n):
                v = a[i]
                if not np.isfinite(v):
                    continue
                poly.append(QPointF(margin_l + i * bar_w + bar_w / 2, price_to_y(v)))
            if poly.count() > 1:
                painter.setPen(QPen(self._ma_colors[pi % len(self._ma_colors)], 1.5))
                painter.drawPolyline(poly)

        # ─── 均线图例 ───
        painter.setFont(QFont("Menlo", 9))
        legend_x = margin_l + 8
        legend_y = k_top + 14
        for pi, period in enumerate(self._ma_periods):
            a = c["ma"].get(period)
            if a is None or not np.isfinite(a[-1]):
                continue
            painter.setPen(self._ma_colors[pi % len(self._ma_colors)])
            text = f"MA{period}:{a[-1]:.3f}"
            painter.drawText(int(legend_x), int(legend_y), text)
            legend_x += QFontMetrics(painter.font()).horizontalAdvance(text) + 14

        if dense:
            painter.setPen(QColor(COLORS["text_muted"]))
            painter.drawText(int(legend_x), int(legend_y),
                             f"[{n:,}根 · 折线模式，滚轮放大看蜡烛]")

        # ─── 指标副图 ───
        if self._indicator and i_h > 20:
            self._paint_indicator(painter, c, margin_l, chart_w,
                                  i_top, i_h, bar_w, candle_w, w, margin_r)

        # ─── 十字光标 ───
        if 0 <= self._hover_idx < n and self._mouse_x > margin_l:
            painter.setPen(QPen(QColor(COLORS["text_secondary"]), 1, Qt.DashLine))
            x = margin_l + self._hover_idx * bar_w + bar_w / 2
            painter.drawLine(int(x), int(margin_t), int(x), int(h - margin_b))
            if margin_t <= self._mouse_y <= h - margin_b:
                painter.drawLine(int(margin_l), int(self._mouse_y),
                                 int(w - margin_r), int(self._mouse_y))
                if k_top <= self._mouse_y <= k_top + k_h:
                    price = p_high - (self._mouse_y - k_top) / k_h * p_range
                    painter.setBrush(QBrush(QColor(COLORS["accent"])))
                    painter.setPen(Qt.NoPen)
                    lr = QRectF(w - margin_r + 2, self._mouse_y - 10, margin_r - 6, 20)
                    painter.drawRect(lr)
                    painter.setPen(QColor("#000000"))
                    painter.setFont(QFont("Menlo", 9, QFont.Bold))
                    painter.drawText(lr, Qt.AlignCenter, f"{price:.3f}")

        # ─── 最新价标签 ───
        last_close = float(cl[-1])
        last_color = green if last_close >= float(o[-1]) else red
        y = price_to_y(last_close)
        painter.setBrush(QBrush(last_color))
        painter.setPen(Qt.NoPen)
        lrect = QRectF(w - margin_r + 2, y - 10, margin_r - 6, 20)
        painter.drawRect(lrect)
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Menlo", 9, QFont.Bold))
        painter.drawText(lrect, Qt.AlignCenter, f"{last_close:.3f}")

        # ─── 时间轴 ───
        painter.setPen(QColor(COLORS["text_secondary"]))
        painter.setFont(QFont("Menlo", 8))
        step = max(1, n // 6)
        times = c["time"]
        for i in range(0, n, step):
            x = margin_l + i * bar_w + bar_w / 2
            painter.drawText(QRectF(x - 44, h - margin_b + 4, 88, 16),
                             Qt.AlignCenter, str(times[i])[:16])

    # ═══════════════════════════════════════
    def _paint_indicator(self, painter, c, margin_l, chart_w,
                         top, height, bar_w, candle_w, w, margin_r):
        """绘制副图指标 (MACD / KDJ / RSI)"""
        n = c["n"]
        ind = self._indicator
        data = c["ind"]

        if ind == "MACD":
            series = [("_dif", "#F0883E", "DIF"), ("_dea", "#58A6FF", "DEA")]
            hist_key = "_macd"
        elif ind == "KDJ":
            series = [("_k", "#F0883E", "K"), ("_d", "#58A6FF", "D"),
                      ("_j", "#A371F7", "J")]
            hist_key = None
        else:
            series = [("_rsi", "#F0883E", "RSI")]
            hist_key = None

        present = [(k, col, lb) for k, col, lb in series if k in data]
        if not present:
            return

        stack = [data[k] for k, _, _ in present]
        if hist_key and hist_key in data:
            stack.append(data[hist_key])
        allv = np.concatenate([a[np.isfinite(a)] for a in stack
                               if a is not None and np.isfinite(a).any()]) \
            if stack else np.array([])
        if allv.size == 0:
            return

        v_max, v_min = float(allv.max()), float(allv.min())
        if ind == "RSI":
            v_max, v_min = 100.0, 0.0
        rng = v_max - v_min
        if rng <= 0:
            rng = 1.0
        v_max += rng * 0.1
        v_min -= rng * 0.1
        rng = v_max - v_min

        def to_y(val):
            return top + (v_max - val) / rng * height

        grid = QPen(QColor(COLORS["border"]), 1, Qt.DotLine)
        painter.setPen(grid)
        painter.drawLine(int(margin_l), int(top), int(w - margin_r), int(top))
        painter.drawLine(int(margin_l), int(top + height),
                         int(w - margin_r), int(top + height))

        if ind == "RSI":
            for lvl, col in ((70, COLORS["red"]), (30, COLORS["green"])):
                painter.setPen(QPen(QColor(col), 1, Qt.DotLine))
                y = to_y(lvl)
                painter.drawLine(int(margin_l), int(y), int(w - margin_r), int(y))
        elif v_min < 0 < v_max:
            painter.setPen(grid)
            y0 = to_y(0)
            painter.drawLine(int(margin_l), int(y0), int(w - margin_r), int(y0))

        # MACD 柱：按正负分两批
        if hist_key and hist_key in data:
            hist = data[hist_key]
            y0 = to_y(0)
            painter.setPen(Qt.NoPen)
            finite = np.isfinite(hist)
            for mask, color in ((finite & (hist >= 0), QColor(COLORS["green"])),
                                (finite & (hist < 0), QColor(COLORS["red"]))):
                idxs = np.nonzero(mask)[0]
                if idxs.size == 0:
                    continue
                painter.setBrush(QBrush(color))
                for i in idxs:
                    x = margin_l + i * bar_w + bar_w / 2
                    y = to_y(hist[i])
                    painter.drawRect(QRectF(x - candle_w / 2, min(y, y0),
                                            candle_w, max(1.0, abs(y - y0))))

        painter.setBrush(Qt.NoBrush)
        for key, color, _ in present:
            a = data[key]
            poly = QPolygonF()
            for i in range(n):
                v = a[i]
                if not np.isfinite(v):
                    continue
                poly.append(QPointF(margin_l + i * bar_w + bar_w / 2, to_y(v)))
            if poly.count() > 1:
                painter.setPen(QPen(QColor(color), 1.4))
                painter.drawPolyline(poly)

        painter.setFont(QFont("Menlo", 9))
        lx = margin_l + 8
        ly = top + 13
        painter.setPen(QColor(COLORS["text_secondary"]))
        painter.drawText(int(lx), int(ly), ind)
        lx += QFontMetrics(painter.font()).horizontalAdvance(ind) + 12
        for key, color, label in present:
            v = data[key][-1]
            if not np.isfinite(v):
                continue
            painter.setPen(QColor(color))
            text = f"{label}:{v:.2f}"
            painter.drawText(int(lx), int(ly), text)
            lx += QFontMetrics(painter.font()).horizontalAdvance(text) + 12


class MiniBarChart(QWidget):
    """迷你柱状图 - 用于因子评分展示"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self._data = {}  # {label: score(-100~100)}
        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")

    def set_data(self, data: dict):
        self._data = data or {}
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(COLORS["bg_card"]))

        if not self._data:
            painter.setPen(QColor(COLORS["text_muted"]))
            painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "暂无因子数据")
            return

        n = len(self._data)
        margin_l, margin_r, margin_t, margin_b = 10, 10, 16, 26
        chart_w = w - margin_l - margin_r
        chart_h = h - margin_t - margin_b
        bar_slot = chart_w / n
        bar_w = bar_slot * 0.55

        mid_y = margin_t + chart_h / 2

        # 零轴
        painter.setPen(QPen(QColor(COLORS["border"]), 1, Qt.DashLine))
        painter.drawLine(int(margin_l), int(mid_y), int(w - margin_r), int(mid_y))

        painter.setFont(QFont("PingFang SC", 8))
        labels_cn = {
            "ma_system": "均线",
            "volume_price": "量价",
            "momentum": "动量",
            "volatility": "波动",
            "regression": "回归",
        }

        for i, (key, score) in enumerate(self._data.items()):
            score = max(-100, min(100, float(score)))
            x = margin_l + i * bar_slot + (bar_slot - bar_w) / 2
            bar_h = abs(score) / 100 * (chart_h / 2)

            if score >= 0:
                y = mid_y - bar_h
                color = QColor(COLORS["green"])
            else:
                y = mid_y
                color = QColor(COLORS["red"])

            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRect(QRectF(x, y, bar_w, max(1, bar_h)))

            # 数值
            painter.setPen(QColor(COLORS["text_primary"]))
            painter.setFont(QFont("Menlo", 8))
            val_y = y - 4 if score >= 0 else y + bar_h + 12
            painter.drawText(QRectF(x - 8, val_y - 10, bar_w + 16, 14),
                            Qt.AlignCenter, f"{score:.0f}")

            # 标签
            painter.setPen(QColor(COLORS["text_secondary"]))
            painter.setFont(QFont("PingFang SC", 8))
            painter.drawText(QRectF(x - 8, h - margin_b + 4, bar_w + 16, 16),
                            Qt.AlignCenter, labels_cn.get(key, key))


class GaugeWidget(QWidget):
    """评分仪表盘 - 半圆形"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 120)
        self._score = 50
        self._label = "综合评分"
        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")

    def set_score(self, score: float, label: str = "综合评分"):
        self._score = max(0, min(100, float(score)))
        self._label = label
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(COLORS["bg_card"]))

        cx, cy = w / 2, h - 22
        radius = min(w / 2 - 16, h - 40)

        # 背景弧
        pen = QPen(QColor(COLORS["border"]), 12, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        painter.drawArc(rect, 180 * 16, -180 * 16)

        # 评分弧
        if self._score >= 70:
            color = QColor(COLORS["green"])
        elif self._score >= 45:
            color = QColor(COLORS["yellow"])
        else:
            color = QColor(COLORS["red"])

        pen = QPen(color, 12, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        span = int(self._score / 100 * 180)
        painter.drawArc(rect, 180 * 16, -span * 16)

        # 中心数值
        painter.setPen(color)
        painter.setFont(QFont("Menlo", 26, QFont.Bold))
        painter.drawText(QRectF(0, cy - 44, w, 40), Qt.AlignCenter, f"{self._score:.0f}")

        painter.setPen(QColor(COLORS["text_secondary"]))
        painter.setFont(QFont("PingFang SC", 9))
        painter.drawText(QRectF(0, h - 20, w, 16), Qt.AlignCenter, self._label)
