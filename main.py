"""
main.py – DriveSafe Entry Point

Boots the PyQt5 application and shows the main window.

Keyboard shortcuts (active anywhere in the window):
    I      Toggle info overlay
    M      Mute / unmute voice alerts
    Q/ESC  Quit
"""

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette, QPixmap, QPainter, QFont, QPen
from PyQt5.QtWidgets import QApplication, QSplashScreen

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

# SPlash screen

def _make_splash(w: int = 520, h: int = 300) -> QPixmap:
    pix = QPixmap(w, h)
    pix.fill(QColor("#111111"))

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    p.fillRect(0, 0, w, 6, QColor("#3c64b4"))

    title_font = QFont("Sans Serif", 42, QFont.Bold)
    p.setFont(title_font)
    p.setPen(QColor("#ffffff"))
    p.drawText(0, 60, w, 70, Qt.AlignHCenter | Qt.AlignVCenter, "DriveSafe")

    sub_font = QFont("Sans Serif", 13)
    p.setFont(sub_font)
    p.setPen(QColor("#888888"))
    p.drawText(0, 130, w, 40, Qt.AlignHCenter | Qt.AlignVCenter,
               "Pedestrian Safety Assistant")

    p.end()
    return pix



def main() -> None:
    cfg = load_config()

    app = QApplication(sys.argv)
    app.setApplicationName("DriveSafe")
    app.setStyle("Fusion")
    _apply_dark_palette(app)

    splash = QSplashScreen(_make_splash(), Qt.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    window = MainWindow(cfg)
    window._thread.ready.connect(lambda: splash.finish(window))
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()