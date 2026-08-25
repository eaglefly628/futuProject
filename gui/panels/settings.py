"""系统设置面板"""
from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QLineEdit,
    QSpinBox, QDoubleSpinBox, QCheckBox, QGridLayout,
    QMessageBox, QGroupBox
)
from PySide6.QtCore import Qt
from gui.panels.base import BasePanel
from gui.theme import COLORS


class SettingsPanel(BasePanel):
    def __init__(self, main_window):
        super().__init__(main_window, "系统设置", "管理 OpenD 连接、数据存储、下载参数等配置")
        self._build()

    def _build(self):
        # ─── OpenD 连接设置 ───
        card1, layout1 = self.make_card("🔗 OpenD 连接设置")
        grid1 = QGridLayout()
        grid1.setSpacing(10)
        grid1.addWidget(QLabel("主机地址"), 0, 0)
        self._host = QLineEdit(self._main.config.get("opend", "host", default="127.0.0.1"))
        grid1.addWidget(self._host, 0, 1)
        grid1.addWidget(QLabel("端口"), 0, 2)
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(self._main.config.get("opend", "port", default=11111))
        grid1.addWidget(self._port, 0, 3)
        self._encrypt_check = QCheckBox("启用加密")
        self._encrypt_check.setChecked(self._main.config.get("opend", "is_encrypt", default=False))
        grid1.addWidget(self._encrypt_check, 1, 0, 1, 2)
        layout1.addLayout(grid1)
        self.add_widget(card1)

        # ─── K线下载设置 ───
        card2, layout2 = self.make_card("📊 K线下载设置")
        grid2 = QGridLayout()
        grid2.setSpacing(10)
        grid2.addWidget(QLabel("单次请求最大条数"), 0, 0)
        self._max_count = QSpinBox()
        self._max_count.setRange(100, 5000)
        self._max_count.setValue(self._main.config.get("kline", "max_count_per_request", default=1000))
        grid2.addWidget(self._max_count, 0, 1)
        grid2.addWidget(QLabel("请求间隔（秒）"), 0, 2)
        self._interval = QDoubleSpinBox()
        self._interval.setRange(0.1, 10.0)
        self._interval.setSingleStep(0.1)
        self._interval.setValue(self._main.config.get("kline", "request_interval", default=0.5))
        grid2.addWidget(self._interval, 0, 3)
        layout2.addLayout(grid2)
        self.add_widget(card2)

        # ─── 逐笔采集设置 ───
        card3, layout3 = self.make_card("⚡ 逐笔采集设置")
        grid3 = QGridLayout()
        grid3.setSpacing(10)
        self._tick_enabled = QCheckBox("启用逐笔采集")
        self._tick_enabled.setChecked(self._main.config.get("tick", "enabled", default=True))
        grid3.addWidget(self._tick_enabled, 0, 0, 1, 2)
        grid3.addWidget(QLabel("采集间隔（秒）"), 1, 0)
        self._tick_interval = QDoubleSpinBox()
        self._tick_interval.setRange(0.1, 5.0)
        self._tick_interval.setSingleStep(0.1)
        self._tick_interval.setValue(self._main.config.get("tick", "collect_interval", default=0.3))
        grid3.addWidget(self._tick_interval, 1, 1)
        grid3.addWidget(QLabel("单次最大条数"), 1, 2)
        self._tick_max = QSpinBox()
        self._tick_max.setRange(100, 10000)
        self._tick_max.setValue(self._main.config.get("tick", "max_count", default=1000))
        grid3.addWidget(self._tick_max, 1, 3)
        layout3.addLayout(grid3)
        self.add_widget(card3)

        # ─── 存储设置 ───
        card4, layout4 = self.make_card("💾 存储设置")
        grid4 = QGridLayout()
        grid4.setSpacing(10)
        grid4.addWidget(QLabel("数据库路径"), 0, 0)
        self._db_path = QLineEdit(str(self._main.config.get("storage", "sqlite_path", default="")))
        self._db_path.setReadOnly(True)
        self._db_path.setStyleSheet(f"color: {COLORS['text_muted']};")
        grid4.addWidget(self._db_path, 0, 1, 1, 3)
        layout4.addLayout(grid4)
        self.add_widget(card4)

        # ─── 保存按钮 ───
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self.make_primary_btn("💾 保存配置", self._on_save))
        self.add_layout(btn_row)
        self.add_stretch()

    def _on_save(self):
        cfg = self._main.config
        cfg.set("opend", "host", self._host.text().strip())
        cfg.set("opend", "port", self._port.value())
        cfg.set("opend", "is_encrypt", self._encrypt_check.isChecked())
        cfg.set("kline", "max_count_per_request", self._max_count.value())
        cfg.set("kline", "request_interval", self._interval.value())
        cfg.set("tick", "enabled", self._tick_enabled.isChecked())
        cfg.set("tick", "collect_interval", self._tick_interval.value())
        cfg.set("tick", "max_count", self._tick_max.value())
        cfg.save()
        self._main.log("配置已保存")
        QMessageBox.information(self, "成功", "配置已保存！")
