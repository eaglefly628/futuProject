"""数据导出面板"""
import os
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QCheckBox, QTextEdit, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt
from gui.panels.base import BasePanel
from gui.theme import COLORS

KTYPE_LIST = ["K_1M", "K_3M", "K_5M", "K_15M", "K_30M", "K_60M", "K_DAY", "K_WEEK", "K_MON"]


class ExportPanel(BasePanel):
    def __init__(self, main_window):
        super().__init__(main_window, "数据导出", "将数据库中的K线数据导出为 Parquet / CSV 文件")
        self._build()

    def _build(self):
        card, layout = self.make_card("导出设置")

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("股票代码"))
        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("如 US.AAPL")
        row1.addWidget(self._code_input)
        row1.addWidget(QLabel("K线类型"))
        self._ktype_combo = QComboBox()
        self._ktype_combo.addItems(KTYPE_LIST)
        self._ktype_combo.setCurrentText("K_DAY")
        row1.addWidget(self._ktype_combo)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self._parquet_check = QCheckBox("Parquet 格式")
        self._parquet_check.setChecked(True)
        self._csv_check = QCheckBox("CSV 格式")
        self._csv_check.setChecked(True)
        row2.addWidget(self._parquet_check)
        row2.addWidget(self._csv_check)
        row2.addStretch()
        layout.addLayout(row2)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.make_primary_btn("💾 导出", self._on_export))
        btn_row.addStretch()
        layout.addLayout(btn_row)
        self.add_widget(card)

        log_card, log_layout = self.make_card("导出结果")
        self._log = QTextEdit()
        self._log.setObjectName("logPanel")
        self._log.setReadOnly(True)
        log_layout.addWidget(self._log)
        self.add_widget(log_card)
        self.add_stretch()

    def _on_export(self):
        code = self._code_input.text().strip()
        ktype = self._ktype_combo.currentText()
        if not code:
            QMessageBox.warning(self, "提示", "请输入股票代码")
            return
        if not self._parquet_check.isChecked() and not self._csv_check.isChecked():
            QMessageBox.warning(self, "提示", "请选择至少一种导出格式")
            return

        results = []
        if self._parquet_check.isChecked():
            pdir = self._main.config.get("storage", "parquet_dir")
            path = self._main.db.export_to_parquet(code, ktype, pdir)
            if path:
                results.append(f"Parquet: {path}")

        if self._csv_check.isChecked():
            cdir = self._main.config.get("storage", "csv_dir")
            path = self._main.db.export_to_csv(code, ktype, cdir)
            if path:
                results.append(f"CSV: {path}")

        if results:
            for r in results:
                self._log.append(f'<span style="color:{COLORS["green"]}">✅ {r}</span>')
            self._main.log(f"导出完成: {code} {ktype}")
        else:
            self._log.append(f'<span style="color:{COLORS["yellow"]}">⚠️ 无数据可导出: {code} {ktype}</span>')
