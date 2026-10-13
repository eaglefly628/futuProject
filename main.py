#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║         富途量化数据平台 (FutuQuant Data Platform)            ║
║                v2.0 GUI · 个人投资辅助工具                    ║
╚══════════════════════════════════════════════════════════════╝
"""
import sys
import os
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
os.chdir(PROJECT_ROOT)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from gui.theme import FUTU_STYLESHEET
from gui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser(description="FutuQuant 桌面量化平台")
    parser.add_argument("--market", action="store_true", help="直接打开全市场对照")
    args, qt_args = parser.parse_known_args()
    # macOS 高分辨率支持
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication([sys.argv[0], *qt_args])

    # 全局字体
    font = QFont("Microsoft YaHei UI", 11) if os.name == "nt" else QFont("PingFang SC", 13)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)

    # 应用深色主题
    app.setStyleSheet(FUTU_STYLESHEET)

    # 创建主窗口
    window = MainWindow()
    if args.market:
        window._switch_panel("a500")
        window._panels["a500"]._tabs.setCurrentIndex(3)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
