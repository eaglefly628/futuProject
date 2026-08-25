"""K线下载面板"""
from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QLineEdit,
    QComboBox, QCheckBox, QPushButton, QProgressBar,
    QTextEdit, QFrame, QGridLayout, QDateEdit, QMessageBox
)
from PySide6.QtCore import Qt, QDate
from gui.panels.base import BasePanel
from gui.widgets.worker import WorkerThread
from gui.theme import COLORS

KTYPE_OPTIONS = [
    ("K_1M", "1分钟"), ("K_3M", "3分钟"), ("K_5M", "5分钟"),
    ("K_15M", "15分钟"), ("K_30M", "30分钟"), ("K_60M", "60分钟"),
    ("K_DAY", "日K"), ("K_WEEK", "周K"), ("K_MON", "月K"),
]


class KlineDownloadPanel(BasePanel):
    def __init__(self, main_window):
        super().__init__(main_window, "K线下载", "下载指定股票的历史K线数据")
        self._worker = None
        self._build()

    def _build(self):
        # ─── 参数卡片 ───
        card, layout = self.make_card("下载参数")

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        # 股票代码
        grid.addWidget(QLabel("股票代码"), 0, 0)
        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("如 US.AAPL, HK.00700, SH.600519")
        grid.addWidget(self._code_input, 0, 1)

        # K线类型
        grid.addWidget(QLabel("K线类型"), 0, 2)
        self._ktype_combo = QComboBox()
        for val, label in KTYPE_OPTIONS:
            self._ktype_combo.addItem(f"{label} ({val})", val)
        self._ktype_combo.setCurrentIndex(6)  # 默认日K
        grid.addWidget(self._ktype_combo, 0, 3)

        # 开始日期
        grid.addWidget(QLabel("开始日期"), 1, 0)
        self._start_date = QDateEdit()
        self._start_date.setCalendarPopup(True)
        self._start_date.setDate(QDate.currentDate().addMonths(-3))
        self._start_date.setDisplayFormat("yyyy-MM-dd")
        grid.addWidget(self._start_date, 1, 1)

        # 结束日期
        grid.addWidget(QLabel("结束日期"), 1, 2)
        self._end_date = QDateEdit()
        self._end_date.setCalendarPopup(True)
        self._end_date.setDate(QDate.currentDate())
        self._end_date.setDisplayFormat("yyyy-MM-dd")
        grid.addWidget(self._end_date, 1, 3)

        layout.addLayout(grid)

        # 选项行
        opt_row = QHBoxLayout()
        self._incr_check = QCheckBox("增量模式（从上次断点继续）")
        self._incr_check.setChecked(True)
        opt_row.addWidget(self._incr_check)
        self._auto_date_check = QCheckBox("自动计算起始日期")
        self._auto_date_check.setChecked(True)
        self._auto_date_check.toggled.connect(self._on_auto_date_toggle)
        opt_row.addWidget(self._auto_date_check)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        # 操作按钮
        btn_row = QHBoxLayout()
        self._start_btn = self.make_primary_btn("🚀 开始下载", self._on_start)
        self._stop_btn = self.make_danger_btn("⏹ 停止", self._on_stop)
        self._stop_btn.setEnabled(False)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.add_widget(card)

        # ─── 进度卡片 ───
        prog_card, prog_layout = self.make_card("下载进度")
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # indeterminate
        self._progress_bar.setVisible(False)
        prog_layout.addWidget(self._progress_bar)

        self._log = QTextEdit()
        self._log.setObjectName("logPanel")
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(200)
        prog_layout.addWidget(self._log)
        self.add_widget(prog_card)

        self.add_stretch()
        self._on_auto_date_toggle(True)

    def _on_auto_date_toggle(self, checked):
        self._start_date.setEnabled(not checked)

    def _on_start(self):
        code = self._code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "提示", "请输入股票代码")
            return
        if not self._main.is_connected:
            QMessageBox.warning(self, "提示", "请先连接Futu OpenD（侧栏 → 连接管理）")
            return

        ktype = self._ktype_combo.currentData()
        start = None if self._auto_date_check.isChecked() else self._start_date.date().toString("yyyy-MM-dd")
        end = self._end_date.date().toString("yyyy-MM-dd")
        incr = self._incr_check.isChecked()

        self._log.clear()
        self._log_msg(f"开始下载: {code} | {ktype} | 增量: {incr}")
        self._set_running(True)

        self._worker = WorkerThread(
            self._main.kline_dl.download_history,
            code, ktype, start, end, incr
        )
        self._worker.finished_ok.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._log_msg("⚠️ 已手动停止")
        self._set_running(False)

    def _on_done(self, count):
        self._log_msg(f"✅ 下载完成！共 {count} 条记录")
        self._main.log(f"K线下载完成: {self._code_input.text()} → {count} 条")
        self._main.refresh_status()
        self._set_running(False)

    def _on_error(self, msg):
        self._log_msg(f"❌ 下载失败: {msg}")
        self._main.log(f"K线下载失败: {msg}")
        self._set_running(False)

    def _set_running(self, running):
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._progress_bar.setVisible(running)

    def _log_msg(self, msg):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        color = COLORS['text_secondary']
        if "✅" in msg or "完成" in msg:
            color = COLORS['green']
        elif "❌" in msg or "失败" in msg:
            color = COLORS['red']
        elif "⚠" in msg:
            color = COLORS['yellow']
        self._log.append(f'<span style="color:#484F58">[{ts}]</span> '
                         f'<span style="color:{color}">{msg}</span>')
