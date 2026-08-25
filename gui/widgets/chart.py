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

        # 显示范围（用于缩放）
        self._visible_count = 120
        self._offset = 0

        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")

    def set_data(self, df: pd.DataFrame):
        """设置K线数据 (需含 open/high/low/close/volume/time_key)"""
        if df is None or df.empty:
            self._df = None
            self.update()
            return

        df = df.copy()
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["close"]).reset_index(drop=True)

        # 计算均线
        for p in self._ma_periods:
            df[f"ma{p}"] = df["close"].rolling(p, min_periods=1).mean()

        self._df = df
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
        if delta > 0:
            self._visible_count = max(20, int(self._visible_count * 0.85))
        else:
            self._visible_count = min(len(self._df), int(self._visible_count * 1.18))
        self._offset = max(0, min(self._offset, len(self._df) - self._visible_count))
        self.update()

    def mouseMoveEvent(self, event):
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

        # 布局: 上70% K线, 下30% 成交量
        margin_l, margin_r, margin_t, margin_b = 60, 70, 20, 30
        chart_w = w - margin_l - margin_r
        total_h = h - margin_t - margin_b
        k_h = int(total_h * 0.72)
        v_h = total_h - k_h - 10
        k_top = margin_t
        v_top = margin_t + k_h + 10

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
