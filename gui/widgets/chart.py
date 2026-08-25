"""
K线图表组件 - 纯 QPainter 绘制，无额外依赖
支持: K线蜡烛图、成交量柱状图、均线叠加、十字光标
"""
from typing import List, Optional
import pandas as pd
import numpy as np

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QFontMetrics

from gui.theme import COLORS


class KLineChart(QWidget):
    """K线蜡烛图 + 成交量 + 均线"""

    crosshair_moved = Signal(dict)  # 十字光标移动时发出当前K线数据

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

        self._df: Optional[pd.DataFrame] = None
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

        # 显示范围（用于缩放/平移）
        self._visible_count = 120
        self._offset = 0

        # 拖拽平移
        self._dragging = False
        self._drag_start_x = 0
        self._drag_start_offset = 0

        # 指标副图: None / "MACD" / "KDJ" / "RSI"
        self._indicator = None

        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        self.setCursor(Qt.CrossCursor)

    def set_indicator(self, name: Optional[str]):
        """设置副图指标: None / MACD / KDJ / RSI"""
        self._indicator = name if name in ("MACD", "KDJ", "RSI") else None
        if self._df is not None:
            self._compute_indicators()
        self.update()

    def set_ma_periods(self, periods: List[int]):
        """设置均线周期"""
        self._ma_periods = [p for p in periods if p > 0][:4]
        if self._df is not None:
            self.set_data(self._raw_df)

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

    def set_data(self, df: pd.DataFrame):
        """设置K线数据 (需含 open/high/low/close/volume/time_key)"""
        if df is None or df.empty:
            self._df = None
            self.update()
            return

        self._raw_df = df
        df = df.copy()
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["close"]).reset_index(drop=True)

        # 计算均线
        for p in self._ma_periods:
            df[f"ma{p}"] = df["close"].rolling(p, min_periods=1).mean()

        self._df = df
        self._compute_indicators()
        self._offset = max(0, len(df) - self._visible_count)
        self.update()

    def set_visible_count(self, n: int):
        """设置显示的K线数量"""
        if self._df is None:
            return
        self._visible_count = max(20, min(n, len(self._df)))
        self._offset = max(0, len(self._df) - self._visible_count)
        self.update()

    def _visible_df(self) -> Optional[pd.DataFrame]:
        if self._df is None or self._df.empty:
            return None
        start = max(0, self._offset)
        end = min(len(self._df), start + self._visible_count)
        return self._df.iloc[start:end]

    def wheelEvent(self, event):
        """滚轮缩放"""
        if self._df is None:
            return
        delta = event.angleDelta().y()
        right_edge = self._offset + self._visible_count  # 缩放时锚定右端
        if delta > 0:
            self._visible_count = max(20, int(self._visible_count * 0.85))
        else:
            self._visible_count = min(len(self._df), int(self._visible_count * 1.18))
        self._offset = max(0, min(right_edge - self._visible_count,
                                  len(self._df) - self._visible_count))
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
        # 拖拽平移
        if self._dragging and self._df is not None:
            w = self.width() - 130
            if w > 0 and self._visible_count > 0:
                bar_w = w / self._visible_count
                delta_bars = int((self._drag_start_x - event.position().x()) / max(bar_w, 0.5))
                max_off = max(0, len(self._df) - self._visible_count)
                self._offset = max(0, min(max_off, self._drag_start_offset + delta_bars))
            self.update()
            return

        self._mouse_x = event.position().x()
        self._mouse_y = event.position().y()

        dfv = self._visible_df()
        if dfv is not None and len(dfv) > 0:
            w = self.width()
            margin_l, margin_r = 60, 70
            chart_w = w - margin_l - margin_r
            if chart_w > 0:
                rel = (self._mouse_x - margin_l) / chart_w
                idx = int(rel * len(dfv))
                if 0 <= idx < len(dfv):
                    self._hover_idx = idx
                    row = dfv.iloc[idx]
                    self.crosshair_moved.emit({
                        "time": str(row.get("time_key", "")),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row.get("volume", 0)),
                    })
                else:
                    self._hover_idx = -1
        self.update()

    def leaveEvent(self, event):
        self._mouse_x = -1
        self._mouse_y = -1
        self._hover_idx = -1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        bg = QColor(COLORS["bg_card"])
        painter.fillRect(0, 0, w, h, bg)

        dfv = self._visible_df()
        if dfv is None or len(dfv) == 0:
            painter.setPen(QColor(COLORS["text_muted"]))
            painter.setFont(QFont("PingFang SC", 13))
            painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter,
                            "暂无数据\n请先采集K线数据")
            return

        # 布局: K线 / 成交量 / 指标副图
        margin_l, margin_r, margin_t, margin_b = 60, 70, 20, 30
        chart_w = w - margin_l - margin_r
        total_h = h - margin_t - margin_b
        gap = 10

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

        n = len(dfv)
        if n == 0 or chart_w <= 0:
            return

        bar_w = chart_w / n
        candle_w = max(1.0, bar_w * 0.7)

        # 价格范围
        p_high = float(dfv["high"].max())
        p_low = float(dfv["low"].min())
        # 均线也要纳入范围
        for p in self._ma_periods:
            col = f"ma{p}"
            if col in dfv.columns:
                vals = dfv[col].dropna()
                if len(vals) > 0:
                    p_high = max(p_high, float(vals.max()))
                    p_low = min(p_low, float(vals.min()))

        p_range = p_high - p_low
        if p_range <= 0:
            p_range = p_high * 0.01 if p_high > 0 else 1
        p_high += p_range * 0.05
        p_low -= p_range * 0.05
        p_range = p_high - p_low

        def price_to_y(price):
            return k_top + (p_high - price) / p_range * k_h

        # 成交量范围
        v_max = float(dfv["volume"].max()) if "volume" in dfv.columns else 1
        if v_max <= 0:
            v_max = 1

        def vol_to_h(vol):
            return (vol / v_max) * v_h

        # ─── 网格线 ───
        grid_pen = QPen(QColor(COLORS["border"]), 1, Qt.DotLine)
        painter.setPen(grid_pen)
        painter.setFont(QFont("Menlo", 9))

        for i in range(5):
            y = k_top + i * k_h / 4
            painter.setPen(grid_pen)
            painter.drawLine(int(margin_l), int(y), int(w - margin_r), int(y))
            price = p_high - (i / 4) * p_range
            painter.setPen(QColor(COLORS["text_secondary"]))
            painter.drawText(QRectF(0, y - 8, margin_l - 6, 16),
                            Qt.AlignRight | Qt.AlignVCenter, f"{price:.3f}")

        # 成交量网格
        for i in range(3):
            y = v_top + i * v_h / 2
            painter.setPen(grid_pen)
            painter.drawLine(int(margin_l), int(y), int(w - margin_r), int(y))
        painter.setPen(QColor(COLORS["text_secondary"]))
        painter.drawText(QRectF(0, v_top - 8, margin_l - 6, 16),
                        Qt.AlignRight | Qt.AlignVCenter, f"{v_max/10000:.0f}万")

        # ─── K线蜡烛 ───
        green = QColor(COLORS["green"])
        red = QColor(COLORS["red"])

        for i in range(n):
            row = dfv.iloc[i]
            o, hi, lo, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            x_center = margin_l + i * bar_w + bar_w / 2

            up = c >= o
            color = green if up else red

            # 影线
            painter.setPen(QPen(color, 1))
            painter.drawLine(QPointF(x_center, price_to_y(hi)),
                            QPointF(x_center, price_to_y(lo)))

            # 实体
            y_top = price_to_y(max(o, c))
            y_bot = price_to_y(min(o, c))
            body_h = max(1.0, y_bot - y_top)

            rect = QRectF(x_center - candle_w / 2, y_top, candle_w, body_h)
            if up:
                painter.setPen(QPen(color, 1))
                painter.setBrush(QBrush(color))
            else:
                painter.setPen(QPen(color, 1))
                painter.setBrush(QBrush(color))
            painter.drawRect(rect)

            # 成交量柱
            if "volume" in row:
                vol = float(row["volume"])
                vh = vol_to_h(vol)
                vrect = QRectF(x_center - candle_w / 2, v_top + v_h - vh, candle_w, vh)
                vcolor = QColor(color)
                vcolor.setAlpha(160)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(vcolor))
                painter.drawRect(vrect)

        # ─── 均线 ───
        painter.setBrush(Qt.NoBrush)
        for pi, period in enumerate(self._ma_periods):
            col = f"ma{period}"
            if col not in dfv.columns:
                continue
            pen = QPen(self._ma_colors[pi % len(self._ma_colors)], 1.5)
            painter.setPen(pen)
            points = []
            for i in range(n):
                val = dfv.iloc[i][col]
                if pd.isna(val):
                    continue
                x = margin_l + i * bar_w + bar_w / 2
                points.append(QPointF(x, price_to_y(float(val))))
            if len(points) > 1:
                for i in range(len(points) - 1):
                    painter.drawLine(points[i], points[i + 1])

        # ─── 均线图例 ───
        painter.setFont(QFont("Menlo", 9))
        legend_x = margin_l + 8
        legend_y = k_top + 14
        last = dfv.iloc[-1]
        for pi, period in enumerate(self._ma_periods):
            col = f"ma{period}"
            if col not in dfv.columns:
                continue
            val = last[col]
            if pd.isna(val):
                continue
            painter.setPen(self._ma_colors[pi % len(self._ma_colors)])
            text = f"MA{period}:{float(val):.3f}"
            painter.drawText(int(legend_x), int(legend_y), text)
            legend_x += QFontMetrics(painter.font()).horizontalAdvance(text) + 14

        # ─── 指标副图 ───
        if self._indicator and i_h > 20:
            self._paint_indicator(painter, dfv, margin_l, chart_w,
                                  i_top, i_h, bar_w, candle_w, w, margin_r)

        # ─── 十字光标 ───
        if 0 <= self._hover_idx < n and self._mouse_x > margin_l:
            cross_pen = QPen(QColor(COLORS["text_secondary"]), 1, Qt.DashLine)
            painter.setPen(cross_pen)
            x = margin_l + self._hover_idx * bar_w + bar_w / 2
            painter.drawLine(int(x), int(margin_t), int(x), int(h - margin_b))
            if margin_t <= self._mouse_y <= h - margin_b:
                painter.drawLine(int(margin_l), int(self._mouse_y),
                                int(w - margin_r), int(self._mouse_y))
                # 右侧价格标签
                if k_top <= self._mouse_y <= k_top + k_h:
                    price = p_high - (self._mouse_y - k_top) / k_h * p_range
                    painter.setBrush(QBrush(QColor(COLORS["accent"])))
                    painter.setPen(Qt.NoPen)
                    label_rect = QRectF(w - margin_r + 2, self._mouse_y - 10, margin_r - 6, 20)
                    painter.drawRect(label_rect)
                    painter.setPen(QColor("#000000"))
                    painter.setFont(QFont("Menlo", 9, QFont.Bold))
                    painter.drawText(label_rect, Qt.AlignCenter, f"{price:.3f}")

        # ─── 最新价标签 ───
        last_close = float(dfv.iloc[-1]["close"])
        last_open = float(dfv.iloc[-1]["open"])
        last_color = green if last_close >= last_open else red
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
        for i in range(0, n, step):
            row = dfv.iloc[i]
            tk = str(row.get("time_key", ""))[:10]
            x = margin_l + i * bar_w + bar_w / 2
            painter.drawText(QRectF(x - 40, h - margin_b + 4, 80, 16),
                            Qt.AlignCenter, tk)

    # ═══════════════════════════════════════
    def _paint_indicator(self, painter, dfv, margin_l, chart_w,
                         top, height, bar_w, candle_w, w, margin_r):
        """绘制副图指标 (MACD / KDJ / RSI)"""
        n = len(dfv)
        ind = self._indicator

        if ind == "MACD":
            series = [("_dif", "#F0883E", "DIF"), ("_dea", "#58A6FF", "DEA")]
            hist_col = "_macd"
        elif ind == "KDJ":
            series = [("_k", "#F0883E", "K"), ("_d", "#58A6FF", "D"),
                      ("_j", "#A371F7", "J")]
            hist_col = None
        else:  # RSI
            series = [("_rsi", "#F0883E", "RSI")]
            hist_col = None

        cols = [c for c, _, _ in series if c in dfv.columns]
        if not cols:
            return

        vals = pd.concat([dfv[c] for c in cols]).dropna()
        if hist_col and hist_col in dfv.columns:
            vals = pd.concat([vals, dfv[hist_col].dropna()])
        if vals.empty:
            return

        v_max, v_min = float(vals.max()), float(vals.min())
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

        # 边框 + 零轴/参考线
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

        # MACD 柱
        if hist_col and hist_col in dfv.columns:
            y0 = to_y(0)
            painter.setPen(Qt.NoPen)
            for i in range(n):
                v = dfv.iloc[i][hist_col]
                if pd.isna(v):
                    continue
                v = float(v)
                x = margin_l + i * bar_w + bar_w / 2
                y = to_y(v)
                color = QColor(COLORS["green"] if v >= 0 else COLORS["red"])
                painter.setBrush(QBrush(color))
                painter.drawRect(QRectF(x - candle_w / 2, min(y, y0),
                                        candle_w, max(1.0, abs(y - y0))))

        # 指标线
        painter.setBrush(Qt.NoBrush)
        for col, color, _ in series:
            if col not in dfv.columns:
                continue
            painter.setPen(QPen(QColor(color), 1.4))
            pts = []
            for i in range(n):
                v = dfv.iloc[i][col]
                if pd.isna(v):
                    continue
                pts.append(QPointF(margin_l + i * bar_w + bar_w / 2, to_y(float(v))))
            for i in range(len(pts) - 1):
                painter.drawLine(pts[i], pts[i + 1])

        # 图例
        painter.setFont(QFont("Menlo", 9))
        lx = margin_l + 8
        ly = top + 13
        last = dfv.iloc[-1]
        painter.setPen(QColor(COLORS["text_secondary"]))
        painter.drawText(int(lx), int(ly), ind)
        lx += QFontMetrics(painter.font()).horizontalAdvance(ind) + 12
        for col, color, label in series:
            if col not in dfv.columns or pd.isna(last[col]):
                continue
            painter.setPen(QColor(color))
            text = f"{label}:{float(last[col]):.2f}"
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
