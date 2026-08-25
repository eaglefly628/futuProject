"""
OpenD 终端组件
把 OpenD 控制台的输出/输入接进 GUI，可直接输命令（验证码等）
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QLabel
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor

from gui.theme import COLORS

# 输出着色规则: (关键字, 颜色)
_COLOR_RULES = [
    ("登录成功", COLORS["green"]),
    ("必要数据准备完毕", COLORS["green"]),
    ("成功", COLORS["green"]),
    ("失败", COLORS["red"]),
    ("错误", COLORS["red"]),
    ("不匹配", COLORS["red"]),
    ("无权限", COLORS["yellow"]),
    ("需要手机验证码", COLORS["accent"]),
    ("req_phone_verify_code", COLORS["accent"]),
    ("请输入", COLORS["accent"]),
    ("请选择", COLORS["accent"]),
    (">>>", COLORS["blue"]),
]


class OpenDTerminal(QWidget):
    """OpenD 控制台终端"""

    command_sent = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._launcher = None
        self._history = []
        self._history_idx = -1
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 输出区
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setLineWrapMode(QTextEdit.NoWrap)
        self._output.setFont(QFont("Consolas, Menlo, monospace", 11))
        self._output.setStyleSheet(f"""
            QTextEdit {{
                background-color: #0A0E14;
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 8px;
                font-family: Consolas, Menlo, "Courier New", monospace;
                font-size: 12px;
            }}
        """)
        layout.addWidget(self._output, 1)

        # 输入区
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        prompt = QLabel(">>>")
        prompt.setStyleSheet(
            f"color:{COLORS['accent']}; font-family:Consolas,Menlo,monospace; "
            f"font-size:13px; font-weight:bold;")
        input_row.addWidget(prompt)

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "输入 OpenD 命令后回车，如 input_phone_verify_code -code=123456")
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background-color: #0A0E14;
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px 10px;
                font-family: Consolas, Menlo, monospace;
                font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {COLORS['accent']}; }}
        """)
        self._input.returnPressed.connect(self._on_send)
        self._input.installEventFilter(self)
        input_row.addWidget(self._input, 1)

        send_btn = QPushButton("发送")
        send_btn.setCursor(Qt.PointingHandCursor)
        send_btn.clicked.connect(self._on_send)
        input_row.addWidget(send_btn)

        layout.addLayout(input_row)

        # 快捷命令
        quick_row = QHBoxLayout()
        quick_row.setSpacing(6)
        quick_row.addWidget(QLabel("快捷:"))
        for label, cmd in [
            ("重发验证码", "req_phone_verify_code"),
            ("命令列表", "help"),
            ("查询权限", "show_quote_right"),
        ]:
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.setMaximumHeight(26)
            b.clicked.connect(lambda _=False, c=cmd: self.send_command(c))
            quick_row.addWidget(b)

        clear_btn = QPushButton("清屏")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setMaximumHeight(26)
        clear_btn.clicked.connect(self._output.clear)
        quick_row.addWidget(clear_btn)

        quick_row.addStretch()
        layout.addLayout(quick_row)

    # ─── 上下键翻历史 ───
    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self._input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Up:
                if self._history:
                    self._history_idx = max(0, self._history_idx - 1)
                    self._input.setText(self._history[self._history_idx])
                return True
            if event.key() == Qt.Key_Down:
                if self._history:
                    self._history_idx = min(len(self._history), self._history_idx + 1)
                    if self._history_idx >= len(self._history):
                        self._input.clear()
                    else:
                        self._input.setText(self._history[self._history_idx])
                return True
        return super().eventFilter(obj, event)

    # ─── 对外接口 ───
    def attach(self, launcher):
        """绑定 OpenDLauncher"""
        self._launcher = launcher

    def append(self, line: str):
        """追加一行输出（带着色）"""
        color = COLORS["text_secondary"]
        for keyword, c in _COLOR_RULES:
            if keyword in line:
                color = c
                break

        safe = (line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))
        self._output.append(f'<span style="color:{color}">{safe}</span>')
        self._output.moveCursor(QTextCursor.End)

    def load_history(self, lines):
        """载入已有输出"""
        for line in lines:
            self.append(line)

    def send_command(self, cmd: str):
        cmd = cmd.strip()
        if not cmd:
            return
        if self._launcher is None or not self._launcher.is_running():
            self.append("[错误] OpenD 未运行，无法发送命令")
            return
        self._launcher.send_command(cmd)
        if cmd not in self._history:
            self._history.append(cmd)
        self._history_idx = len(self._history)
        self.command_sent.emit(cmd)

    def _on_send(self):
        cmd = self._input.text()
        if cmd.strip():
            self.send_command(cmd)
            self._input.clear()

    def focus_input(self):
        self._input.setFocus()
