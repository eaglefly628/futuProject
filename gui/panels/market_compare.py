"""全市场 A500 ETF 与指数对照。"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                              QCheckBox, QPushButton, QTableWidget, QTableWidgetItem,
                              QHeaderView)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QPen

from analysis.market_comparison import (compare_returns, normalized_curves,
                                        rank_comparisons)
from core.market_universe import BENCHMARKS


class ComparisonChart(QWidget):
    COLORS = ["#58a6ff", "#ffb454", "#f778ba", "#7ee787", "#d2a8ff"]

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(230)
        self.data = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0d1117"))
        painter.setPen(QColor("#c9d1d9"))
        if self.data is None or self.data.empty:
            painter.drawText(self.rect(), Qt.AlignCenter, "正在同步历史数据，完成后显示走势对照")
            return
        data = self.data
        lo, hi = float(data.min().min()), float(data.max().max())
        spread = max(hi - lo, 1)
        lo, hi = lo - spread * .1, hi + spread * .1
        width, height = self.width() - 90, self.height() - 90
        for i in range(5):
            value = lo + (hi - lo) * i / 4
            y = 45 + height * (1 - i / 4)
            painter.setPen(QColor("#30363d"))
            painter.drawLine(55, int(y), 55 + width, int(y))
            painter.setPen(QColor("#8b949e"))
            painter.drawText(3, int(y) + 4, f"{value:.1f}")
        for column_index, name in enumerate(data.columns):
            color = QColor(self.COLORS[column_index % len(self.COLORS)])
            painter.setPen(QPen(color, 2))
            values = data[name].to_numpy()
            for i in range(1, len(values)):
                painter.drawLine(int(55 + width * (i - 1) / (len(values) - 1)),
                                 int(45 + height * (hi - values[i - 1]) / (hi - lo)),
                                 int(55 + width * i / (len(values) - 1)),
                                 int(45 + height * (hi - values[i]) / (hi - lo)))
            painter.drawText(55 + column_index * 180, 23, name)
        painter.setPen(QColor("#8b949e"))
        painter.drawText(55, self.height() - 18, str(data.index[0].date()))
        painter.drawText(self.width() - 115, self.height() - 18, str(data.index[-1].date()))


class MarketComparePanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.sync = window.market_sync
        self.history = {}
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.auto = QCheckBox("自动更新")
        self.auto.setChecked(self.sync.enabled)
        self.auto.toggled.connect(self.sync.set_enabled)
        controls.addWidget(self.auto)
        refresh = QPushButton("立即同步")
        refresh.clicked.connect(self.refresh_all)
        controls.addWidget(refresh)
        controls.addWidget(QLabel("对照基准"))
        self.benchmark = QComboBox()
        for code, name in BENCHMARKS:
            self.benchmark.addItem(name, code)
        self.benchmark.setCurrentIndex(3)
        self.benchmark.currentIndexChanged.connect(self.render)
        controls.addWidget(self.benchmark)
        controls.addWidget(QLabel("交易日窗口"))
        self.period = QComboBox()
        for days in (1, 5, 20, 60):
            self.period.addItem(f"{days} 日", days)
        self.period.setCurrentIndex(2)
        self.period.currentIndexChanged.connect(self.render)
        controls.addWidget(self.period)
        self.asset = QComboBox()
        self.asset.currentIndexChanged.connect(self.render)
        controls.addWidget(self.asset)
        controls.addStretch()
        layout.addLayout(controls)
        sorting = QHBoxLayout()
        sorting.addWidget(QLabel("仅普通中证A500 ETF · 指数仅作基准"))
        sorting.addWidget(QLabel("排序"))
        self.order = QComboBox()
        for label, mode in [("超额收益由高到低", "desc"), ("超额收益由低到高", "asc"),
                            ("偏离绝对值由高到低", "abs")]:
            self.order.addItem(label, mode)
        self.order.currentIndexChanged.connect(self.render)
        sorting.addWidget(self.order)
        sorting.addWidget(QLabel("排名反映过去表现，不是买入评分"))
        sorting.addStretch()
        layout.addLayout(sorting)
        self.status = QLabel("启动时同步名单和历史；交易时段报价每3秒、日线/60分钟线每10分钟更新")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.judgement = QLabel()
        self.judgement.setWordWrap(True)
        layout.addWidget(self.judgement)
        self.chart = ComparisonChart()
        layout.addWidget(self.chart)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["排序", "代码", "名称", "最新价", "当日涨跌%",
                                             "报价时间", "窗口收益%", "基准收益%", "超额(百分点)", "比较区间"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 1)
        layout.addWidget(QLabel("历史收益按相同交易日计算，图表起点=100；缺失数据显示 —。"
                               "当日K线可能尚未收盘，价格收益未计分红与费用。"))
        self.sync.universe_changed.connect(self.set_universe)
        self.sync.quotes_updated.connect(self.render)
        self.sync.history_updated.connect(self.load_history)
        self.sync.status_changed.connect(self.status.setText)
        self.set_universe(self.sync.etfs)

    def refresh_all(self):
        self.sync.refresh_quotes(force=True)
        self.sync.refresh_history(force=True)

    def set_universe(self, items):
        selected = self.asset.currentData() or "SH.560530"
        self.asset.blockSignals(True)
        self.asset.clear()
        for code, name in items:
            self.asset.addItem(name, code)
        index = self.asset.findData(selected)
        self.asset.setCurrentIndex(max(0, index))
        self.asset.blockSignals(False)
        self.load_history()

    def load_history(self):
        self.history = {code: self.window.db.get_kline(code, "K_DAY") for code in self.sync.codes}
        self.render()

    def render(self, *args):
        if not hasattr(self, "table"):
            return
        benchmark = self.history.get(self.benchmark.currentData())
        days = self.period.currentData()
        items = self.sync.etfs
        rows = [(code, name, compare_returns(self.history.get(code), benchmark, days))
                for code, name in items]
        rows = rank_comparisons(rows, self.order.currentData())
        self.table.setRowCount(len(rows))
        returns, excess = [], []
        for row, (code, name, result) in enumerate(rows):
            quote = self.sync.quotes.get(code, {})
            price, change = quote.get("price"), quote.get("change_rate")
            values = [str(row + 1) if result else "—", code, name,
                      f"{price:.3f}" if price is not None else "—",
                      f"{change:+.2f}" if change is not None else "—", quote.get("time", "—")]
            values += ([f"{result['return']:+.2f}", f"{result['benchmark_return']:+.2f}",
                        f"{result['excess']:+.2f}", f"{result['start']} ~ {result['end']}"]
                       if result else ["—"] * 4)
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
            if result and code not in {c for c, _ in BENCHMARKS}:
                returns.append(result["return"])
                excess.append(result["excess"])
        if returns:
            positive = sum(value > 0 for value in returns)
            outperform = sum(value > 0 for value in excess)
            self.summary.setText(f"普通A500 ETF {len(self.sync.etfs)} 只 · 可比较 {len(returns)} 只 · "
                                 f"{days}日上涨 {positive} 只 · 跑赢基准 {outperform} 只 · "
                                 f"平均超额 {sum(excess)/len(excess):+.2f} 个百分点")
        else:
            self.summary.setText(f"A500 ETF {len(self.sync.etfs)} 只 · 当前窗口数据不足，等待同步")
        selected = compare_returns(self.history.get(self.asset.currentData()), benchmark, days)
        index_results = [compare_returns(self.history.get(code), benchmark, days)
                         for code, _ in BENCHMARKS]
        if selected:
            relative = "强于" if selected["excess"] > 0 else "弱于" if selected["excess"] < 0 else "持平于"
            available = [result for result in index_results if result]
            if len(available) == 4:
                market = ("四个指数同期上涨" if all(r["return"] > 0 for r in available)
                          else "四个指数同期下跌" if all(r["return"] < 0 for r in available)
                          else "指数走势分化")
            else:
                market = "指数历史尚未齐全"
            self.judgement.setText(f"{self.asset.currentText()}：{days}日价格收益 {selected['return']:+.2f}% · "
                                    f"相对{relative}{self.benchmark.currentText()} "
                                    f"{abs(selected['excess']):.2f} 个百分点 · {market}")
        else:
            self.judgement.setText("所选 ETF 暂无足够的共同交易日，暂不判断相对强弱")
        self.render_chart()

    def render_chart(self, *args):
        if not hasattr(self, "chart"):
            return
        frames = {name: self.history.get(code) for code, name in BENCHMARKS}
        if self.asset.currentData():
            frames[self.asset.currentText()] = self.history.get(self.asset.currentData())
        self.chart.data = normalized_curves(frames, self.period.currentData() or 60)
        self.chart.update()
