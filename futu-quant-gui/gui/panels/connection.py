"""连接管理面板"""
from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QTextEdit, QFrame
)
from PySide6.QtCore import Qt
from gui.panels.base import BasePanel
from gui.widgets.worker import WorkerThread
from gui.theme import COLORS


class ConnectionPanel(BasePanel):
    def __init__(self, main_window):
        super().__init__(main_window, "连接管理", "管理与 Futu OpenD 网关的连接")
        self._worker = None
        self._build()

    def _build(self):
        # ─── 连接状态卡片 ───
        status_card = QFrame()
        status_card.setObjectName("card")
        status_layout = QVBoxLayout(status_card)

        self._status_icon = QLabel("⬤")
        self._status_icon.setStyleSheet(f"font-size: 48px; color: {COLORS['red']};")
        self._status_icon.setAlignment(Qt.AlignCenter)
        status_layout.addWidget(self._status_icon)

        self._status_text = QLabel("未连接")
        self._status_text.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {COLORS['text_primary']};")
        self._status_text.setAlignment(Qt.AlignCenter)
        status_layout.addWidget(self._status_text)

        host = self._main.config.get("opend", "host", default="127.0.0.1")
        port = self._main.config.get("opend", "port", default=11111)
        self._addr_label = QLabel(f"目标地址: {host}:{port}")
        self._addr_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        self._addr_label.setAlignment(Qt.AlignCenter)
        status_layout.addWidget(self._addr_label)

        self.add_widget(status_card)

        # ─── 操作按钮 ───
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._connect_btn = self.make_primary_btn("🔗 连接 OpenD", self._on_connect)
        self._disconnect_btn = self.make_danger_btn("断开连接", self._on_disconnect)
        self._disconnect_btn.setEnabled(False)
        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._disconnect_btn)
        btn_row.addStretch()
        self.add_layout(btn_row)

        # ─── 提示信息 ───
        info_card, info_layout = self.make_card("使用说明")
        tips = QLabel(
            "1. 请先从 <a href='https://openapi.futunn.com/' style='color:#F0883E;'>Futu 官网</a> 下载并安装 OpenD 网关<br>"
            "2. 启动 OpenD 并确保运行在配置的地址和端口上<br>"
            "3. 确保已安装 futu-api：<code style='color:#58A6FF;'>pip install futu-api</code><br>"
            "4. 点击上方「连接」按钮建立连接"
        )
        tips.setOpenExternalLinks(True)
        tips.setWordWrap(True)
        tips.setStyleSheet(f"color: {COLORS['text_secondary']}; line-height: 1.8; font-size: 13px;")
        info_layout.addWidget(tips)
        self.add_widget(info_card)

        # ─── 日志 ───
        log_card, log_layout = self.make_card("连接日志")
        self._log = QTextEdit()
        self._log.setObjectName("logPanel")
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(150)
        log_layout.addWidget(self._log)
        self.add_widget(log_card)
        self.add_stretch()

    def on_show(self):
        self._update_status_display()

    def _update_status_display(self):
        connected = self._main.is_connected
        if connected:
            self._status_icon.setStyleSheet(f"font-size: 48px; color: {COLORS['green']};")
            self._status_text.setText("已连接")
            self._status_text.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {COLORS['green']};")
        else:
            self._status_icon.setStyleSheet(f"font-size: 48px; color: {COLORS['red']};")
            self._status_text.setText("未连接")
            self._status_text.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {COLORS['text_muted']};")
        self._connect_btn.setEnabled(not connected)
        self._disconnect_btn.setEnabled(connected)

        host = self._main.config.get("opend", "host", default="127.0.0.1")
        port = self._main.config.get("opend", "port", default=11111)
        self._addr_label.setText(f"目标地址: {host}:{port}")

    def _on_connect(self):
        self._log.append("正在连接 Futu OpenD...")
        self._connect_btn.setEnabled(False)

        def do_connect():
            from core.client import FutuClient
            host = self._main.config.get("opend", "host", default="127.0.0.1")
            port = self._main.config.get("opend", "port", default=11111)
            client = FutuClient(host=host, port=port)
            client.connect_quote()
            return client

        self._worker = WorkerThread(do_connect)
        self._worker.finished_ok.connect(self._on_connected)
        self._worker.error.connect(self._on_connect_error)
        self._worker.start()

    def _on_connected(self, client):
        self._main.client = client

        from downloaders.kline_downloader import KlineDownloader
        from downloaders.tick_collector import TickCollector
        self._main.kline_dl = KlineDownloader(client, self._main.db, self._main.config)
        self._main.tick_cl = TickCollector(client, self._main.db, self._main.config)
        self._main.set_connected(True)

        self._log.append(f'<span style="color:{COLORS["green"]}">✅ 连接成功！</span>')
        self._main.log("Futu OpenD 连接成功")
        self._update_status_display()

    def _on_connect_error(self, msg):
        self._log.append(f'<span style="color:{COLORS["red"]}">❌ 连接失败: {msg}</span>')
        self._log.append(f'<span style="color:{COLORS["text_muted"]}">请确保 OpenD 已启动且 futu-api 已安装</span>')
        self._main.log(f"连接失败: {msg}")
        self._connect_btn.setEnabled(True)

    def _on_disconnect(self):
        if self._main.client:
            try:
                self._main.client.close()
            except Exception:
                pass
            self._main.client = None
        self._main.set_connected(False)
        self._log.append("已断开连接")
        self._main.log("已断开 Futu OpenD 连接")
        self._update_status_display()
