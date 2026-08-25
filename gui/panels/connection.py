"""连接管理面板 - OpenD 一键启动 + 连接"""
from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QTextEdit, QFrame,
    QLineEdit, QCheckBox, QPushButton, QFileDialog, QGridLayout,
    QSpinBox, QComboBox, QMessageBox
)
from PySide6.QtCore import Qt, QTimer
from gui.panels.base import BasePanel
from gui.widgets.worker import WorkerThread
from gui.theme import COLORS


class ConnectionPanel(BasePanel):
    def __init__(self, main_window):
        super().__init__(main_window, "连接管理", "启动 OpenD 网关并建立连接")
        self._worker = None
        self._launcher = None
        self._verify_timer = None
        self._verify_elapsed = 0
        self._build()
        self._init_launcher()

        # 定时刷新 OpenD 进程状态
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_opend_status)
        self._timer.start(2000)

    # ═══════════════════════════════════════
    def _build(self):
        # ─── 状态卡片 ───
        status_card = QFrame()
        status_card.setObjectName("card")
        status_layout = QHBoxLayout(status_card)
        status_layout.setSpacing(30)

        # OpenD 进程状态
        opend_box = QVBoxLayout()
        self._opend_icon = QLabel("⬤")
        self._opend_icon.setStyleSheet(f"font-size: 36px; color: {COLORS['text_muted']};")
        self._opend_icon.setAlignment(Qt.AlignCenter)
        opend_box.addWidget(self._opend_icon)
        self._opend_text = QLabel("OpenD 未运行")
        self._opend_text.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {COLORS['text_muted']};")
        self._opend_text.setAlignment(Qt.AlignCenter)
        opend_box.addWidget(self._opend_text)
        status_layout.addLayout(opend_box)

        # 分隔
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {COLORS['border']};")
        status_layout.addWidget(sep)

        # API 连接状态
        api_box = QVBoxLayout()
        self._status_icon = QLabel("⬤")
        self._status_icon.setStyleSheet(f"font-size: 36px; color: {COLORS['red']};")
        self._status_icon.setAlignment(Qt.AlignCenter)
        api_box.addWidget(self._status_icon)
        self._status_text = QLabel("API 未连接")
        self._status_text.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {COLORS['text_muted']};")
        self._status_text.setAlignment(Qt.AlignCenter)
        api_box.addWidget(self._status_text)
        status_layout.addLayout(api_box)

        status_layout.addStretch()

        # 地址信息
        addr_box = QVBoxLayout()
        self._addr_label = QLabel()
        self._addr_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        addr_box.addWidget(self._addr_label)
        self._exe_label = QLabel()
        self._exe_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        self._exe_label.setWordWrap(True)
        addr_box.addWidget(self._exe_label)
        status_layout.addLayout(addr_box, 1)

        self.add_widget(status_card)

        # ─── OpenD 启动配置 ───
        cfg_card, cfg_layout = self.make_card("OpenD 启动配置")
        grid = QGridLayout()
        grid.setSpacing(10)
        grid.setColumnStretch(1, 1)

        # 可执行文件路径
        grid.addWidget(QLabel("OpenD 路径:"), 0, 0)
        path_row = QHBoxLayout()
        self._exe_input = QLineEdit()
        self._exe_input.setPlaceholderText("留空则自动在项目 FutuOpenD/ 目录下查找")
        path_row.addWidget(self._exe_input, 1)
        browse_btn = QPushButton("浏览...")
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(browse_btn)
        detect_btn = QPushButton("自动检测")
        detect_btn.setCursor(Qt.PointingHandCursor)
        detect_btn.clicked.connect(self._on_autodetect)
        path_row.addWidget(detect_btn)
        grid.addLayout(path_row, 0, 1)

        # 账号
        grid.addWidget(QLabel("牛牛号:"), 1, 0)
        self._account_input = QLineEdit()
        self._account_input.setPlaceholderText("平台ID / 邮箱 / 手机号")
        grid.addWidget(self._account_input, 1, 1)

        # 密码
        grid.addWidget(QLabel("登录密码:"), 2, 0)
        pwd_row = QHBoxLayout()
        self._pwd_input = QLineEdit()
        self._pwd_input.setEchoMode(QLineEdit.Password)
        self._pwd_input.setPlaceholderText("交易密码（本地 MD5 加密后保存）")
        pwd_row.addWidget(self._pwd_input, 1)
        self._remember_check = QCheckBox("记住")
        self._remember_check.setToolTip(
            "勾选后账号和密码MD5保存到 config/local.yaml（已 gitignore，不会提交）")
        pwd_row.addWidget(self._remember_check)
        grid.addLayout(pwd_row, 2, 1)

        # 端口 / 语言 / 控制台
        grid.addWidget(QLabel("API 端口:"), 3, 0)
        opt_row = QHBoxLayout()
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(11111)
        self._port_spin.setMaximumWidth(100)
        opt_row.addWidget(self._port_spin)

        opt_row.addWidget(QLabel("语言:"))
        self._lang_combo = QComboBox()
        self._lang_combo.addItem("简体中文", "chs")
        self._lang_combo.addItem("English", "en")
        self._lang_combo.setMaximumWidth(110)
        opt_row.addWidget(self._lang_combo)

        self._console_check = QCheckBox("显示 OpenD 控制台窗口")
        opt_row.addWidget(self._console_check)
        opt_row.addStretch()
        grid.addLayout(opt_row, 3, 1)

        cfg_layout.addLayout(grid)

        # 启动按钮行
        btn_row = QHBoxLayout()
        self._launch_btn = self.make_primary_btn("▶ 启动 OpenD 并连接", self._on_launch_and_connect)
        btn_row.addWidget(self._launch_btn)

        self._stop_opend_btn = self.make_danger_btn("■ 停止 OpenD", self._on_stop_opend)
        self._stop_opend_btn.setEnabled(False)
        btn_row.addWidget(self._stop_opend_btn)

        btn_row.addStretch()

        self._connect_btn = QPushButton("🔗 仅连接（OpenD 已在运行）")
        self._connect_btn.setCursor(Qt.PointingHandCursor)
        self._connect_btn.clicked.connect(self._on_connect)
        btn_row.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("断开连接")
        self._disconnect_btn.setCursor(Qt.PointingHandCursor)
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        self._disconnect_btn.setEnabled(False)
        btn_row.addWidget(self._disconnect_btn)

        cfg_layout.addLayout(btn_row)
        self.add_widget(cfg_card)

        # ─── OpenD 终端 ───
        from gui.widgets.terminal import OpenDTerminal
        term_card, term_layout = self.make_card(
            "OpenD 终端  ·  可直接输入命令（如手机验证码）")
        self._terminal = OpenDTerminal()
        term_layout.addWidget(self._terminal)
        self.add_widget(term_card)
        self._content_layout.setStretchFactor(term_card, 1)

    # ═══════════════════════════════════════
    def _init_launcher(self):
        """初始化启动器并回填配置"""
        from core.opend_launcher import OpenDLauncher

        cfg = self._main.config
        exe_path = cfg.get("opend", "exe_path", default="")
        self._launcher = OpenDLauncher(exe_path or None)
        self._terminal.attach(self._launcher)

        if not exe_path:
            if self._launcher.auto_discover():
                self._exe_input.setText(str(self._launcher.exe_path))
                self._terminal.append(f'✓ 自动发现 OpenD: '
                    f'{self._launcher.exe_path}')
            else:
                self._terminal.append(f'⚠ 未在项目目录下找到 OpenD，'
                    f'请手动指定路径或将 OpenD 放入 FutuOpenD/ 目录')
        else:
            self._exe_input.setText(exe_path)

        # 回填账号
        account = cfg.get("opend", "account", default="")
        if account:
            self._account_input.setText(str(account))
        pwd_md5 = cfg.get("opend", "pwd_md5", default="")
        if pwd_md5:
            self._pwd_input.setText("")
            self._pwd_input.setPlaceholderText("已保存密码（留空则使用已保存的）")
            self._remember_check.setChecked(True)

        self._port_spin.setValue(int(cfg.get("opend", "port", default=11111)))
        self._update_status_display()

    def on_show(self):
        self._update_status_display()
        self._update_opend_status()

    # ─── 路径选择 ───
    def _on_browse(self):
        import platform
        if platform.system() == "Windows":
            filt = "OpenD (FutuOpenD.exe);;所有文件 (*)"
        else:
            filt = "所有文件 (*)"
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 OpenD 可执行文件", str(Path.cwd()), filt)
        if path:
            self._exe_input.setText(path)
            self._launcher.set_exe_path(path)
            self._update_status_display()

    def _on_autodetect(self):
        from core.opend_launcher import list_opend_candidates
        found = list_opend_candidates()
        if not found:
            QMessageBox.information(
                self, "未找到",
                "未在项目目录下找到 OpenD。\n\n"
                "请将 OpenD 解压到项目的 FutuOpenD/ 目录，例如：\n"
                "FutuOpenD/windows/Futu_OpenD_x.x.x_Windows/FutuOpenD.exe\n\n"
                "或点击「浏览...」手动指定。")
            return
        self._exe_input.setText(str(found[0]))
        self._launcher.set_exe_path(str(found[0]))
        self._terminal.append(f'✓ 已选择: {found[0]}')
        if len(found) > 1:
            self._terminal.append(f'（共发现 {len(found)} 个，'
                f'如需切换请用「浏览...」）')
        self._update_status_display()

    # ─── 状态显示 ───
    def _update_opend_status(self):
        running = self._launcher is not None and self._launcher.is_running()
        if running:
            self._opend_icon.setStyleSheet(f"font-size: 36px; color: {COLORS['green']};")
            self._opend_text.setText("OpenD 运行中")
            self._opend_text.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {COLORS['green']};")
            self._stop_opend_btn.setEnabled(True)
        else:
            self._opend_icon.setStyleSheet(f"font-size: 36px; color: {COLORS['text_muted']};")
            self._opend_text.setText("OpenD 未运行")
            self._opend_text.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {COLORS['text_muted']};")
            self._stop_opend_btn.setEnabled(False)

    def _update_status_display(self):
        connected = self._main.is_connected
        if connected:
            self._status_icon.setStyleSheet(f"font-size: 36px; color: {COLORS['green']};")
            self._status_text.setText("API 已连接")
            self._status_text.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {COLORS['green']};")
        else:
            self._status_icon.setStyleSheet(f"font-size: 36px; color: {COLORS['red']};")
            self._status_text.setText("API 未连接")
            self._status_text.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {COLORS['text_muted']};")

        self._connect_btn.setEnabled(not connected)
        self._disconnect_btn.setEnabled(connected)
        self._launch_btn.setEnabled(not connected)

        host = self._main.config.get("opend", "host", default="127.0.0.1")
        port = self._port_spin.value()
        self._addr_label.setText(f"目标地址: {host}:{port}")

        exe = self._exe_input.text().strip()
        if exe:
            self._exe_label.setText(f"OpenD: {exe}")
        else:
            self._exe_label.setText("OpenD: 未指定")

    # ─── 启动 + 连接 ───
    def _on_launch_and_connect(self):
        exe = self._exe_input.text().strip()
        if not exe:
            QMessageBox.warning(self, "缺少路径",
                                "请先指定 OpenD 可执行文件路径（可点「自动检测」）")
            return
        if not Path(exe).is_file():
            QMessageBox.warning(self, "路径无效", f"文件不存在:\n{exe}")
            return

        account = self._account_input.text().strip()
        pwd_plain = self._pwd_input.text()
        saved_md5 = self._main.config.get("opend", "pwd_md5", default="")

        if not account:
            QMessageBox.warning(self, "缺少账号", "请填写牛牛号")
            return
        if not pwd_plain and not saved_md5:
            QMessageBox.warning(self, "缺少密码", "请填写登录密码")
            return

        self._launcher.set_exe_path(exe)
        port = self._port_spin.value()
        lang = self._lang_combo.currentData()
        show_console = self._console_check.isChecked()

        # 持久化配置
        from core.opend_launcher import md5_password
        pwd_md5 = md5_password(pwd_plain) if pwd_plain else saved_md5

        local_cfg = {"opend": {"exe_path": exe, "port": port}}
        if self._remember_check.isChecked():
            local_cfg["opend"]["account"] = account
            local_cfg["opend"]["pwd_md5"] = pwd_md5
        try:
            self._main.config.save_local(local_cfg)
        except Exception as e:
            self._terminal.append(f'配置保存失败: {e}')

        self._launch_btn.setEnabled(False)
        self._terminal.append("正在启动 OpenD...")

        host = self._main.config.get("opend", "host", default="127.0.0.1")
        launcher = self._launcher

        worker = WorkerThread(lambda: None)

        def do_launch():
            launcher.start(
                account=account,
                password=pwd_md5,
                password_is_md5=True,
                api_port=port,
                api_ip=host,
                lang=lang,
                show_console=show_console,
                on_output=lambda line: worker.progress.emit(line),
            )
            worker.progress.emit("等待 OpenD 就绪...")
            if not launcher.wait_until_ready(host, port, timeout=45.0):
                if launcher.needs_verify:
                    raise RuntimeError("__NEED_VERIFY__")
                raise RuntimeError(
                    "OpenD 启动后端口未就绪。请查看下方终端输出，"
                    "必要时在终端里直接输命令处理。")

            worker.progress.emit("OpenD 就绪，正在连接 API...")
            from core.client import FutuClient
            client = FutuClient(host=host, port=port)
            client.connect_quote()
            return client

        worker._func = do_launch
        self._worker = worker
        worker.progress.connect(self._on_log)
        worker.finished_ok.connect(self._on_connected)
        worker.error.connect(self._on_launch_error)
        worker.start()

    def _on_log(self, msg: str):
        self._terminal.append(msg)

    def _wait_for_login_then_connect(self):
        """等待终端里完成验证码登录，登录成功后自动连接 API"""
        host = self._main.config.get("opend", "host", default="127.0.0.1")
        port = self._port_spin.value()
        launcher = self._launcher

        if self._verify_timer is not None:
            self._verify_timer.stop()

        self._verify_timer = QTimer(self)
        self._verify_elapsed = 0

        def check():
            self._verify_elapsed += 1
            if not launcher.is_running():
                self._verify_timer.stop()
                self._terminal.append("[提示] OpenD 已退出")
                self._launch_btn.setEnabled(True)
                return
            if launcher.logged_in:
                self._verify_timer.stop()
                self._terminal.append("[提示] 检测到登录成功，正在连接 API...")
                self._on_connect()
                return
            if self._verify_elapsed > 300:  # 5 分钟
                self._verify_timer.stop()
                self._terminal.append("[提示] 等待登录超时，可手动点「仅连接」")
                self._launch_btn.setEnabled(True)

        self._verify_timer.timeout.connect(check)
        self._verify_timer.start(1000)

    def _on_launch_error(self, msg: str):
        # 需要手机验证码：不算失败，引导用户在终端里输入
        if "__NEED_VERIFY__" in msg:
            self._terminal.append("")
            self._terminal.append("需要手机验证码 —— 请在下方终端输入框执行：")
            self._terminal.append("    input_phone_verify_code -code=你收到的验证码")
            self._terminal.append("（验证通过后会自动连接 API）")
            self._terminal.focus_input()
            self._terminal._input.setText("input_phone_verify_code -code=")
            self._wait_for_login_then_connect()
            return

        self._terminal.append(f'❌ 启动失败: {msg}')
        self._main.log(f"OpenD 启动失败: {msg}")
        self._launch_btn.setEnabled(True)
        self._update_opend_status()

    def _on_stop_opend(self):
        if self._main.is_connected:
            self._on_disconnect()
        if self._launcher and self._launcher.stop():
            self._terminal.append("OpenD 已停止")
        self._update_opend_status()
        self._update_status_display()

    # ─── 仅连接 ───
    def _on_connect(self):
        self._terminal.append("正在连接 Futu OpenD...")
        self._connect_btn.setEnabled(False)

        host = self._main.config.get("opend", "host", default="127.0.0.1")
        port = self._port_spin.value()

        def do_connect():
            from core.client import FutuClient
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

        # 把 Futu 下载器挂到市场路由上（A股仍走 akshare）
        if self._main.router is not None:
            self._main.router.futu = self._main.kline_dl

        from core.quote_subscriber import QuoteSubscriber
        from trading.fee_calculator import FeeCalculator
        from trading.paper_engine import PaperEngine
        from strategy.indicators import IndicatorEngine
        from strategy.engine import StrategyEngine

        self._main.quote_sub = QuoteSubscriber(client)
        fee_calc = FeeCalculator(self._main.config)
        self._main.paper_engine = PaperEngine(self._main.db, fee_calc, self._main.config)
        indicator_eng = IndicatorEngine()
        self._main.strategy_engine = StrategyEngine(
            self._main.db, self._main.paper_engine, indicator_eng, self._main.config
        )

        self._main.set_connected(True)

        self._terminal.append(f'✅ 连接成功！')
        self._main.log("Futu OpenD 连接成功")
        self._update_status_display()
        self._update_opend_status()

    def _on_connect_error(self, msg):
        self._terminal.append(f'❌ 连接失败: {msg}')
        self._terminal.append(f''
            f'请确认 OpenD 已启动，或使用上方「启动 OpenD 并连接」')
        self._main.log(f"连接失败: {msg}")
        self._connect_btn.setEnabled(True)
        self._launch_btn.setEnabled(True)

    def _on_disconnect(self):
        if self._main.client:
            try:
                self._main.client.close()
            except Exception:
                pass
            self._main.client = None
        self._main.set_connected(False)
        self._terminal.append("已断开 API 连接")
        self._main.log("已断开 Futu OpenD 连接")
        self._update_status_display()
