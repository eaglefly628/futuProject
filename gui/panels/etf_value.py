"""普通 A500 ETF 的净值偏离筛查。"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                              QPushButton, QTableWidget, QTableWidgetItem, QHeaderView)


def fmt(value, digits=3, signed=False):
    return (f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}") if value is not None else "—"


class ETFValuePanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.sync = window.market_sync
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("普通A500 ETF · 价格相对参考净值"))
        self.order = QComboBox()
        for label, field in [("卖一价偏离：低 → 高", "ask_premium_pct"),
                             ("成交价偏离：低 → 高", "premium_pct"),
                             ("买卖价差：小 → 大", "spread_pct")]:
            self.order.addItem(label, field)
        self.order.currentIndexChanged.connect(self.render)
        controls.addWidget(self.order)
        button = QPushButton("更新净值与盘口")
        button.clicked.connect(self.refresh)
        controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        note = QLabel("偏离=(价格÷参考净值−1)×100%，负数为折价、正数为溢价。"
                      "IOPV为估算参考净值，接口未提供独立时间戳；盘后盘口、未核时数据仅供筛查。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 16)
        self.table.setHorizontalHeaderLabels([
            "序号", "代码", "名称", "成交价", "IOPV", "成交价偏离%", "卖一价",
            "卖一价偏离%", "价差%", "成交额(万元)", "正式净值", "净值日期",
            "管理/托管费(%/年)", "费率核验", "源行情更新时间", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 1)
        footnote = QLabel("正式净值由东财转录基金披露；昨晚净值只用于核对，不与今天价格计算折价。"
                          "卖一价只代表该档报价，小额折价还需覆盖佣金、滑点；不自动生成买入建议。")
        footnote.setWordWrap(True)
        layout.addWidget(footnote)
        self.sync.values_updated.connect(self.render)
        self.sync.universe_changed.connect(self.render)
        self.render()

    def refresh(self):
        self.sync.refresh_values(force=True)
        self.sync.refresh_references(force=True)

    def render(self, *args):
        if not hasattr(self, "table"):
            return
        field = self.order.currentData()
        rows = [dict(self.sync.values.get(code, {}), code=code, name=name)
                for code, name in self.sync.etfs]
        rows.sort(key=lambda row: (row.get(field) is None, row.get(field) or 0))
        self.table.setRowCount(len(rows))
        available = sum(row.get("iopv") is not None for row in rows)
        discounted = sum(row.get("premium_pct") is not None and row["premium_pct"] < 0 for row in rows)
        ask_discounted = sum(row.get("ask_premium_pct") is not None and row["ask_premium_pct"] < 0 for row in rows)
        self.summary.setText(f"{len(rows)} 只普通A500 ETF · IOPV可用 {available} 只 · 成交价折价 {discounted} 只 · "
                             f"卖一报价折价 {ask_discounted} 只 · 获取时间 {self.sync.value_fetched_at or '等待更新'}")
        for index, row in enumerate(rows):
            fee = f"{fmt(row.get('management_fee_pct'), 2)} / {fmt(row.get('custody_fee_pct'), 2)}"
            status = "IOPV时间未核验" if row.get("iopv") else "暂无IOPV"
            values = [index + 1, row["code"], row["name"], fmt(row.get("price")), fmt(row.get("iopv"), 4),
                      fmt(row.get("premium_pct"), 3, True), fmt(row.get("ask")),
                      fmt(row.get("ask_premium_pct"), 3, True), fmt(row.get("spread_pct"), 3),
                      fmt(row["turnover"] / 10000, 1) if row.get("turnover") is not None else "—",
                      fmt(row.get("nav"), 4), row.get("nav_date") or "—", fee,
                      "官网费率页" if row.get("fee_verified") else "摘要待官方核验",
                      row.get("quote_time") or "—", status]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(f"行情：{row.get('market_source_url', '—')}\n"
                                f"净值：{row.get('nav_source_url', '—')}\n"
                                f"费率：{row.get('fee_source_url', '—')}\n"
                                f"净值错误：{row.get('nav_error', '无')}\nIOPV独立时间戳：未提供")
                self.table.setItem(index, column, item)
