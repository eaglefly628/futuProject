"""监控列表管理面板"""
from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QLineEdit,
    QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QPushButton
)
from PySide6.QtCore import Qt
from gui.panels.base import BasePanel
from gui.theme import COLORS


class WatchlistPanel(BasePanel):
    def __init__(self, main_window):
        super().__init__(main_window, "监控列表", "管理需要跟踪的股票代码")
        self._build()

    def _build(self):
        # ─── 添加卡片 ───
        card, layout = self.make_card("添加股票")
        row = QHBoxLayout()
        row.addWidget(QLabel("市场"))
        self._market_combo = QComboBox()
        self._market_combo.addItems(["US", "HK", "SH", "SZ"])
        self._market_combo.setFixedWidth(100)
        row.addWidget(self._market_combo)

        row.addWidget(QLabel("股票代码"))
        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("如 US.AAPL（含市场前缀）")
        self._code_input.returnPressed.connect(self._on_add)
        row.addWidget(self._code_input)

        add_btn = self.make_primary_btn("➕ 添加", self._on_add)
        row.addWidget(add_btn)
        layout.addLayout(row)

        # 快捷添加
        quick_row = QHBoxLayout()
        quick_row.addWidget(QLabel("快捷添加:"))
        for code in ["US.AAPL", "US.TSLA", "US.NVDA", "HK.00700", "SH.600519"]:
            btn = QPushButton(code)
            btn.setFixedHeight(28)
            btn.setStyleSheet(f"font-size: 11px; padding: 2px 10px;")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, c=code: self._quick_add(c))
            quick_row.addWidget(btn)
        quick_row.addStretch()
        layout.addLayout(quick_row)
        self.add_widget(card)

        # ─── 列表卡片 ───
        list_card, list_layout = self.make_card("当前监控列表")
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["市场", "股票代码", "操作"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 80)
        self._table.setColumnWidth(2, 100)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        list_layout.addWidget(self._table)

        self._count_label = QLabel()
        self._count_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        list_layout.addWidget(self._count_label)
        self.add_widget(list_card)
        self.add_stretch()

    def on_show(self):
        self._refresh_table()

    def _refresh_table(self):
        wl = self._main.config.get("watchlist", default={})
        rows = []
        for market, codes in wl.items():
            if isinstance(codes, list):
                for c in codes:
                    rows.append((market, c))

        self._table.setRowCount(len(rows))
        for i, (market, code) in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(market))
            self._table.setItem(i, 1, QTableWidgetItem(code))
            del_btn = self.make_danger_btn("删除")
            del_btn.setFixedHeight(28)
            del_btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
            del_btn.clicked.connect(lambda checked, m=market, c=code: self._on_remove(m, c))
            self._table.setCellWidget(i, 2, del_btn)

        self._count_label.setText(f"共 {len(rows)} 只股票")

    def _on_add(self):
        market = self._market_combo.currentText()
        code = self._code_input.text().strip()
        if not code:
            return
        # 如果用户输入不含市场前缀，自动加上
        if "." not in code:
            code = f"{market}.{code}"

        self._main.config.add_to_watchlist(market, code)
        self._main.config.save()
        self._main.log(f"已添加 {code} 到监控列表")
        self._code_input.clear()
        self._refresh_table()

    def _quick_add(self, code):
        market = code.split(".")[0]
        self._main.config.add_to_watchlist(market, code)
        self._main.config.save()
        self._main.log(f"已添加 {code}")
        self._refresh_table()

    def _on_remove(self, market, code):
        self._main.config.remove_from_watchlist(market, code)
        self._main.config.save()
        self._main.log(f"已移除 {code}")
        self._refresh_table()
