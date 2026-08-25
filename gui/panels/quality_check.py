"""数据质量检查面板"""
from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QLineEdit,
    QComboBox, QGridLayout, QFrame, QMessageBox
)
from PySide6.QtCore import Qt
from gui.panels.base import BasePanel
from gui.theme import COLORS

KTYPE_LIST = ["K_1M", "K_3M", "K_5M", "K_15M", "K_30M", "K_60M", "K_DAY", "K_WEEK", "K_MON"]


class QualityCheckPanel(BasePanel):
    def __init__(self, main_window):
        super().__init__(main_window, "数据质量检查", "检测数据中的异常、缺失和跳价")
        self._build()

    def _build(self):
        # 参数
        card, layout = self.make_card("检查参数")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("股票代码"))
        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("如 US.AAPL")
        row.addWidget(self._code_input)
        row.addWidget(QLabel("K线类型"))
        self._ktype_combo = QComboBox()
        self._ktype_combo.addItems(KTYPE_LIST)
        self._ktype_combo.setCurrentText("K_DAY")
        row.addWidget(self._ktype_combo)
        row.addWidget(self.make_primary_btn("🔬 检查", self._on_check))
        layout.addLayout(row)
        self.add_widget(card)

        # 结果卡片
        result_card, result_layout = self.make_card("检查报告")
        self._result_grid = QGridLayout()
        self._result_grid.setSpacing(16)
        self._fields = {}
        fields = [
            ("records", "总记录数", 0, 0),
            ("date_range", "时间范围", 0, 1),
            ("nulls", "空值数量", 1, 0),
            ("duplicates", "重复记录", 1, 1),
            ("price_range", "价格区间", 2, 0),
            ("max_up", "最大涨幅", 2, 1),
            ("max_down", "最大跌幅", 3, 0),
            ("anomalies", "异常跳价(>20%)", 3, 1),
            ("avg_vol", "平均成交量", 4, 0),
            ("zero_vol", "零成交K线", 4, 1),
        ]
        for key, label, r, c in fields:
            item = self._make_result_item(label)
            self._result_grid.addWidget(item, r, c)
            self._fields[key] = item

        result_layout.addLayout(self._result_grid)
        self._no_data_label = QLabel("请选择股票和K线类型后点击检查")
        self._no_data_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 14px; padding: 20px;")
        self._no_data_label.setAlignment(Qt.AlignCenter)
        result_layout.addWidget(self._no_data_label)

        self.add_widget(result_card)
        self.add_stretch()

        # 初始隐藏结果
        for w in self._fields.values():
            w.setVisible(False)

    def _make_result_item(self, label):
        f = QFrame()
        f.setObjectName("card")
        f.setStyleSheet(f"""
            #card {{ background-color: {COLORS['bg_dark']}; border: 1px solid {COLORS['border']}; border-radius: 6px; padding: 12px; }}
        """)
        layout = QVBoxLayout(f)
        layout.setSpacing(4)
        val = QLabel("-")
        val.setObjectName("_val")
        val.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLORS['text_primary']};")
        layout.addWidget(val)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"font-size: 11px; color: {COLORS['text_secondary']};")
        layout.addWidget(lbl)
        return f

    def _set_field(self, key, value, color=None):
        widget = self._fields.get(key)
        if widget:
            widget.setVisible(True)
            val_label = widget.findChild(QLabel, "_val")
            if val_label:
                val_label.setText(str(value))
                if color:
                    val_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {color};")

    def _on_check(self):
        code = self._code_input.text().strip()
        ktype = self._ktype_combo.currentText()
        if not code:
            QMessageBox.warning(self, "提示", "请输入股票代码")
            return

        report = self._main.analyzer.data_quality_check(code, ktype)
        if report.get("status") == "empty":
            self._no_data_label.setText(f"⚠️ {code} {ktype} 无数据")
            self._no_data_label.setVisible(True)
            for w in self._fields.values():
                w.setVisible(False)
            return

        self._no_data_label.setVisible(False)
        self._set_field("records", f"{report['total_records']:,}", COLORS['accent'])
        self._set_field("date_range", report.get("date_range", "-"))
        self._set_field("nulls", report.get("null_count", 0),
                        COLORS['green'] if report.get("null_count", 0) == 0 else COLORS['red'])
        self._set_field("duplicates", report.get("duplicate_count", 0),
                        COLORS['green'] if report.get("duplicate_count", 0) == 0 else COLORS['red'])
        self._set_field("price_range", report.get("price_range", "-"))
        self._set_field("max_up", report.get("max_daily_change", "-"), COLORS['green'])
        self._set_field("max_down", report.get("min_daily_change", "-"), COLORS['red'])
        anomalies = report.get("anomaly_count", 0)
        self._set_field("anomalies", f"{anomalies} 次",
                        COLORS['green'] if anomalies == 0 else COLORS['yellow'])
        self._set_field("avg_vol", report.get("avg_volume", "-"))
        zero_vol = report.get("zero_volume_count", 0)
        self._set_field("zero_vol", f"{zero_vol} 根",
                        COLORS['green'] if zero_vol == 0 else COLORS['yellow'])
