"""
富途风格深色主题
配色参考富途牛牛桌面端：深蓝黑底、橙色强调、红涨绿跌
"""

# 核心色板
COLORS = {
    "bg_dark": "#0D1117",       # 最深背景
    "bg_main": "#141B24",       # 主背景
    "bg_card": "#1B2432",       # 卡片背景
    "bg_sidebar": "#0F1620",    # 侧栏背景
    "bg_hover": "#1F2B3D",      # 悬停
    "bg_selected": "#1A3A5C",   # 选中
    "bg_input": "#0D1117",      # 输入框
    "border": "#2A3545",        # 边框
    "border_light": "#3A4A5C",  # 浅边框

    "text_primary": "#E6EDF3",  # 主文字
    "text_secondary": "#8B949E",# 次要文字
    "text_muted": "#484F58",    # 弱文字

    "accent": "#F0883E",        # 强调色(富途橙)
    "accent_hover": "#D97A35",  # 强调悬停
    "accent_light": "#2A1F14",  # 强调浅底

    "red": "#E5534B",           # 跌(中国市场用绿跌,这里用国际惯例)
    "green": "#3FB950",         # 涨
    "red_bg": "#2D1B1B",       # 红色背景
    "green_bg": "#1B2D1B",     # 绿色背景

    "blue": "#58A6FF",          # 信息蓝
    "yellow": "#D29922",        # 警告黄
    "purple": "#A371F7",        # 紫色
}

FUTU_STYLESHEET = f"""
/* ═══════ 全局 ═══════ */
QMainWindow, QDialog {{
    background-color: {COLORS['bg_main']};
    color: {COLORS['text_primary']};
}}
QWidget {{
    color: {COLORS['text_primary']};
    font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}}

/* ═══════ 侧栏 ═══════ */
#sidebar {{
    background-color: {COLORS['bg_sidebar']};
    border-right: 1px solid {COLORS['border']};
    min-width: 200px;
    max-width: 200px;
}}
#sidebar QPushButton {{
    text-align: left;
    padding: 12px 20px;
    border: none;
    border-radius: 0;
    background: transparent;
    color: {COLORS['text_secondary']};
    font-size: 13px;
}}
#sidebar QPushButton:hover {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['text_primary']};
}}
#sidebar QPushButton:checked,
#sidebar QPushButton[active="true"] {{
    background-color: {COLORS['bg_selected']};
    color: {COLORS['accent']};
    border-left: 3px solid {COLORS['accent']};
    font-weight: bold;
}}
#sidebarLogo {{
    padding: 20px;
    font-size: 18px;
    font-weight: bold;
    color: {COLORS['accent']};
    border-bottom: 1px solid {COLORS['border']};
}}

/* ═══════ 内容区 ═══════ */
#contentArea {{
    background-color: {COLORS['bg_main']};
}}
#panelTitle {{
    font-size: 20px;
    font-weight: bold;
    color: {COLORS['text_primary']};
    padding: 16px 24px 8px 24px;
}}
#panelSubtitle {{
    font-size: 12px;
    color: {COLORS['text_secondary']};
    padding: 0 24px 16px 24px;
}}

/* ═══════ 卡片 ═══════ */
#card {{
    background-color: {COLORS['bg_card']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
}}
#cardTitle {{
    font-size: 14px;
    font-weight: bold;
    color: {COLORS['text_primary']};
    margin-bottom: 8px;
}}
#statValue {{
    font-size: 28px;
    font-weight: bold;
    color: {COLORS['accent']};
}}
#statLabel {{
    font-size: 12px;
    color: {COLORS['text_secondary']};
}}

/* ═══════ 按钮 ═══════ */
QPushButton {{
    padding: 8px 20px;
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    background-color: {COLORS['bg_card']};
    color: {COLORS['text_primary']};
    font-size: 13px;
    min-height: 20px;
}}
QPushButton:hover {{
    background-color: {COLORS['bg_hover']};
    border-color: {COLORS['border_light']};
}}
QPushButton:pressed {{
    background-color: {COLORS['bg_selected']};
}}
QPushButton:disabled {{
    color: {COLORS['text_muted']};
    background-color: {COLORS['bg_dark']};
}}
#primaryBtn {{
    background-color: {COLORS['accent']};
    border: none;
    color: #FFFFFF;
    font-weight: bold;
}}
#primaryBtn:hover {{
    background-color: {COLORS['accent_hover']};
}}
#primaryBtn:disabled {{
    background-color: {COLORS['text_muted']};
}}
#dangerBtn {{
    background-color: {COLORS['red']};
    border: none;
    color: #FFFFFF;
}}
#successBtn {{
    background-color: {COLORS['green']};
    border: none;
    color: #FFFFFF;
}}

/* ═══════ 输入框 ═══════ */
QLineEdit, QSpinBox, QDoubleSpinBox {{
    padding: 8px 12px;
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    background-color: {COLORS['bg_input']};
    color: {COLORS['text_primary']};
    selection-background-color: {COLORS['accent']};
    min-height: 20px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {COLORS['accent']};
}}
QLineEdit:disabled {{
    background-color: {COLORS['bg_dark']};
    color: {COLORS['text_muted']};
}}

/* ═══════ 下拉框 ═══════ */
QComboBox {{
    padding: 8px 12px;
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    background-color: {COLORS['bg_input']};
    color: {COLORS['text_primary']};
    min-height: 20px;
}}
QComboBox:hover {{ border-color: {COLORS['border_light']}; }}
QComboBox:focus {{ border-color: {COLORS['accent']}; }}
QComboBox::drop-down {{
    border: none;
    width: 30px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {COLORS['text_secondary']};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_card']};
    border: 1px solid {COLORS['border']};
    selection-background-color: {COLORS['bg_selected']};
    color: {COLORS['text_primary']};
    outline: none;
}}

/* ═══════ 复选框 ═══════ */
QCheckBox {{
    spacing: 8px;
    color: {COLORS['text_primary']};
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    background-color: {COLORS['bg_input']};
}}
QCheckBox::indicator:checked {{
    background-color: {COLORS['accent']};
    border-color: {COLORS['accent']};
}}

/* ═══════ 表格 ═══════ */
QTableWidget, QTableView {{
    background-color: {COLORS['bg_card']};
    alternate-background-color: {COLORS['bg_dark']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    gridline-color: {COLORS['border']};
    selection-background-color: {COLORS['bg_selected']};
    color: {COLORS['text_primary']};
    outline: none;
}}
QTableWidget::item, QTableView::item {{
    padding: 6px 10px;
    border-bottom: 1px solid {COLORS['border']};
}}
QTableWidget::item:selected {{
    background-color: {COLORS['bg_selected']};
}}
QHeaderView::section {{
    background-color: {COLORS['bg_sidebar']};
    color: {COLORS['text_secondary']};
    border: none;
    border-bottom: 2px solid {COLORS['border']};
    border-right: 1px solid {COLORS['border']};
    padding: 8px 10px;
    font-weight: bold;
    font-size: 12px;
}}

/* ═══════ 滚动条 ═══════ */
QScrollBar:vertical {{
    background: {COLORS['bg_dark']};
    width: 8px;
    margin: 0;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['border']};
    min-height: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {COLORS['border_light']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {COLORS['bg_dark']};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {COLORS['border']};
    min-width: 30px;
    border-radius: 4px;
}}

/* ═══════ 进度条 ═══════ */
QProgressBar {{
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    background-color: {COLORS['bg_dark']};
    text-align: center;
    color: {COLORS['text_primary']};
    min-height: 20px;
}}
QProgressBar::chunk {{
    background-color: {COLORS['accent']};
    border-radius: 5px;
}}

/* ═══════ 标签页 ═══════ */
QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    background-color: {COLORS['bg_card']};
    border-radius: 6px;
}}
QTabBar::tab {{
    background-color: {COLORS['bg_dark']};
    color: {COLORS['text_secondary']};
    padding: 8px 20px;
    border: 1px solid {COLORS['border']};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {COLORS['bg_card']};
    color: {COLORS['accent']};
    font-weight: bold;
}}
QTabBar::tab:hover:!selected {{
    background-color: {COLORS['bg_hover']};
}}

/* ═══════ 文本区域 ═══════ */
QTextEdit, QPlainTextEdit {{
    background-color: {COLORS['bg_input']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    color: {COLORS['text_primary']};
    padding: 8px;
    font-family: "SF Mono", "Menlo", "Consolas", monospace;
    font-size: 12px;
}}

/* ═══════ 分割线 ═══════ */
QFrame[frameShape="4"] {{
    color: {COLORS['border']};
    max-height: 1px;
}}
QFrame[frameShape="5"] {{
    color: {COLORS['border']};
    max-width: 1px;
}}

/* ═══════ 分组框 ═══════ */
QGroupBox {{
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: bold;
    color: {COLORS['text_secondary']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 6px;
}}

/* ═══════ 提示框 ═══════ */
QToolTip {{
    background-color: {COLORS['bg_card']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    padding: 4px 8px;
}}

/* ═══════ 状态栏 ═══════ */
QStatusBar {{
    background-color: {COLORS['bg_sidebar']};
    color: {COLORS['text_secondary']};
    border-top: 1px solid {COLORS['border']};
    font-size: 12px;
}}
QStatusBar::item {{
    border: none;
}}
#statusConnected {{
    color: {COLORS['green']};
    font-weight: bold;
}}
#statusDisconnected {{
    color: {COLORS['red']};
    font-weight: bold;
}}

/* ═══════ 日志面板 ═══════ */
#logPanel {{
    background-color: {COLORS['bg_dark']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    font-family: "SF Mono", "Menlo", "Consolas", monospace;
    font-size: 11px;
}}

/* ═══════ 面板滚动区 ═══════ */
QScrollArea {{
    background-color: transparent;
    border: none;
}}
#panelContent {{
    background-color: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['border_light']};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {COLORS['text_muted']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {COLORS['border_light']};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

"""
