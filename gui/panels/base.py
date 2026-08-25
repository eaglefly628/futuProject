"""
面板基类 - 统一布局和样式辅助
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QPushButton, QGroupBox, QGridLayout
)
from PySide6.QtCore import Qt


class BasePanel(QWidget):
    """面板基类"""

    def __init__(self, main_window, title="", subtitle=""):
        super().__init__()
        self._main = main_window
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        if title:
            t = QLabel(title)
            t.setObjectName("panelTitle")
            self._layout.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("panelSubtitle")
            self._layout.addWidget(s)

        # 内容区(带padding和滚动)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(24, 8, 24, 24)
        self._content_layout.setSpacing(16)
        self._layout.addWidget(self._content, 1)

    def add_widget(self, w):
        self._content_layout.addWidget(w)

    def add_layout(self, l):
        self._content_layout.addLayout(l)

    def add_stretch(self):
        self._content_layout.addStretch()

    def make_card(self, title=None) -> tuple:
        """创建卡片, 返回 (card_widget, card_layout)"""
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setSpacing(12)
        if title:
            t = QLabel(title)
            t.setObjectName("cardTitle")
            layout.addWidget(t)
        return card, layout

    def make_stat_card(self, label, value, color=None):
        """创建统计卡片"""
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setSpacing(4)
        v = QLabel(str(value))
        v.setObjectName("statValue")
        if color:
            v.setStyleSheet(f"color: {color}; font-size: 28px; font-weight: bold;")
        layout.addWidget(v)
        l = QLabel(label)
        l.setObjectName("statLabel")
        layout.addWidget(l)
        return card

    def make_primary_btn(self, text, callback=None):
        btn = QPushButton(text)
        btn.setObjectName("primaryBtn")
        btn.setCursor(Qt.PointingHandCursor)
        if callback:
            btn.clicked.connect(callback)
        return btn

    def make_danger_btn(self, text, callback=None):
        btn = QPushButton(text)
        btn.setObjectName("dangerBtn")
        btn.setCursor(Qt.PointingHandCursor)
        if callback:
            btn.clicked.connect(callback)
        return btn

    def on_show(self):
        """面板被切换到前台时调用"""
        pass
