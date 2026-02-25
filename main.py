"""
main.py – DriveSafe Entry Point

Boots the PyQt5 application and shows the main window.

Keyboard shortcuts (active anywhere in the window):
    I      Toggle info overlay
    M      Mute / unmute voice alerts
    Q/ESC  Quit
"""

import sys

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

from core.config import load_config
from ui.app import MainWindow


def _apply_dark_palette(app: QApplication) -> None:
    """Apply a dark Fusion palette to every widget in the application."""
    p = QPalette()
    p.setColor(QPalette.Window,          QColor(26, 26, 26))
    p.setColor(QPalette.WindowText,      QColor(220, 220, 220))
    p.setColor(QPalette.Base,            QColor(18, 18, 18))
    p.setColor(QPalette.AlternateBase,   QColor(38, 38, 38))
    p.setColor(QPalette.ToolTipBase,     QColor(240, 240, 240))
    p.setColor(QPalette.ToolTipText,     QColor(30, 30, 30))
    p.setColor(QPalette.Text,            QColor(220, 220, 220))
    p.setColor(QPalette.Button,          QColor(48, 48, 48))
    p.setColor(QPalette.ButtonText,      QColor(220, 220, 220))
    p.setColor(QPalette.BrightText,      QColor(255, 80, 80))
    p.setColor(QPalette.Highlight,       QColor(60, 100, 180))
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(p)


def main() -> None:
    cfg = load_config()

    app = QApplication(sys.argv)
    app.setApplicationName("DriveSafe")
    app.setStyle("Fusion")
    _apply_dark_palette(app)

    window = MainWindow(cfg)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()