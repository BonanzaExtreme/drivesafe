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

_FILTERS = [
    ("All",             None,             "#2e2e2e"),
    ("Recordings",      "Recording",      "#1a5c1a"),
    ("Clips (Warning)", "Clip (Warning)", "#7a5800"),
    ("Clips (Danger)",  "Clip (Danger)",  "#6b1a1a"),
]
_STYLE = """
QDialog {
    background: #1a1a1a;
}
QLabel {
    color: #cccccc;
}
QPushButton#filter_btn {
    padding: 5px 14px;
    border-radius: 3px;
    font-size: 12px;
    font-weight: bold;
    border: 1px solid #444;
}
QPushButton#filter_btn:checked {
    border: 1px solid #aaa;
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
    """Modal dialog listing all saved recordings and clips, filterable by category."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DriveSafe – Archive")
        self.setMinimumSize(800, 520)
        self.setStyleSheet(_STYLE)
        self._active_filter: str | None = None   # None = show all
        self._filter_btns: list = []
        self._build_ui()
        self._load()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        title_row = QHBoxLayout()
        header = QLabel("Archive")
        header.setStyleSheet(
            "font-size: 17px; font-weight: bold; color: #ffffff;"
        )
        title_row.addWidget(header)
        root.addLayout(title_row)

        for label, filter_val, bg_color in _FILTERS:
            btn = QPushButton(label)
            btn.setObjectName("filter_btn")
            btn.setCheckable(True)
            btn.setChecked(filter_val is None)   # "All" starts checked
            btn.setStyleSheet(
                f"QPushButton#filter_btn {{ background: {bg_color}; color: #dddddd; }}"
                f"QPushButton#filter_btn:checked {{ background: {bg_color}; color: #ffffff; border: 1.5px solid #ffffff; }}"
            )
            # Capture filter_val in closure
            btn.clicked.connect(lambda checked, fv=filter_val, b=btn: self._on_filter(fv, b))
            title_row.addWidget(btn)
            self._filter_btns.append((btn, filter_val))

        root.addLayout(title_row)

        # Table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Filename", "Type", "Date", "Duration", "Size"])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
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
    
    # ── Filter ────────────────────────────────────────────────────────────────

    def _on_filter(self, filter_val: str | None, clicked_btn) -> None:
        """Switch active category filter and reload the table."""
        self._active_filter = filter_val
        # Update checked state of all filter buttons
        for btn, fv in self._filter_btns:
            btn.blockSignals(True)
            btn.setChecked(fv == filter_val)
            btn.blockSignals(False)
        self._load()

    # ── Data ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _classify(name: str) -> str:
        """Return the display type string for a filename."""
        if name.startswith("clip_danger"):
            return "Clip (Danger)"
        if name.startswith("clip_warning"):
            return "Clip (Warning)"
        if name.startswith("clip_"):
            return "Clip"
        return "Recording"

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
            vid_type = self._classify(name)
            # Apply category filter
            if self._active_filter is not None and vid_type != self._active_filter:
                continue
            path = os.path.join(RECORDINGS_DIR, name)
            entries.append((name, path, os.stat(path), vid_type))

        if not entries:
            label = f"No {self._active_filter or 'recordings'} found."
            self._show_empty(label)
            return

        # Newest first
        entries.sort(key=lambda e: e[2].st_mtime, reverse=True)
        _ROW_COLOR = {
            "Recording":      "#1a2a1a",
            "Clip (Warning)": "#2a2000",
            "Clip (Danger)":  "#2a0a0a",
            "Clip":           "#1e1e2a",
        }

        for name, path, stat, vid_type in entries:
            row = self._table.rowCount()
            self._table.insertRow(row)

            dt = datetime.datetime.fromtimestamp(stat.st_mtime).strftime(
                "%Y-%m-%d  %H:%M:%S"
            )
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.UserRole, path)

            items = [
                name_item,
                QTableWidgetItem(vid_type),
                QTableWidgetItem(dt),
                QTableWidgetItem(_fmt_duration(path)),
                QTableWidgetItem(_fmt_size(stat.st_size)),
            ]
            row_bg = _ROW_COLOR.get(vid_type, "#1a1a1a")
            from PyQt5.QtGui import QColor
            for col, item in enumerate(items):
                item.setBackground(QColor(row_bg))
                self._table.setItem(row, col, item)
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
