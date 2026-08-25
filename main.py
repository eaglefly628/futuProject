#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║         富途量化数据平台 (FutuQuant Data Platform)            ║
║                v2.0 GUI · 个人投资辅助工具                    ║
╚══════════════════════════════════════════════════════════════╝
"""
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
os.chdir(PROJECT_ROOT)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from gui.theme import FUTU_STYLESHEET
from gui.main_window import MainWindow


def main():
    # macOS 高分辨率支持
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # 全局字体
    font = QFont("PingFang SC", 13)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)

    # 应用深色主题
    app.setStyleSheet(FUTU_STYLESHEET)

    # 创建主窗口
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
