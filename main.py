"""
main.py – DriveSafe Entry Point

Boots the PyQt5 application and shows the main window.

Keyboard shortcuts (active anywhere in the window):
    I      Toggle info overlay
    M      Mute / unmute voice alerts
    Q/ESC  Quit
"""

import sys

from PyQt5.QtCore import Qt, QThread
from PyQt5.QtGui import QColor, QPalette, QPixmap, QPainter, QFont, QPen, QLinearGradient, QPainterPath
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

def _make_splash(w: int = 900, h: int = 560) -> QPixmap:
    pix = QPixmap(w, h)
    pix.fill(QColor("#0a0a0a"))

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

     # Background gradient
    gradient = QLinearGradient(0, 0, 0, h)
    gradient.setColorAt(0, QColor("#1a1a2e"))
    gradient.setColorAt(0.5, QColor("#16213e"))
    gradient.setColorAt(1, QColor("#0f0f23"))
    p.fillRect(0, 0, w, h, gradient)

    # Top accent bar with gradient
    accent_gradient = QLinearGradient(0, 0, w, 0)
    accent_gradient.setColorAt(0, QColor("#ff6b6b"))
    accent_gradient.setColorAt(0.5, QColor("#4ecdc4"))
    accent_gradient.setColorAt(1, QColor("#45b7d1"))
    p.fillRect(0, 0, w, 8, accent_gradient)

    # Configuration
    y_offset = 30  # Increase this value to move the car further down
    center_x = w // 2
    center_y = h // 2 + y_offset

    # 1. Car body
    p.setPen(QPen(QColor("#4ecdc4"), 3))
    p.setBrush(QColor("#4ecdc4").lighter(120))

    car_path = QPainterPath()
    car_path.moveTo(center_x - 80, center_y - 40)
    car_path.lineTo(center_x - 50, center_y - 60) # Roof start
    car_path.lineTo(center_x + 50, center_y - 60) # Roof end
    car_path.lineTo(center_x + 80, center_y - 30)
    car_path.lineTo(center_x + 65, center_y + 15)
    car_path.lineTo(center_x - 65, center_y + 15)
    car_path.closeSubpath()
    p.drawPath(car_path)

    # 2. Add Windows
    p.setBrush(QColor("#ffffff")) # White or light blue for glass
    window_path = QPainterPath()
    # Inset slightly from the roof lines
    window_path.moveTo(center_x - 45, center_y - 55)
    window_path.lineTo(center_x + 45, center_y - 55)
    window_path.lineTo(center_x + 65, center_y - 35)
    window_path.lineTo(center_x - 45, center_y - 35)
    window_path.closeSubpath()
    p.drawPath(window_path)

    # 3. Wheels
    p.setBrush(QColor("#2c3e50"))
    p.drawEllipse(center_x - 60, center_y + 8, 22, 22)
    p.drawEllipse(center_x + 38, center_y + 8, 22, 22)

    # Title - larger font for bigger screen
    title_font = QFont("Arial", 64, QFont.Bold)
    p.setFont(title_font)
    p.setPen(QColor("#ffffff"))
    
     # Add text shadow
    p.setPen(QColor("#000000"))
    p.drawText(3, 83, w, 90, Qt.AlignHCenter | Qt.AlignVCenter, "DriveSafe")
    p.setPen(QColor("#ffffff"))
    p.drawText(0, 80, w, 90, Qt.AlignHCenter | Qt.AlignVCenter, "DriveSafe")

    # Subtitle - larger font
    sub_font = QFont("Arial", 20)
    p.setFont(sub_font)
    p.setPen(QColor("#b8c5d6"))
    p.drawText(0, 180, w, 40, Qt.AlignHCenter | Qt.AlignVCenter,
               "Pedestrian Safety Assistant") 

    # Version info - larger font
    version_font = QFont("Arial", 14)
    p.setFont(version_font)
    p.setPen(QColor("#888888"))
    p.drawText(0, h - 80, w, 30, Qt.AlignHCenter | Qt.AlignVCenter,
               "YOLO Real-time Detection  • Distance Estimation • Alerts")

    # Loading text - larger font
    loading_font = QFont("Arial", 16, QFont.Bold)
    p.setFont(loading_font)
    p.setPen(QColor("#4ecdc4"))
    
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

    # Show loading messages
    loading_messages = [
        "Loading configuration...",
        "Initializing AI model...",
        "Setting up camera...",
        "Starting DriveSafe..."
    ]

    for i, message in enumerate(loading_messages):
        splash.showMessage(message + "\n", Qt.AlignBottom | Qt.AlignHCenter, QColor("#4ecdc4"))
        app.processEvents()
        QThread.msleep(900)  # Longer delay for visibility

    # Brief pause before showing main window
    QThread.msleep(500)

    window = MainWindow(cfg)
    window._thread.ready.connect(lambda: splash.finish(window))
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()