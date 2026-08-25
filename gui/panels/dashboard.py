"""数据总览面板 - 首页仪表盘"""
from datetime import datetime
from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QGridLayout, QLabel,
    QFrame, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter
)
from PySide6.QtCore import Qt
from gui.panels.base import BasePanel
from gui.theme import COLORS


class DashboardPanel(BasePanel):
    def __init__(self, main_window):
        super().__init__(main_window, "数据总览", "实时查看数据采集状态和系统信息")
        self._build()

    def _build(self):
        # ─── 统计卡片行 ───
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(16)
        self._card_kline = self.make_stat_card("K线总记录", "0", COLORS['accent'])
        self._card_stocks = self.make_stat_card("覆盖股票", "0", COLORS['blue'])
        self._card_tick = self.make_stat_card("逐笔记录", "0", COLORS['purple'])
        self._card_db = self.make_stat_card("数据库大小", "0 MB", COLORS['green'])
        stats_row.addWidget(self._card_kline)
        stats_row.addWidget(self._card_stocks)
        stats_row.addWidget(self._card_tick)
        stats_row.addWidget(self._card_db)
        self.add_layout(stats_row)

        # ─── 下半部分：数据明细 + 日志 ───
        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; height: 6px; }")

        # 数据明细表
        detail_card, detail_layout = self.make_card("数据明细")
        self._detail_table = QTableWidget()
        self._detail_table.setMinimumHeight(200)
        self._detail_table.setAlternatingRowColors(True)
        self._detail_table.setColumnCount(5)
        self._detail_table.setHorizontalHeaderLabels(["股票代码", "K线类型", "记录数", "开始时间", "结束时间"])
        self._detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._detail_table.verticalHeader().setVisible(False)
        self._detail_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._detail_table.setSelectionBehavior(QTableWidget.SelectRows)
        detail_layout.addWidget(self._detail_table)
        splitter.addWidget(detail_card)

        # 日志面板
        log_card, log_layout = self.make_card("运行日志")
        self._log_text = QTextEdit()
        self._log_text.setMinimumHeight(120)
        self._log_text.setObjectName("logPanel")
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(200)
        log_layout.addWidget(self._log_text)
        splitter.addWidget(log_card)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        self.add_widget(splitter)

    def on_show(self):
        self._refresh()

    def _refresh(self):
        try:
            stats = self._main.db.get_stats()
        except Exception:
            return

        # 更新统计卡片
        self._update_stat(self._card_kline, f"{stats['kline_total']:,}")
        self._update_stat(self._card_stocks, str(stats['kline_stocks']))
        self._update_stat(self._card_tick, f"{stats['tick_total']:,}")
        self._update_stat(self._card_db, f"{stats['db_size_mb']} MB")

        # 更新表格
        details = stats.get("kline_detail", [])
        self._detail_table.setRowCount(len(details))
        for i, (code, ktype, count, min_t, max_t) in enumerate(details):
            self._detail_table.setItem(i, 0, QTableWidgetItem(code))
            self._detail_table.setItem(i, 1, QTableWidgetItem(ktype))
            item_count = QTableWidgetItem(f"{count:,}")
            item_count.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._detail_table.setItem(i, 2, item_count)
            self._detail_table.setItem(i, 3, QTableWidgetItem(str(min_t or "")))
            self._detail_table.setItem(i, 4, QTableWidgetItem(str(max_t or "")))

    def _update_stat(self, card, value_text):
        for child in card.findChildren(QLabel):
            if child.objectName() == "statValue":
                child.setText(value_text)
                break

    def append_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        color = COLORS['text_secondary']
        if "错误" in msg or "失败" in msg or "error" in msg.lower():
            color = COLORS['red']
        elif "成功" in msg or "完成" in msg or "✅" in msg:
            color = COLORS['green']
        elif "警告" in msg or "⚠" in msg:
            color = COLORS['yellow']
        self._log_text.append(f'<span style="color:{COLORS["text_muted"]}">[{ts}]</span> '
                              f'<span style="color:{color}">{msg}</span>')
        self._log_text.verticalScrollBar().setValue(
            self._log_text.verticalScrollBar().maximum()
        )
