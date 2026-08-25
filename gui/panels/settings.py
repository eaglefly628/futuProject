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
        grid1.setContentsMargins(0, 0, 0, 0)
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
        grid2.setContentsMargins(0, 0, 0, 0)
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
        grid3.setContentsMargins(0, 0, 0, 0)
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
        grid4.setContentsMargins(0, 0, 0, 0)
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
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch()
        btn_row.addWidget(self.make_primary_btn("💾 保存配置", self._on_save))
        self.add_layout(btn_row)

        # ─── 环境诊断 ───
        diag_card, diag_layout = self.make_card(
            "🩺 环境诊断  ·  一键检查依赖、配置、OpenD、行情源连通性")

        diag_btn_row = QHBoxLayout()
        diag_btn_row.setContentsMargins(0, 0, 0, 0)
        self._diag_btn = self.make_primary_btn("🩺 开始检测", self._on_diagnose)
        diag_btn_row.addWidget(self._diag_btn)

        self._diag_net_check = QCheckBox("包含网络测试（较慢）")
        self._diag_net_check.setChecked(True)
        diag_btn_row.addWidget(self._diag_net_check)

        self._diag_status = QLabel()
        self._diag_status.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:12px;")
        diag_btn_row.addWidget(self._diag_status)
        diag_btn_row.addStretch()
        diag_layout.addLayout(diag_btn_row)

        from PySide6.QtWidgets import QTextEdit
        self._diag_out = QTextEdit()
        self._diag_out.setMinimumHeight(280)
        self._diag_out.setObjectName("logPanel")
        self._diag_out.setReadOnly(True)
        self._diag_out.setPlaceholderText("点「开始检测」查看环境状况")
        diag_layout.addWidget(self._diag_out)

        self.add_widget(diag_card)
        self._content_layout.setStretchFactor(diag_card, 1)

    # ═══════════════════════════════════════
    #  环境诊断
    # ═══════════════════════════════════════
    def _on_diagnose(self):
        from gui.widgets.worker import WorkerThread
        from core.diagnostics import run_diagnostics

        self._diag_btn.setEnabled(False)
        self._diag_out.clear()
        self._diag_status.setText("检测中...")
        want_net = self._diag_net_check.isChecked()

        worker = WorkerThread(lambda: None)
        worker._func = lambda: run_diagnostics(
            progress=lambda m: worker.progress.emit(m),
            check_network=want_net)
        self._diag_worker = worker
        worker.progress.connect(self._diag_status.setText)
        worker.finished_ok.connect(self._on_diagnose_done)
        worker.error.connect(self._on_diagnose_error)
        worker.start()

    def _on_diagnose_done(self, rep):
        from core.diagnostics import OK, WARN, FAIL, INFO

        self._diag_btn.setEnabled(True)
        color_map = {
            OK: COLORS["green"],
            WARN: COLORS["yellow"],
            FAIL: COLORS["red"],
            INFO: COLORS["text_secondary"],
        }
        mark_map = {OK: "✓", WARN: "!", FAIL: "✗", INFO: "·"}

        html = []
        for section, checks in rep.sections.items():
            html.append(
                f'<div style="color:{COLORS["accent"]};font-weight:bold;'
                f'margin-top:8px">【{section}】</div>')
            for c in checks:
                col = color_map.get(c.status, COLORS["text_primary"])
                detail = (str(c.detail).replace("&", "&amp;")
                          .replace("<", "&lt;").replace(">", "&gt;"))
                html.append(
                    f'<div style="color:{col}">'
                    f'{mark_map.get(c.status, " ")} <b>{c.name}</b>&nbsp; {detail}</div>')
                if c.hint:
                    html.append(
                        f'<div style="color:{COLORS["text_muted"]};'
                        f'margin-left:18px">→ {c.hint}</div>')

        html.append("<br>")
        if rep.missing_required:
            cmd = "pip install " + " ".join(rep.missing_required)
            html.append(
                f'<div style="color:{COLORS["red"]}"><b>缺少必需依赖</b>，'
                f'请执行：<code>{cmd}</code></div>')
        else:
            html.append(
                f'<div style="color:{COLORS["green"]}">'
                f'<b>必需依赖齐全，可正常运行</b></div>')
        if rep.missing_optional:
            cmd = "pip install " + " ".join(rep.missing_optional)
            html.append(
                f'<div style="color:{COLORS["yellow"]}">可选未装：'
                f'<code>{cmd}</code></div>')

        # A股能不能拉，直接给结论
        if self._diag_net_check.isChecked():
            if rep.a_share_ok:
                srcs = " / ".join(rep.usable_sources)
                html.append(
                    f'<div style="color:{COLORS["green"]};margin-top:6px">'
                    f'<b>A股数据源可用（{srcs}）</b> —— '
                    f'可直接在「A500中心 → 数据采集」开始采集</div>')
                if not rep.eastmoney_ok:
                    html.append(
                        f'<div style="color:{COLORS["yellow"]}">'
                        f'东财不可达，但 Yahoo 通；采集时把「数据源」选 '
                        f'<b>Yahoo</b> 或 <b>自动</b> 即可</div>')
            else:
                html.append(
                    f'<div style="color:{COLORS["red"]};margin-top:6px">'
                    f'<b>东财与 Yahoo 均不可访问</b> —— A股数据无法下载，'
                    f'需检查网络/代理设置</div>')

        self._diag_out.setHtml("".join(html))
        self._diag_status.setText("检测完成")

    def _on_diagnose_error(self, msg):
        self._diag_btn.setEnabled(True)
        self._diag_status.setText("检测失败")
        self._diag_out.setHtml(
            f'<span style="color:{COLORS["red"]}">诊断出错: {msg}</span>')

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
