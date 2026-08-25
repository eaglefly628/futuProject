"""逐笔采集面板"""
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QSpinBox,
    QTextEdit, QMessageBox
)
from PySide6.QtCore import Qt
from gui.panels.base import BasePanel
from gui.widgets.worker import WorkerThread
from gui.theme import COLORS


class TickCollectPanel(BasePanel):
    def __init__(self, main_window):
        super().__init__(main_window, "逐笔采集", "获取股票的逐笔成交数据")
        self._worker = None
        self._build()

    def _build(self):
        card, layout = self.make_card("采集参数")

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.addWidget(QLabel("股票代码"))
        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("如 US.AAPL")
        row1.addWidget(self._code_input)
        row1.addWidget(QLabel("获取条数"))
        self._count_spin = QSpinBox()
        self._count_spin.setRange(100, 10000)
        self._count_spin.setValue(1000)
        self._count_spin.setSingleStep(100)
        row1.addWidget(self._count_spin)
        layout.addLayout(row1)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        self._start_btn = self.make_primary_btn("⚡ 开始采集", self._on_start)
        btn_row.addWidget(self._start_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        self.add_widget(card)

        log_card, log_layout = self.make_card("采集日志")
        self._log = QTextEdit()
        self._log.setMinimumHeight(120)
        self._log.setObjectName("logPanel")
        self._log.setReadOnly(True)
        log_layout.addWidget(self._log)
        self.add_widget(log_card)
        self.add_stretch()

    def _on_start(self):
        code = self._code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "提示", "请输入股票代码")
            return
        if not self._main.is_connected:
            QMessageBox.warning(self, "提示", "请先连接Futu OpenD")
            return

        count = self._count_spin.value()
        self._log.append(f"开始采集: {code} × {count} 条...")
        self._start_btn.setEnabled(False)

        self._worker = WorkerThread(
            self._main.tick_cl.get_history_ticks, code, count
        )
        self._worker.finished_ok.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_done(self, saved):
        self._log.append(f'<span style="color:{COLORS["green"]}">✅ 采集完成: {saved} 条逐笔记录</span>')
        self._main.log(f"逐笔采集完成: {saved} 条")
        self._main.refresh_status()
        self._start_btn.setEnabled(True)

    def _on_error(self, msg):
        self._log.append(f'<span style="color:{COLORS["red"]}">❌ 失败: {msg}</span>')
        self._start_btn.setEnabled(True)
