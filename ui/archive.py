"""
archive.py – Archive Dialog

Lists every recorded video clip stored in the recordings/ folder.
Double-click or press Play to open a clip in the system video player.
"""

import datetime
import os
import subprocess

import cv2
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

# Folder where recordings are saved (project root / recordings)
RECORDINGS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recordings"
)

_VIDEO_EXTS = {".avi", ".mp4", ".mkv", ".mov"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_duration(path: str) -> str:
    try:
        cap    = cv2.VideoCapture(path)
        fps    = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        if fps > 0 and frames > 0:
            secs = int(frames / fps)
            return f"{secs // 60}:{secs % 60:02d}"
    except Exception:
        pass
    return "—"


# ── Stylesheet ─────────────────────────────────────────────────────────────────

_STYLE = """
QDialog {
    background: #1a1a1a;
}
QLabel {
    color: #cccccc;
}
QTableWidget {
    background: #121212;
    color: #cccccc;
    gridline-color: #2e2e2e;
    border: 1px solid #2e2e2e;
    selection-background-color: #3c64b4;
    selection-color: #ffffff;
    font-size: 13px;
}
QHeaderView::section {
    background: #252525;
    color: #aaaaaa;
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid #3e3e3e;
    font-size: 12px;
    font-weight: bold;
}
QTableWidget::item {
    padding: 4px 8px;
}
QPushButton {
    background: #2e2e2e;
    color: #cccccc;
    border: none;
    border-radius: 4px;
    padding: 6px 16px;
    font-size: 13px;
}
QPushButton:hover  { background: #3e3e3e; }
QPushButton#play   { background: #1a5c1a; color: #ffffff; }
QPushButton#play:hover   { background: #236b23; }
QPushButton#delete { background: #6b1a1a; color: #ffffff; }
QPushButton#delete:hover { background: #851e1e; }
QScrollBar:vertical { background: #1a1a1a; width: 8px; }
QScrollBar::handle:vertical { background: #3e3e3e; border-radius: 4px; }
"""


# ── Archive window ─────────────────────────────────────────────────────────────

class ArchiveWindow(QDialog):
    """Modal dialog listing all saved recordings."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DriveSafe – Archive")
        self.setMinimumSize(740, 480)
        self.setStyleSheet(_STYLE)
        self._build_ui()
        self._load()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        header = QLabel("Recorded Videos")
        header.setStyleSheet(
            "font-size: 17px; font-weight: bold; color: #ffffff; margin-bottom: 2px;"
        )
        root.addWidget(header)

        # Table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Filename", "Date", "Duration", "Size"])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setShowGrid(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(True)
        self._table.doubleClicked.connect(self._on_play)
        root.addWidget(self._table)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._play_btn = QPushButton("▶   Play")
        self._play_btn.setObjectName("play")
        self._play_btn.clicked.connect(self._on_play)
        btn_row.addWidget(self._play_btn)

        self._del_btn = QPushButton("🗑   Delete")
        self._del_btn.setObjectName("delete")
        self._del_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._del_btn)

        btn_row.addStretch()

        refresh_btn = QPushButton("↺   Refresh")
        refresh_btn.clicked.connect(self._load)
        btn_row.addWidget(refresh_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    # ── Data ─────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        if not os.path.isdir(RECORDINGS_DIR):
            self._show_empty("No recordings folder found.")
            return

        entries = []
        for name in os.listdir(RECORDINGS_DIR):
            if os.path.splitext(name)[1].lower() not in _VIDEO_EXTS:
                continue
            path = os.path.join(RECORDINGS_DIR, name)
            entries.append((name, path, os.stat(path)))

        if not entries:
            self._show_empty("No recordings yet.")
            return

        # Newest first
        entries.sort(key=lambda e: e[2].st_mtime, reverse=True)

        for name, path, stat in entries:
            row = self._table.rowCount()
            self._table.insertRow(row)

            dt = datetime.datetime.fromtimestamp(stat.st_mtime).strftime(
                "%Y-%m-%d  %H:%M:%S"
            )
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.UserRole, path)

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, QTableWidgetItem(dt))
            self._table.setItem(row, 2, QTableWidgetItem(_fmt_duration(path)))
            self._table.setItem(row, 3, QTableWidgetItem(_fmt_size(stat.st_size)))

        self._table.setSortingEnabled(True)

    def _show_empty(self, msg: str) -> None:
        self._table.insertRow(0)
        item = QTableWidgetItem(msg)
        item.setForeground(Qt.gray)
        self._table.setItem(0, 0, item)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _selected_path(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _on_play(self) -> None:
        path = self._selected_path()
        if not path or not os.path.isfile(path):
            return
        try:
            subprocess.Popen(["vlc", path])
        except Exception as exc:
            QMessageBox.warning(self, "Playback Error", str(exc))

    def _on_delete(self) -> None:
        path = self._selected_path()
        if not path or not os.path.isfile(path):
            return
        name = os.path.basename(path)
        reply = QMessageBox.question(
            self,
            "Delete Recording",
            f"Permanently delete  {name}?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                os.remove(path)
            except OSError as exc:
                QMessageBox.critical(self, "Error", str(exc))
            self._load()
