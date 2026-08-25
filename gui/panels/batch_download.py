"""批量下载面板"""
from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QCheckBox,
    QProgressBar, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox
)
from PySide6.QtCore import Qt
from gui.panels.base import BasePanel
from gui.widgets.worker import WorkerThread
from gui.theme import COLORS

KTYPE_ALL = ["K_1M", "K_3M", "K_5M", "K_15M", "K_30M", "K_60M", "K_DAY", "K_WEEK", "K_MON"]


class BatchDownloadPanel(BasePanel):
    def __init__(self, main_window):
        super().__init__(main_window, "批量下载", "一键下载监控列表中所有股票的K线数据")
        self._worker = None
        self._build()

    def _build(self):
        # ─── K线类型选择 ───
        card, layout = self.make_card("K线类型选择")
        ktype_row = QHBoxLayout()
        ktype_row.setContentsMargins(0, 0, 0, 0)
        self._ktype_checks = {}
        defaults = self._main.config.get("kline", "default_types", default=["K_1M", "K_DAY"])
        for kt in KTYPE_ALL:
            cb = QCheckBox(kt)
            cb.setChecked(kt in defaults)
            ktype_row.addWidget(cb)
            self._ktype_checks[kt] = cb
        layout.addLayout(ktype_row)

        opt_row = QHBoxLayout()
        opt_row.setContentsMargins(0, 0, 0, 0)
        self._incr_check = QCheckBox("增量模式")
        self._incr_check.setChecked(True)
        opt_row.addWidget(self._incr_check)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        self._start_btn = self.make_primary_btn("🚀 开始批量下载", self._on_start)
        self._stop_btn = self.make_danger_btn("⏹ 停止", self._on_stop)
        self._stop_btn.setEnabled(False)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        self.add_widget(card)

        # ─── 监控列表预览 ───
        list_card, list_layout = self.make_card("监控列表预览")
        self._stock_table = QTableWidget()
        self._stock_table.setMinimumHeight(200)
        self._stock_table.setColumnCount(2)
        self._stock_table.setHorizontalHeaderLabels(["市场", "股票代码"])
        self._stock_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._stock_table.verticalHeader().setVisible(False)
        self._stock_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._stock_table.setMaximumHeight(180)
        list_layout.addWidget(self._stock_table)
        self.add_widget(list_card)

        # ─── 日志 ───
        log_card, log_layout = self.make_card("下载日志")
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        log_layout.addWidget(self._progress)
        self._log = QTextEdit()
        self._log.setMinimumHeight(120)
        self._log.setObjectName("logPanel")
        self._log.setReadOnly(True)
        log_layout.addWidget(self._log)
        self.add_widget(log_card)

    def on_show(self):
        wl = self._main.config.get("watchlist", default={})
        rows = []
        for market, codes in wl.items():
            if isinstance(codes, list):
                for c in codes:
                    rows.append((market, c))
        self._stock_table.setRowCount(len(rows))
        for i, (m, c) in enumerate(rows):
            self._stock_table.setItem(i, 0, QTableWidgetItem(m))
            self._stock_table.setItem(i, 1, QTableWidgetItem(c))

    def _on_start(self):
        if not self._main.is_connected:
            QMessageBox.warning(self, "提示", "请先连接Futu OpenD")
            return
        codes = self._main.config.get_watchlist_all()
        if not codes:
            QMessageBox.warning(self, "提示", "监控列表为空，请先添加股票")
            return
        ktypes = [k for k, cb in self._ktype_checks.items() if cb.isChecked()]
        if not ktypes:
            QMessageBox.warning(self, "提示", "请选择至少一种K线类型")
            return

        self._log.clear()
        self._log.append(f"开始批量下载: {len(codes)} 只股票 × {len(ktypes)} 种K线")
        self._set_running(True)
        self._progress.setRange(0, len(codes) * len(ktypes))
        self._progress.setValue(0)
        self._progress.setVisible(True)

        self._worker = WorkerThread(
            self._main.kline_dl.batch_download,
            codes, ktypes, self._incr_check.isChecked()
        )
        self._worker.finished_ok.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
        self._set_running(False)

    def _on_done(self, results):
        total = sum(sum(v.values()) for v in results.values())
        self._log.append(f'<span style="color:{COLORS["green"]}">✅ 批量下载完成！共 {total:,} 条记录</span>')
        for code, kt_res in results.items():
            s = ", ".join(f"{k}:{v}" for k, v in kt_res.items())
            self._log.append(f"  {code}: {s}")
        self._main.log(f"批量下载完成: {total:,} 条")
        self._main.refresh_status()
        self._set_running(False)
        self._progress.setValue(self._progress.maximum())

    def _on_error(self, msg):
        self._log.append(f'<span style="color:{COLORS["red"]}">❌ 失败: {msg}</span>')
        self._set_running(False)

    def _set_running(self, running):
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
