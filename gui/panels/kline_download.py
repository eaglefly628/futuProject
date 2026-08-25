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
        grid.setContentsMargins(0, 0, 0, 0)
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
        self._ktype_combo.currentIndexChanged.connect(
            lambda _: self._refresh_date_hint())
        grid.addWidget(self._ktype_combo, 0, 3)

        # 开始日期
        grid.addWidget(QLabel("开始日期"), 1, 0)
        self._start_date = QDateEdit()
        self._start_date.setCalendarPopup(True)
        # 默认三个月，但允许一路翻到 1990，回溯多久由用户定
        self._start_date.setMinimumDate(QDate(1990, 1, 1))
        self._start_date.setMaximumDate(QDate.currentDate())
        self._start_date.setDate(QDate.currentDate().addMonths(-3))
        self._start_date.setDisplayFormat("yyyy-MM-dd")
        self._start_date.dateChanged.connect(lambda _: self._refresh_date_hint())
        grid.addWidget(self._start_date, 1, 1)

        # 结束日期
        grid.addWidget(QLabel("结束日期"), 1, 2)
        self._end_date = QDateEdit()
        self._end_date.setCalendarPopup(True)
        self._end_date.setDate(QDate.currentDate())
        self._end_date.setDisplayFormat("yyyy-MM-dd")
        grid.addWidget(self._end_date, 1, 3)

        # 数据源
        grid.addWidget(QLabel("数据源"), 2, 0)
        self._source_combo = QComboBox()
        from downloaders.akshare_source import MarketRouter
        for key, label, tip in MarketRouter.SOURCE_OPTIONS:
            self._source_combo.addItem(label, key)
            self._source_combo.setItemData(
                self._source_combo.count() - 1, tip, Qt.ToolTipRole)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        grid.addWidget(self._source_combo, 2, 1)

        self._source_hint = QLabel()
        self._source_hint.setWordWrap(True)
        self._source_hint.setStyleSheet(f"color: {COLORS['text_secondary']};")
        grid.addWidget(self._source_hint, 2, 2, 1, 2)

        layout.addLayout(grid)

        # 选项行
        opt_row = QHBoxLayout()
        opt_row.setContentsMargins(0, 0, 0, 0)
        self._incr_check = QCheckBox("增量模式（从上次断点继续）")
        self._incr_check.setChecked(True)
        self._incr_check.setToolTip(
            "只补库里最新一条之后的数据。要往前回溯更早的历史，请取消勾选。")
        self._incr_check.toggled.connect(lambda _: self._refresh_date_hint())
        opt_row.addWidget(self._incr_check)

        self._auto_date_check = QCheckBox("自动计算起始日期")
        self._auto_date_check.setChecked(True)
        self._auto_date_check.setToolTip(
            "勾选时按配置的回溯天数自动算起点，「开始日期」不可编辑。\n"
            "取消勾选即可自己指定起点，最早可选到 1990-01-01。")
        self._auto_date_check.toggled.connect(self._on_auto_date_toggle)
        opt_row.addWidget(self._auto_date_check)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        # 说明当前这组选项实际会从哪天开始拉，省得用户猜
        self._date_hint = QLabel()
        self._date_hint.setWordWrap(True)
        self._date_hint.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(self._date_hint)

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
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
        self._log.setMinimumHeight(120)
        self._log.setObjectName("logPanel")
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(200)
        prog_layout.addWidget(self._log)
        self.add_widget(prog_card)

        self.add_stretch()
        self._on_auto_date_toggle(True)
        self._on_source_changed()
        self._refresh_date_hint()

    def _on_auto_date_toggle(self, checked):
        self._start_date.setEnabled(not checked)
        self._refresh_date_hint()

    def _refresh_date_hint(self):
        """把「这次实际从哪天开始拉」算出来显示，别让用户猜"""
        from datetime import datetime, timedelta

        ktype = self._ktype_combo.currentData()
        auto = self._auto_date_check.isChecked()
        incr = self._incr_check.isChecked()

        if not auto:
            start = self._start_date.date().toString("yyyy-MM-dd")
            self._date_hint.setText(
                f"起点: {start}（手动指定，会覆盖增量模式）")
            return

        days = self._main.config.get("kline", "lookback_days", ktype, default=90)
        auto_start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        if incr:
            self._date_hint.setText(
                f"起点: 库里最新一条之后；库里没有数据时回溯 {days} 天（{auto_start}）。"
                f"　要往前补更早的历史，取消「自动计算起始日期」并选一个更早的开始日期。")
        else:
            self._date_hint.setText(
                f"起点: {auto_start}（{ktype} 自动回溯 {days} 天）。"
                f"　想拉更早，取消「自动计算起始日期」自己选。")

    def _on_source_changed(self):
        """下拉切换时显示该源的适用说明"""
        from downloaders.akshare_source import MarketRouter
        key = self._source_combo.currentData()
        tip = dict((k, t) for k, _, t in MarketRouter.SOURCE_OPTIONS).get(key, "")
        self._source_hint.setText(tip)

    def _on_start(self):
        code = self._code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "提示", "请输入股票代码")
            return

        router = self._main.router
        if router is None:
            QMessageBox.warning(self, "提示", "数据源未初始化")
            return

        prefer = self._source_combo.currentData() or "auto"

        # 只有真要走 Futu 才需要 OpenD；A 股走免费源，不该被这道检查拦住
        if router.requires_futu(code, prefer) and not self._main.is_connected:
            QMessageBox.warning(
                self, "提示",
                "这次下载要走 Futu OpenAPI，请先连接 OpenD（侧栏 → 连接管理）。\n"
                "如果是 A 股标的，把「数据源」改成自动或东财/Yahoo 即可免连接。")
            return

        ktype = self._ktype_combo.currentData()
        start = None if self._auto_date_check.isChecked() else self._start_date.date().toString("yyyy-MM-dd")
        end = self._end_date.date().toString("yyyy-MM-dd")
        incr = self._incr_check.isChecked()

        self._log.clear()
        self._log_msg(f"开始下载: {code} | {ktype} | 增量: {incr} | "
                      f"数据源: {router.source_name(code, prefer)}")
        self._set_running(True)

        worker = WorkerThread.deferred()

        def do_download():
            n = router.download_history(
                code, ktype, start, end, incr, prefer=prefer,
                should_stop=worker.should_stop,
                on_progress=worker.emit_progress)
            # 把命中的源和失败原因一起带回来，否则界面只能看到一个 0
            return n, router.last_source, router.last_error, worker.cancelled

        worker.set_task(do_download)
        self._worker = worker
        worker.progress.connect(self._log_msg)
        worker.finished_ok.connect(self._on_done)
        worker.error.connect(self._on_error)
        worker.start()

    def _on_stop(self):
        if not (self._worker and self._worker.isRunning()):
            return
        self._worker.cancel()
        # 不在这里 wait()，会卡住界面。线程自己收尾后走 _on_done
        self._stop_btn.setEnabled(False)
        self._stop_btn.setText("停止中…")
        self._log_msg("⏹ 正在停止，等当前请求返回…")

    def _on_done(self, result):
        count, source, error, cancelled = result
        code = self._code_input.text().strip()

        if cancelled:
            self._log_msg(f"⏹ 已停止，本次已保存 {count} 条")
            if count:
                self._log_msg("已入库的数据会保留，下次开增量模式接着补即可")
            self._main.log(f"K线下载已停止: {code} → {count} 条")
        elif count > 0:
            self._log_msg(f"✅ 下载完成！共 {count} 条记录"
                          + (f" · 实际来源: {source}" if source else ""))
            self._main.log(f"K线下载完成: {code} → {count} 条")
        else:
            # 0 条不是成功。报清楚是哪个源、卡在哪
            self._log_msg(f"⚠️ 没有拿到数据（0 条）")
            if error:
                self._log_msg(f"原因: {error}")
            self._log_msg(self._hint_for(code, error))
            self._main.log(f"K线下载无数据: {code} - {error or '未知原因'}")

        self._main.refresh_status()
        self._set_running(False)

    def _hint_for(self, code: str, error: str) -> str:
        """按失败原因给一条能直接照做的建议"""
        from downloaders.akshare_source import is_a_share
        err = (error or "")

        if "无权限" in err:
            return ("提示: Futu 账号没有该标的的行情权限。A 股请把「数据源」"
                    "换成自动 / 东财 / Yahoo，这些不需要权限。")
        if "Proxy" in err or "proxy" in err:
            return ("提示: 该源被系统代理挡住了。换成 Yahoo 再试 —— "
                    "挂日本代理时通常是它能通。")
        if is_a_share(code) and "无数据" in err and "Yahoo" in err:
            return ("提示: 免费源的分钟线历史很短（东财约 5 天、Yahoo 7 天）。"
                    "拉长历史请改用 60 分钟或日线。")
        if "未安装" in err:
            return "提示: 该源缺依赖，按报错里的 pip 命令装上再试。"
        return ("提示: 换一个数据源再试；仍不行就跑 "
                "python -m scripts.test_em <代码> 看各周期能否拉到。")

    def _on_error(self, msg):
        self._log_msg(f"❌ 下载失败: {msg}")
        self._main.log(f"K线下载失败: {msg}")
        self._set_running(False)

    def _set_running(self, running):
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._stop_btn.setText("⏹ 停止")
        self._progress_bar.setVisible(running)

    def _log_msg(self, msg):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        color = COLORS['text_secondary']
        if "⏹" in msg:
            color = COLORS['yellow']
        elif "✅" in msg or "完成" in msg:
            color = COLORS['green']
        elif "❌" in msg or "失败" in msg:
            color = COLORS['red']
        elif "⚠" in msg:
            color = COLORS['yellow']
        self._log.append(f'<span style="color:#484F58">[{ts}]</span> '
                         f'<span style="color:{color}">{msg}</span>')
