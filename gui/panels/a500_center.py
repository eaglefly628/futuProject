"""
A500 量化中心 - 一站式采集/图表/分析面板
"""
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QComboBox, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QProgressBar, QTextEdit, QHeaderView, QFrame, QCheckBox, QSplitter,
    QAbstractItemView, QMessageBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor

from gui.panels.base import BasePanel
from gui.widgets.worker import WorkerThread
from gui.widgets.chart import KLineChart, MiniBarChart, GaugeWidget
from gui.theme import COLORS

# ─── A500 ETF 标的 ───
A500_ETFS = [
    ("SZ.159338", "中证A500ETF(国泰)"),
    ("SZ.159361", "中证A500ETF(易方达)"),
    ("SZ.159352", "中证A500ETF(南方)"),
    ("SZ.159355", "中证A500ETF(招商)"),
    ("SZ.159339", "中证A500ETF(广发)"),
    ("SH.512050", "中证A500ETF(国泰-沪)"),
    ("SH.563360", "中证A500ETF(华泰柏瑞)"),
    ("SH.563220", "中证A500ETF(富国)"),
    ("SH.563800", "中证A500ETF(广发-沪)"),
    ("SH.512370", "A500增强策略ETF(华夏)"),
    ("SH.563510", "A500红利低波ETF(易方达)"),
]

KTYPE_LABELS = [
    ("K_1M", "1分钟", 90),
    ("K_5M", "5分钟", 180),
    ("K_15M", "15分钟", 365),
    ("K_60M", "60分钟", 730),
    ("K_DAY", "日线", 3650),
]


class A500CenterPanel(BasePanel):
    """A500 量化中心"""

    def __init__(self, main_window):
        super().__init__(main_window, "A500 量化中心",
                         "中证A500 ETF 数据采集 · K线图表 · 量价分析")
        self._worker = None
        self._current_report = None
        self._build()

    # ═══════════════════════════════════════
    def _build(self):
        # ─── 顶部工具栏 ───
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(10)

        toolbar.addWidget(QLabel("标的:"))
        self._code_combo = QComboBox()
        self._code_combo.setEditable(True)
        self._code_combo.setInsertPolicy(QComboBox.NoInsert)
        for code, name in A500_ETFS:
            self._code_combo.addItem(f"{name}  [{code}]", code)
        self._code_combo.setMinimumWidth(260)
        self._code_combo.lineEdit().setPlaceholderText("选择或输入代码，如 SZ.159338")
        self._code_combo.currentIndexChanged.connect(self._on_code_changed)
        # 回车确认手输代码
        self._code_combo.lineEdit().returnPressed.connect(self._on_code_changed)
        toolbar.addWidget(self._code_combo)

        toolbar.addWidget(QLabel("周期:"))
        self._ktype_combo = QComboBox()
        for kt, label, _ in KTYPE_LABELS:
            self._ktype_combo.addItem(label, kt)
        self._ktype_combo.setCurrentIndex(4)  # 默认日线
        self._ktype_combo.currentIndexChanged.connect(self._refresh_chart)
        toolbar.addWidget(self._ktype_combo)

        self._refresh_btn = self.make_primary_btn("🔄 刷新图表", self._refresh_chart)
        toolbar.addWidget(self._refresh_btn)

        self._analyze_btn = self.make_primary_btn("🔬 运行分析", self._on_analyze)
        toolbar.addWidget(self._analyze_btn)

        toolbar.addStretch()

        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet(f"color:{COLORS['text_secondary']};")
        toolbar.addWidget(self._status_label)

        self.add_layout(toolbar)

        # ─── 主标签页 ───
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_chart_tab(), "📈 K线图表")
        self._tabs.addTab(self._build_analysis_tab(), "🔬 量价分析")
        self._tabs.addTab(self._build_fetch_tab(), "⬇️ 数据采集")
        self.add_widget(self._tabs)

    # ═══════════════════════════════════════
    #  Tab 1: K线图表
    # ═══════════════════════════════════════
    def _build_chart_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(10)

        # OHLC 信息条
        info_bar = QFrame()
        info_bar.setObjectName("card")
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(14, 8, 14, 8)
        info_layout.setSpacing(20)

        self._ohlc_labels = {}
        for key, label in [("time", "时间"), ("open", "开"), ("high", "高"),
                           ("low", "低"), ("close", "收"), ("volume", "量")]:
            lbl = QLabel(f"{label}: --")
            lbl.setStyleSheet(f"color:{COLORS['text_secondary']}; font-family:Menlo; font-size:12px;")
            info_layout.addWidget(lbl)
            self._ohlc_labels[key] = lbl
        info_layout.addStretch()

        hint = QLabel("滚轮缩放 · 鼠标移动查看详情")
        hint.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
        info_layout.addWidget(hint)

        layout.addWidget(info_bar)

        # K线图
        self._chart = KLineChart()
        self._chart.crosshair_moved.connect(self._on_crosshair)
        layout.addWidget(self._chart, 1)

        return w

    def _on_crosshair(self, data: dict):
        self._ohlc_labels["time"].setText(f"时间: {data['time'][:16]}")
        self._ohlc_labels["open"].setText(f"开: {data['open']:.3f}")
        self._ohlc_labels["high"].setText(f"高: {data['high']:.3f}")
        self._ohlc_labels["low"].setText(f"低: {data['low']:.3f}")

        close_color = COLORS["green"] if data["close"] >= data["open"] else COLORS["red"]
        self._ohlc_labels["close"].setText(f"收: {data['close']:.3f}")
        self._ohlc_labels["close"].setStyleSheet(
            f"color:{close_color}; font-family:Menlo; font-size:12px; font-weight:bold;")

        vol = data["volume"]
        vol_str = f"{vol/10000:.1f}万" if vol >= 10000 else f"{vol:.0f}"
        self._ohlc_labels["volume"].setText(f"量: {vol_str}")

    # ═══════════════════════════════════════
    #  Tab 2: 量价分析
    # ═══════════════════════════════════════
    def _build_analysis_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 12, 0, 0)
        outer.setSpacing(12)

        # ── 顶部: 评分仪表 + 关键指标 ──
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        # 评分仪表盘
        gauge_card = QFrame()
        gauge_card.setObjectName("card")
        gauge_layout = QVBoxLayout(gauge_card)
        self._gauge = GaugeWidget()
        gauge_layout.addWidget(self._gauge)
        self._reco_label = QLabel("--")
        self._reco_label.setAlignment(Qt.AlignCenter)
        self._reco_label.setStyleSheet(
            f"color:{COLORS['accent']}; font-size:15px; font-weight:bold;")
        gauge_layout.addWidget(self._reco_label)
        gauge_card.setMaximumWidth(220)
        top_row.addWidget(gauge_card)

        # 因子评分柱状图
        factor_card, factor_layout = self.make_card("五因子评分")
        self._factor_chart = MiniBarChart()
        factor_layout.addWidget(self._factor_chart)
        top_row.addWidget(factor_card, 1)

        # 概率卡片
        prob_card, prob_layout = self.make_card("中期趋势概率")
        self._prob_up_label = QLabel("上涨: --")
        self._prob_up_label.setStyleSheet(
            f"color:{COLORS['green']}; font-size:20px; font-weight:bold;")
        self._prob_down_label = QLabel("下跌: --")
        self._prob_down_label.setStyleSheet(
            f"color:{COLORS['red']}; font-size:20px; font-weight:bold;")
        self._direction_label = QLabel("方向: --")
        self._direction_label.setStyleSheet(f"color:{COLORS['text_primary']}; font-size:13px;")
        self._risk_label = QLabel("风险: --")
        self._risk_label.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:12px;")
        prob_layout.addWidget(self._prob_up_label)
        prob_layout.addWidget(self._prob_down_label)
        prob_layout.addWidget(self._direction_label)
        prob_layout.addWidget(self._risk_label)
        prob_layout.addStretch()
        prob_card.setMaximumWidth(200)
        top_row.addWidget(prob_card)

        outer.addLayout(top_row)

        # ── 中部: 指标网格 ──
        mid_row = QHBoxLayout()
        mid_row.setContentsMargins(0, 0, 0, 0)
        mid_row.setSpacing(12)

        # 量价指标
        vol_card, vol_layout = self.make_card("成交量结构")
        self._vol_grid = QGridLayout()
        self._vol_grid.setSpacing(8)
        vol_layout.addLayout(self._vol_grid)
        mid_row.addWidget(vol_card, 1)

        # 技术指标
        tech_card, tech_layout = self.make_card("技术指标")
        self._tech_grid = QGridLayout()
        self._tech_grid.setSpacing(8)
        tech_layout.addLayout(self._tech_grid)
        mid_row.addWidget(tech_card, 1)

        # 支撑阻力
        level_card, level_layout = self.make_card("支撑阻力")
        self._level_grid = QGridLayout()
        self._level_grid.setSpacing(8)
        level_layout.addLayout(self._level_grid)
        mid_row.addWidget(level_card, 1)

        outer.addLayout(mid_row)

        # ── 底部: 信号列表 ──
        signal_card, signal_layout = self.make_card("分析信号")
        self._signal_text = QTextEdit()
        self._signal_text.setMinimumHeight(120)
        self._signal_text.setObjectName("logPanel")
        self._signal_text.setReadOnly(True)
        self._signal_text.setMaximumHeight(160)
        signal_layout.addWidget(self._signal_text)
        outer.addWidget(signal_card)

        return w

    def _set_grid_items(self, grid: QGridLayout, items: list):
        """填充网格 [(label, value, color), ...]"""
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, (label, value, color) in enumerate(items):
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:12px;")
            val = QLabel(str(value))
            val.setStyleSheet(
                f"color:{color or COLORS['text_primary']}; font-size:13px; "
                f"font-weight:bold; font-family:Menlo;")
            val.setAlignment(Qt.AlignRight)
            grid.addWidget(lbl, i, 0)
            grid.addWidget(val, i, 1)

    # ═══════════════════════════════════════
    #  Tab 3: 数据采集
    # ═══════════════════════════════════════
    def _build_fetch_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        # 周期选择
        sel_card, sel_layout = self.make_card("采集周期")
        kt_row = QHBoxLayout()
        kt_row.setContentsMargins(0, 0, 0, 0)
        self._ktype_checks = {}
        for kt, label, days in KTYPE_LABELS:
            cb = QCheckBox(f"{label} ({days}天)")
            cb.setChecked(kt in ("K_5M", "K_60M", "K_DAY"))
            self._ktype_checks[kt] = cb
            kt_row.addWidget(cb)
        kt_row.addStretch()
        sel_layout.addLayout(kt_row)

        # 标的选择
        code_row = QHBoxLayout()
        code_row.setContentsMargins(0, 0, 0, 0)
        code_row.addWidget(QLabel("采集范围:"))
        self._scope_combo = QComboBox()
        self._scope_combo.addItem("当前选中标的", "current")
        self._scope_combo.addItem(f"全部 {len(A500_ETFS)} 只 A500 ETF", "all")
        code_row.addWidget(self._scope_combo)

        code_row.addSpacing(16)
        code_row.addWidget(QLabel("数据源:"))
        self._source_combo = QComboBox()
        from downloaders.akshare_source import MarketRouter
        for key, label, tip in MarketRouter.SOURCE_OPTIONS:
            self._source_combo.addItem(label, key)
            self._source_combo.setItemData(
                self._source_combo.count() - 1, tip, Qt.ToolTipRole)
        self._source_combo.setMinimumWidth(150)
        self._source_combo.currentIndexChanged.connect(self._refresh_chart)
        code_row.addWidget(self._source_combo)

        code_row.addStretch()

        self._incr_check = QCheckBox("增量模式")
        self._incr_check.setChecked(True)
        self._incr_check.setToolTip(
            "只补库里最新一条之后的数据。取消勾选则按上面的周期天数整段重拉。")
        code_row.addWidget(self._incr_check)

        self._fetch_btn = self.make_primary_btn("⬇️ 开始采集", self._on_fetch)
        code_row.addWidget(self._fetch_btn)
        self._stop_btn = self.make_danger_btn("⏹ 停止", self._on_stop)
        self._stop_btn.setEnabled(False)
        code_row.addWidget(self._stop_btn)
        sel_layout.addLayout(code_row)

        layout.addWidget(sel_card)

        # 进度
        prog_card, prog_layout = self.make_card("采集进度")
        self._progress = QProgressBar()
        self._progress.setValue(0)
        prog_layout.addWidget(self._progress)
        self._progress_label = QLabel("等待开始")
        self._progress_label.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:12px;")
        prog_layout.addWidget(self._progress_label)
        layout.addWidget(prog_card)

        # 数据覆盖表
        cov_card, cov_layout = self.make_card("本地数据覆盖")
        self._cov_table = QTableWidget()
        self._cov_table.setMinimumHeight(200)
        self._cov_table.setColumnCount(7)
        self._cov_table.setHorizontalHeaderLabels(
            ["代码", "名称", "1分钟", "5分钟", "15分钟", "60分钟", "日线"])
        self._cov_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._cov_table.setAlternatingRowColors(True)
        self._cov_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._cov_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        cov_layout.addWidget(self._cov_table)
        layout.addWidget(cov_card, 1)

        # 日志
        log_card, log_layout = self.make_card("采集日志")
        self._fetch_log = QTextEdit()
        self._fetch_log.setMinimumHeight(120)
        self._fetch_log.setObjectName("logPanel")
        self._fetch_log.setReadOnly(True)
        self._fetch_log.setMaximumHeight(120)
        log_layout.addWidget(self._fetch_log)
        layout.addWidget(log_card)

        return w

    # ═══════════════════════════════════════
    #  事件处理
    # ═══════════════════════════════════════
    def on_show(self):
        self._refresh_chart()
        self._refresh_coverage()

    def _current_code(self) -> str:
        """取当前标的代码：优先匹配下拉项，否则解析手输文本"""
        text = self._code_combo.currentText().strip()

        # 文本与某个下拉项一致 -> 用它的 data
        idx = self._code_combo.findText(text)
        if idx >= 0:
            data = self._code_combo.itemData(idx)
            if data:
                return data

        if not text:
            return ""

        # 形如 "名称  [SZ.159338]" -> 取方括号内
        if "[" in text and "]" in text:
            inner = text[text.rfind("[") + 1:text.rfind("]")].strip()
            if inner:
                return self._normalize_code(inner)

        return self._normalize_code(text)

    @staticmethod
    def _normalize_code(raw: str) -> str:
        """把 159338 / sz159338 / SZ.159338 统一成 Futu 格式 SZ.159338"""
        c = raw.strip().upper().replace(" ", "")
        if not c:
            return ""
        if "." in c:
            return c
        for prefix in ("SZ", "SH", "HK", "US"):
            if c.startswith(prefix) and len(c) > len(prefix):
                return f"{prefix}.{c[len(prefix):]}"
        # 纯数字：按 A 股代码规则推断交易所
        if c.isdigit():
            if len(c) == 6:
                return f"{'SH' if c[0] in '69' or c.startswith('5') else 'SZ'}.{c}"
            if len(c) == 5:
                return f"HK.{c}"
        # 纯字母按美股处理
        if c.isalpha():
            return f"US.{c}"
        return c

    def _on_code_changed(self):
        self._refresh_chart()

    def _refresh_chart(self):
        code = self._current_code()
        ktype = self._ktype_combo.currentData()
        if not code or not ktype:
            return

        try:
            df = self._main.db.get_kline(code, ktype)
        except Exception as e:
            self._status_label.setText(f"读取失败: {e}")
            return

        if df is None or df.empty:
            self._chart.set_data(None)
            self._status_label.setText(f"{code} {ktype} 无本地数据，请先采集")
            return

        self._chart.set_data(df)
        prefer = self._source_combo.currentData() or "auto"
        src = self._main.router.source_name(code, prefer) if self._main.router else "—"
        self._status_label.setText(f"{code} {ktype} · {len(df):,} 条 · 源: {src}")

    def _refresh_coverage(self):
        """刷新数据覆盖表"""
        self._cov_table.setRowCount(len(A500_ETFS))
        for r, (code, name) in enumerate(A500_ETFS):
            self._cov_table.setItem(r, 0, QTableWidgetItem(code))
            self._cov_table.setItem(r, 1, QTableWidgetItem(name))
            for c, (kt, _, _) in enumerate(KTYPE_LABELS):
                try:
                    df = self._main.db.get_kline(code, kt)
                    n = len(df) if df is not None else 0
                except Exception:
                    n = 0
                item = QTableWidgetItem(f"{n:,}" if n else "—")
                item.setTextAlignment(Qt.AlignCenter)
                if n > 0:
                    item.setForeground(QColor(COLORS["green"]))
                else:
                    item.setForeground(QColor(COLORS["text_muted"]))
                self._cov_table.setItem(r, c + 2, item)

    # ─── 数据采集 ───
    def _on_fetch(self):
        ktypes = [kt for kt, cb in self._ktype_checks.items() if cb.isChecked()]
        if not ktypes:
            QMessageBox.warning(self, "未选择", "请至少选择一个采集周期")
            return

        scope = self._scope_combo.currentData()
        codes = [self._current_code()] if scope == "current" else [c for c, _ in A500_ETFS]

        # A股走免费源(无需OpenD)，港美股才需要 Futu 连接
        from downloaders.akshare_source import is_a_share
        router = self._main.router
        prefer = self._source_combo.currentData() or "auto"
        need_futu = ([c for c in codes if router.requires_futu(c, prefer)]
                     if router else codes)

        if router is None or (router.akshare is None and
                              any(is_a_share(c) for c in codes)):
            QMessageBox.warning(
                self, "缺少数据源",
                "A股数据源 akshare 不可用。\n\n请安装:  pip install akshare")
            return

        if need_futu and not self._main.is_connected:
            QMessageBox.warning(
                self, "未连接",
                f"以下标的需要 Futu OpenD 连接:\n{', '.join(need_futu)}\n\n"
                f"请先在「连接管理」中连接。")
            return

        self._set_running(True)
        self._fetch_log.clear()
        self._progress.setValue(0)

        incr = self._incr_check.isChecked()
        lookback_map = {kt: days for kt, _, days in KTYPE_LABELS}
        total_tasks = len(codes) * len(ktypes)

        worker = WorkerThread.deferred()

        def do_fetch():
            done = 0
            total_records = 0
            for code in codes:
                if worker.should_stop():
                    break
                src_name = router.source_name(code, prefer)
                worker.progress.emit(f"── {code}  数据源: {src_name} ──")
                for kt in ktypes:
                    if worker.should_stop():
                        break
                    days = lookback_map.get(kt, 90)
                    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                    end = datetime.now().strftime("%Y-%m-%d")
                    try:
                        n = router.download_history(
                            code=code, ktype_str=kt,
                            start_date=start, end_date=end, incremental=incr,
                            prefer=prefer,
                            should_stop=worker.should_stop,
                            on_progress=worker.progress.emit)
                        total_records += n
                        if n > 0:
                            hit = router.last_source or src_name
                            worker.progress.emit(f"{code} {kt}: {n} 条  ({hit})")
                        else:
                            # 0 条要说明原因，不然只看到一串 0 无从下手
                            why = router.last_error or "无数据"
                            worker.progress.emit(f"{code} {kt}: 0 条 — {why}")
                    except Exception as e:
                        worker.progress.emit(f"{code} {kt}: 失败 - {e}")
                    done += 1
                    worker.progress.emit(f"__PROGRESS__{int(done / total_tasks * 100)}")
                    if worker.sleep_or_stop(0.3):
                        break
            return total_records, worker.cancelled

        worker.set_task(do_fetch)
        self._worker = worker
        worker.progress.connect(self._on_fetch_progress)
        worker.finished_ok.connect(self._on_fetch_done)
        worker.error.connect(self._on_fetch_error)
        worker.start()

    def _on_fetch_progress(self, msg: str):
        if msg.startswith("__PROGRESS__"):
            try:
                self._progress.setValue(int(msg.replace("__PROGRESS__", "")))
            except ValueError:
                pass
            return
        self._fetch_log.append(msg)
        self._progress_label.setText(msg)

    def _on_stop(self):
        if not (self._worker and self._worker.isRunning()):
            return
        self._worker.cancel()
        # 不在这里 wait()，会卡住界面。线程自己收尾后走 _on_fetch_done
        self._stop_btn.setEnabled(False)
        self._stop_btn.setText("停止中…")
        self._fetch_log.append(f'<span style="color:{COLORS["yellow"]}">'
                               f'⏹ 正在停止，等当前请求返回…</span>')

    def _set_running(self, running):
        self._fetch_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._stop_btn.setText("⏹ 停止")

    def _on_fetch_done(self, payload):
        total, cancelled = payload
        self._progress.setValue(100)
        if cancelled:
            self._progress_label.setText(f"已停止，本次已保存 {total:,} 条")
            self._fetch_log.append(
                f'<span style="color:{COLORS["yellow"]}">'
                f'⏹ 已停止，本次已保存 {total:,} 条 —— '
                f'已入库的数据保留，下次开增量模式接着补</span>')
        elif total > 0:
            self._progress_label.setText(f"采集完成，共 {total:,} 条记录")
            self._fetch_log.append(
                f'<span style="color:{COLORS["green"]}">✅ 完成，共 {total:,} 条</span>')
        else:
            self._progress_label.setText("采集结束，但没有拿到数据")
            self._fetch_log.append(
                f'<span style="color:{COLORS["yellow"]}">'
                f'⚠️ 一条都没拿到 —— 看上面每行末尾的原因，'
                f'或把「数据源」换一个再试</span>')
        self._set_running(False)
        self._refresh_coverage()
        self._refresh_chart()
        self._main.refresh_status()

    def _on_fetch_error(self, msg: str):
        self._fetch_log.append(f'<span style="color:{COLORS["red"]}">❌ {msg}</span>')
        self._progress_label.setText("采集失败")
        self._set_running(False)

    # ─── 量价分析 ───
    def _on_analyze(self):
        code = self._current_code()
        self._analyze_btn.setEnabled(False)
        self._status_label.setText("分析中...")

        def do_analyze():
            from analysis.a500_analyzer import A500Analyzer
            analyzer = A500Analyzer(self._main.db)
            return analyzer.full_analysis(code)

        self._worker = WorkerThread(do_analyze)
        self._worker.finished_ok.connect(self._on_analyze_done)
        self._worker.error.connect(self._on_analyze_error)
        self._worker.start()

    def _on_analyze_done(self, report: dict):
        self._analyze_btn.setEnabled(True)

        if "error" in report:
            self._status_label.setText(report["error"])
            self._signal_text.setHtml(
                f'<span style="color:{COLORS["red"]}">{report["error"]}</span>')
            return

        self._current_report = report
        self._tabs.setCurrentIndex(1)
        self._status_label.setText(f"分析完成 · {report['analysis_time']}")

        # 评分仪表
        score = report.get("score", {})
        self._gauge.set_score(score.get("total_score", 50))
        self._reco_label.setText(score.get("recommendation", "--"))

        # 因子柱状图
        pred_m = report.get("prediction_medium", {})
        self._factor_chart.set_data(pred_m.get("factor_scores", {}))

        # 概率
        p_up = pred_m.get("probability_up", 0.5)
        p_down = pred_m.get("probability_down", 0.5)
        self._prob_up_label.setText(f"上涨: {p_up*100:.1f}%")
        self._prob_down_label.setText(f"下跌: {p_down*100:.1f}%")
        self._direction_label.setText(f"方向: {pred_m.get('direction', '--')}")
        self._risk_label.setText(f"风险: {pred_m.get('risk_level', '--')}")

        # 成交量结构
        va = report.get("volume_analysis", {})
        vol_color = COLORS["green"] if va.get("vol_ratio_5_20", 1) > 1 else COLORS["red"]
        self._set_grid_items(self._vol_grid, [
            ("5日均量", f"{va.get('vol_5d_avg', 0)/10000:.1f}万", None),
            ("20日均量", f"{va.get('vol_20d_avg', 0)/10000:.1f}万", None),
            ("量比(5/20)", f"{va.get('vol_ratio_5_20', 0):.3f}", vol_color),
            ("量能状态", va.get("vol_status", "--"), COLORS["accent"]),
            ("量能趋势", va.get("vol_trend", "--"), None),
        ])

        # 技术指标
        tech = report.get("technicals", {})
        macd = tech.get("macd", {})
        rsi = tech.get("rsi_14", 50)
        rsi_color = COLORS["red"] if rsi > 70 else COLORS["green"] if rsi < 30 else None
        ma_arr = tech.get("ma_arrangement", "--")
        ma_color = COLORS["green"] if "多头" in ma_arr else COLORS["red"] if "空头" in ma_arr else None
        self._set_grid_items(self._tech_grid, [
            ("均线排列", ma_arr, ma_color),
            ("偏离MA20", f"{tech.get('price_vs_ma20', 0):.2f}%", None),
            ("MACD DIF", f"{macd.get('dif', 0):.4f}", None),
            ("MACD 信号", macd.get("signal", "--"), None),
            ("RSI(14)", f"{rsi:.1f} ({tech.get('rsi_zone', '')})", rsi_color),
        ])

        # 支撑阻力
        lvl = report.get("levels", {})
        latest = report.get("latest_price", 0)
        self._set_grid_items(self._level_grid, [
            ("阻力位", f"{lvl.get('resistance_1', 0):.3f}", COLORS["red"]),
            ("最新价", f"{latest:.3f}", COLORS["accent"]),
            ("主力成本", f"{lvl.get('poc_price', 0):.3f}", COLORS["yellow"]),
            ("支撑位", f"{lvl.get('support_1', 0):.3f}", COLORS["green"]),
            ("近期高低", f"{lvl.get('recent_low', 0):.3f} ~ {lvl.get('recent_high', 0):.3f}", None),
        ])

        # 信号
        html = []
        vp = report.get("volume_price", {})
        html.append(f'<b style="color:{COLORS["accent"]}">量价关系:</b> {vp.get("vp_relation", "--")}')
        html.append(f'<b style="color:{COLORS["accent"]}">OBV趋势:</b> {vp.get("obv_trend", "--")}')
        html.append("")

        for label, key in [("中期", "prediction_medium"), ("长期", "prediction_long")]:
            pred = report.get(key, {})
            if not pred:
                continue
            color = COLORS["green"] if pred.get("direction") == "看涨" else \
                    COLORS["red"] if pred.get("direction") == "看跌" else COLORS["yellow"]
            html.append(
                f'<b style="color:{color}">{label}预测 ({pred.get("timeframe", "")}):</b> '
                f'{pred.get("direction", "--")} · 上涨概率 {pred.get("probability_up", 0)*100:.1f}% · '
                f'目标 {pred.get("target_down", 0):.3f} ~ {pred.get("target_up", 0):.3f}')
            for s in pred.get("signals", [])[:6]:
                html.append(f'　· {s}')
            html.append("")

        self._signal_text.setHtml("<br>".join(html))

    def _on_analyze_error(self, msg: str):
        self._analyze_btn.setEnabled(True)
        self._status_label.setText("分析失败")
        self._signal_text.setHtml(f'<span style="color:{COLORS["red"]}">分析失败: {msg}</span>')
