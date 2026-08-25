"""
主窗口 - 富途风格侧栏导航
"""
import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QStatusBar,
    QFrame, QSpacerItem, QSizePolicy, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon

PROJECT_ROOT = Path(__file__).parent.parent

# 侧栏菜单项配置
MENU_ITEMS = [
    ("📊", "数据总览", "dashboard"),
    ("🎯", "A500中心", "a500"),
    ("📡", "实时行情", "realtime"),
    ("💰", "模拟交易", "paper"),
    ("🧪", "策略编辑", "strategy"),
    None,  # 分割线
    ("📈", "K线下载", "kline"),
    ("⚡", "批量下载", "batch"),
    ("🔄", "逐笔采集", "tick"),
    ("📋", "监控列表", "watchlist"),
    ("💾", "数据导出", "export"),
    ("🔬", "质量检查", "quality"),
    None,  # 分割线
    ("⚙️", "系统设置", "settings"),
    ("🔗", "连接管理", "connection"),
]


class MainWindow(QMainWindow):
    """主窗口"""

    connection_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FutuQuant · 富途量化数据平台")
        self.setMinimumSize(1200, 750)
        self.resize(1400, 850)

        # 后端引用
        self.config = None
        self.db = None
        self.client = None
        self.kline_dl = None
        self.tick_cl = None
        self.analyzer = None
        self.quote_sub = None
        self.paper_engine = None
        self.strategy_engine = None
        self._connected = False

        self._init_backend()
        self._build_ui()
        self._update_status()

    def _init_backend(self):
        """初始化后端"""
        from config import Config
        config_path = str(PROJECT_ROOT / "config" / "default.yaml")
        self.config = Config(config_path)

        from storage.database import Database
        db_path = self.config.get("storage", "sqlite_path")
        self.db = Database(db_path)

        from analysis.basic_stats import BasicAnalyzer
        self.analyzer = BasicAnalyzer(self.db)

    def _build_ui(self):
        """构建界面"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ─── 左侧栏 ───
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Logo
        logo = QLabel("  FutuQuant")
        logo.setObjectName("sidebarLogo")
        logo.setFixedHeight(64)
        logo.setAlignment(Qt.AlignVCenter)
        sidebar_layout.addWidget(logo)

        # 菜单按钮
        self._menu_buttons = {}
        self._panels = {}
        self._stack = QStackedWidget()
        self._stack.setObjectName("contentArea")

        for item in MENU_ITEMS:
            if item is None:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setFixedHeight(1)
                line.setStyleSheet(f"background-color: #2A3545; margin: 8px 16px;")
                sidebar_layout.addWidget(line)
                continue

            icon, label, key = item
            btn = QPushButton(f"  {icon}   {label}")
            btn.setCheckable(True)
            btn.setFixedHeight(44)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, k=key: self._switch_panel(k))
            sidebar_layout.addWidget(btn)
            self._menu_buttons[key] = btn

        sidebar_layout.addStretch()

        # 版本信息
        ver = QLabel("  v2.0 GUI")
        ver.setStyleSheet(f"color: #484F58; font-size: 11px; padding: 12px;")
        sidebar_layout.addWidget(ver)

        main_layout.addWidget(sidebar)

        # ─── 右侧内容区 ───
        self._build_panels()
        main_layout.addWidget(self._stack)

        # ─── 状态栏 ───
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self._status_conn_label = QLabel("⬤ 未连接")
        self._status_conn_label.setObjectName("statusDisconnected")
        self._status_db_label = QLabel()
        status_bar.addWidget(self._status_conn_label)
        status_bar.addPermanentWidget(self._status_db_label)

        # 默认显示数据总览
        self._switch_panel("dashboard")

    def _build_panels(self):
        """创建所有面板"""
        from gui.panels.dashboard import DashboardPanel
        from gui.panels.kline_download import KlineDownloadPanel
        from gui.panels.batch_download import BatchDownloadPanel
        from gui.panels.tick_collect import TickCollectPanel
        from gui.panels.watchlist import WatchlistPanel
        from gui.panels.export import ExportPanel
        from gui.panels.quality_check import QualityCheckPanel
        from gui.panels.settings import SettingsPanel
        from gui.panels.connection import ConnectionPanel
        from gui.panels.realtime_monitor import RealtimeMonitorPanel
        from gui.panels.paper_trading import PaperTradingPanel
        from gui.panels.strategy_editor import StrategyEditorPanel
        from gui.panels.a500_center import A500CenterPanel

        panel_map = {
            "dashboard": DashboardPanel(self),
            "a500": A500CenterPanel(self),
            "realtime": RealtimeMonitorPanel(self),
            "paper": PaperTradingPanel(self),
            "strategy": StrategyEditorPanel(self),
            "kline": KlineDownloadPanel(self),
            "batch": BatchDownloadPanel(self),
            "tick": TickCollectPanel(self),
            "watchlist": WatchlistPanel(self),
            "export": ExportPanel(self),
            "quality": QualityCheckPanel(self),
            "settings": SettingsPanel(self),
            "connection": ConnectionPanel(self),
        }

        for key, panel in panel_map.items():
            self._panels[key] = panel
            self._stack.addWidget(panel)

    def _switch_panel(self, key: str):
        """切换面板"""
        if key in self._panels:
            self._stack.setCurrentWidget(self._panels[key])
            # 刷新面板
            panel = self._panels[key]
            if hasattr(panel, "on_show"):
                panel.on_show()
        # 更新按钮状态
        for k, btn in self._menu_buttons.items():
            btn.setChecked(k == key)

    def _update_status(self):
        """更新状态栏"""
        try:
            stats = self.db.get_stats()
            self._status_db_label.setText(
                f"📊 K线: {stats['kline_total']:,}  |  "
                f"📈 股票: {stats['kline_stocks']}  |  "
                f"⚡ 逐笔: {stats['tick_total']:,}  |  "
                f"💾 {stats['db_size_mb']} MB"
            )
        except Exception:
            self._status_db_label.setText("数据库加载中...")

    def set_connected(self, connected: bool):
        """更新连接状态"""
        self._connected = connected
        if connected:
            self._status_conn_label.setText("⬤ 已连接")
            self._status_conn_label.setObjectName("statusConnected")
        else:
            self._status_conn_label.setText("⬤ 未连接")
            self._status_conn_label.setObjectName("statusDisconnected")
        self._status_conn_label.style().unpolish(self._status_conn_label)
        self._status_conn_label.style().polish(self._status_conn_label)
        self.connection_changed.emit(connected)

    def refresh_status(self):
        self._update_status()

    def log(self, msg: str):
        """向日志面板追加消息"""
        if "dashboard" in self._panels:
            self._panels["dashboard"].append_log(msg)

    @property
    def is_connected(self):
        return self._connected

    def closeEvent(self, event):
        if self.quote_sub:
            try:
                self.quote_sub.close()
            except Exception:
                pass
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        if self.db:
            try:
                self.db.close()
            except Exception:
                pass
        event.accept()
