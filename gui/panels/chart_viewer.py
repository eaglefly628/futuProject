"""
行情图表 - 通用K线看图工具

浏览数据库里已下载的所有标的，传统股票软件式的看图体验：
蜡烛图 + 均线 + 成交量 + 指标副图，滚轮缩放、拖拽平移、十字光标
"""
from typing import Optional

import pandas as pd

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QSplitter, QFrame, QLineEdit,
    QAbstractItemView, QHeaderView, QCheckBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from gui.panels.base import BasePanel
from gui.widgets.chart import KLineChart
from gui.theme import COLORS

KTYPE_LABELS = [
    ("K_1M", "1分钟"), ("K_5M", "5分钟"), ("K_15M", "15分钟"),
    ("K_30M", "30分钟"), ("K_60M", "60分钟"),
    ("K_DAY", "日线"), ("K_WEEK", "周线"), ("K_MON", "月线"),
]

MARKET_NAMES = {"SH": "上海", "SZ": "深圳", "HK": "香港", "US": "美股"}


class ChartViewerPanel(BasePanel):
    """通用行情图表"""

    def __init__(self, main_window):
        super().__init__(main_window, "行情图表",
                         "浏览已下载数据 · 蜡烛图 / 均线 / 成交量 / 指标")
        self._current_code = None
        self._current_ktype = "K_DAY"
        self._build()

    # ═══════════════════════════════════════
    def _build(self):
        splitter = QSplitter(Qt.Horizontal)

        # ── 左：标的列表 ──
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 8, 0)
        lv.setSpacing(8)

        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("筛选代码...")
        self._filter_input.textChanged.connect(self._apply_filter)
        lv.addWidget(self._filter_input)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["标的", "周期数", "条数"])
        self._tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tree.setAlternatingRowColors(True)
        self._tree.itemClicked.connect(self._on_tree_click)
        self._tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tree.setColumnWidth(1, 60)
        self._tree.setColumnWidth(2, 80)
        lv.addWidget(self._tree, 1)

        refresh_btn = self.make_primary_btn("🔄 刷新列表", self._reload_symbols)
        lv.addWidget(refresh_btn)

        left.setMinimumWidth(240)
        left.setMaximumWidth(340)
        splitter.addWidget(left)

        # ── 右：图表 ──
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)

        # 工具栏
        bar = QHBoxLayout()
        bar.setSpacing(10)

        self._title_label = QLabel("未选择标的")
        self._title_label.setStyleSheet(
            f"color:{COLORS['text_primary']}; font-size:15px; font-weight:bold;")
        bar.addWidget(self._title_label)

        bar.addSpacing(16)
        bar.addWidget(QLabel("周期:"))
        self._ktype_combo = QComboBox()
        for kt, label in KTYPE_LABELS:
            self._ktype_combo.addItem(label, kt)
        self._ktype_combo.setCurrentIndex(5)
        self._ktype_combo.currentIndexChanged.connect(self._on_ktype_changed)
        bar.addWidget(self._ktype_combo)

        bar.addWidget(QLabel("指标:"))
        self._ind_combo = QComboBox()
        self._ind_combo.addItem("无", None)
        for name in ("MACD", "KDJ", "RSI"):
            self._ind_combo.addItem(name, name)
        self._ind_combo.currentIndexChanged.connect(self._on_indicator_changed)
        bar.addWidget(self._ind_combo)

        bar.addStretch()
        self._count_label = QLabel()
        self._count_label.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:12px;")
        bar.addWidget(self._count_label)
        rv.addLayout(bar)

        # OHLC 信息条
        info = QFrame()
        info.setObjectName("card")
        il = QHBoxLayout(info)
        il.setContentsMargins(14, 6, 14, 6)
        il.setSpacing(18)
        self._ohlc = {}
        for key, label in [("time", "时间"), ("open", "开"), ("high", "高"),
                           ("low", "低"), ("close", "收"), ("chg", "涨跌"),
                           ("volume", "量")]:
            lbl = QLabel(f"{label} --")
            lbl.setStyleSheet(
                f"color:{COLORS['text_secondary']}; font-family:Menlo,Consolas,monospace; font-size:12px;")
            il.addWidget(lbl)
            self._ohlc[key] = lbl
        il.addStretch()
        hint = QLabel("滚轮缩放 · 拖拽平移")
        hint.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
        il.addWidget(hint)
        rv.addWidget(info)

        # 图表
        self._chart = KLineChart()
        self._chart.crosshair_moved.connect(self._on_crosshair)
        rv.addWidget(self._chart, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 900])

        self.add_widget(splitter)
        self._content_layout.setStretchFactor(splitter, 1)

    # ═══════════════════════════════════════
    def on_show(self):
        self._reload_symbols()

    def _reload_symbols(self):
        """从数据库读出所有已下载的标的"""
        self._tree.clear()
        try:
            stats = self._main.db.get_stats()
            detail = stats.get("kline_detail", [])
        except Exception:
            detail = []

        if not detail:
            item = QTreeWidgetItem(["暂无数据，请先采集", "", ""])
            item.setForeground(0, QColor(COLORS["text_muted"]))
            self._tree.addTopLevelItem(item)
            return

        # detail: (code, ktype, count, min_time, max_time)
        by_code = {}
        for row in detail:
            code, ktype, cnt = row[0], row[1], row[2]
            by_code.setdefault(code, {})[ktype] = cnt

        by_market = {}
        for code, kmap in by_code.items():
            market = code.split(".")[0] if "." in code else "其他"
            by_market.setdefault(market, {})[code] = kmap

        for market in sorted(by_market):
            label = MARKET_NAMES.get(market, market)
            total = sum(sum(k.values()) for k in by_market[market].values())
            parent = QTreeWidgetItem([f"{label} ({len(by_market[market])})",
                                      "", f"{total:,}"])
            parent.setForeground(0, QColor(COLORS["accent"]))
            f = parent.font(0); f.setBold(True); parent.setFont(0, f)

            for code in sorted(by_market[market]):
                kmap = by_market[market][code]
                child = QTreeWidgetItem([code, str(len(kmap)),
                                         f"{sum(kmap.values()):,}"])
                child.setData(0, Qt.UserRole, code)
                child.setData(1, Qt.UserRole, kmap)
                parent.addChild(child)

            self._tree.addTopLevelItem(parent)
            parent.setExpanded(True)

        self._apply_filter(self._filter_input.text())

    def _apply_filter(self, text: str):
        text = (text or "").strip().upper()
        for i in range(self._tree.topLevelItemCount()):
            parent = self._tree.topLevelItem(i)
            visible_children = 0
            for j in range(parent.childCount()):
                child = parent.child(j)
                code = child.data(0, Qt.UserRole) or ""
                match = (not text) or (text in code.upper())
                child.setHidden(not match)
                if match:
                    visible_children += 1
            parent.setHidden(visible_children == 0)

    def _on_tree_click(self, item, column):
        code = item.data(0, Qt.UserRole)
        if not code:
            return
        self._current_code = code

        # 只保留该标的实际有数据的周期
        kmap = item.data(1, Qt.UserRole) or {}
        self._ktype_combo.blockSignals(True)
        self._ktype_combo.clear()
        for kt, label in KTYPE_LABELS:
            if kt in kmap:
                self._ktype_combo.addItem(f"{label} ({kmap[kt]:,})", kt)
        if self._ktype_combo.count() == 0:
            for kt, label in KTYPE_LABELS:
                self._ktype_combo.addItem(label, kt)
        # 尽量保持当前周期
        idx = self._ktype_combo.findData(self._current_ktype)
        self._ktype_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._ktype_combo.blockSignals(False)

        self._current_ktype = self._ktype_combo.currentData()
        self._load_chart()

    def _on_ktype_changed(self):
        self._current_ktype = self._ktype_combo.currentData()
        self._load_chart()

    def _on_indicator_changed(self):
        self._chart.set_indicator(self._ind_combo.currentData())

    def _load_chart(self):
        if not self._current_code or not self._current_ktype:
            return
        try:
            df = self._main.db.get_kline(self._current_code, self._current_ktype)
        except Exception as e:
            self._count_label.setText(f"读取失败: {e}")
            return

        label = dict(KTYPE_LABELS).get(self._current_ktype, self._current_ktype)
        self._title_label.setText(f"{self._current_code}  ·  {label}")

        if df is None or df.empty:
            self._chart.set_data(None)
            self._count_label.setText("无数据")
            return

        self._chart.set_data(df)
        first = str(df["time_key"].iloc[0])[:16]
        last = str(df["time_key"].iloc[-1])[:16]
        self._count_label.setText(f"{len(df):,} 条  ·  {first} ~ {last}")

    def _on_crosshair(self, d: dict):
        self._ohlc["time"].setText(f"时间 {d['time'][:16]}")
        self._ohlc["open"].setText(f"开 {d['open']:.3f}")
        self._ohlc["high"].setText(f"高 {d['high']:.3f}")
        self._ohlc["low"].setText(f"低 {d['low']:.3f}")

        up = d["close"] >= d["open"]
        color = COLORS["green"] if up else COLORS["red"]
        style = (f"color:{color}; font-family:Menlo,Consolas,monospace; "
                 f"font-size:12px; font-weight:bold;")

        self._ohlc["close"].setText(f"收 {d['close']:.3f}")
        self._ohlc["close"].setStyleSheet(style)

        if d["open"]:
            pct = (d["close"] - d["open"]) / d["open"] * 100
            self._ohlc["chg"].setText(f"涨跌 {pct:+.2f}%")
            self._ohlc["chg"].setStyleSheet(style)

        vol = d["volume"]
        vs = f"{vol/1e8:.2f}亿" if vol >= 1e8 else \
             f"{vol/1e4:.1f}万" if vol >= 1e4 else f"{vol:.0f}"
        self._ohlc["volume"].setText(f"量 {vs}")
