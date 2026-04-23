"""
settings.py – Settings Dialog for DriveSafe

Allows users to configure:
- Voice selection (from available voice models)
- Path zone adjustment (slider)
- Other runtime settings
"""

import os
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QComboBox,
    QPushButton,
    QGroupBox,
    QSpinBox,
    QDoubleSpinBox,
    QGridLayout,
    QRadioButton,
    QButtonGroup,
)

from ..core.paths import resource_path


VOICE_CHOICES = [
    ("Male", "en_US-hfc_male-medium (1).onnx"),
    ("Female", "en_US-hfc_female-medium.onnx"),
]


class SettingsWindow(QDialog):
    """Settings dialog for runtime configuration."""

    # Signals to notify main window of changes
    settings_changed = pyqtSignal(dict)  # {"path_zone": 0.65, "voice_model": "...", "alert_mode": "both"}

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg.copy()  # Work with a copy
        self.setWindowTitle("DriveSafe Settings")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: #cccccc;
            }
            QGroupBox {
                color: #cccccc;
                border: 1px solid #3e3e3e;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
            }
            QLabel {
                color: #cccccc;
            }
            QComboBox, QSpinBox, QDoubleSpinBox, QSlider {
                background-color: #252525;
                color: #cccccc;
                border: 1px solid #3e3e3e;
                border-radius: 4px;
                padding: 4px;
            }
            QPushButton {
                background-color: #2a4a7a;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3c64b4;
            }
            QPushButton:pressed {
                background-color: #1c3a6a;
            }
        """)

        layout = QVBoxLayout()

        # ── Voice Selection ───────────────────────────────────────────────
        voice_group = QGroupBox("Voice Settings")
        voice_layout = QGridLayout()

        voice_label = QLabel("Alert Voice:")
        voice_label.setFont(QFont("Arial", 10, QFont.Bold))
        self._voice_combo = QComboBox()
        self._populate_voices()
        voice_layout.addWidget(voice_label, 0, 0)
        voice_layout.addWidget(self._voice_combo, 0, 1)

        voice_group.setLayout(voice_layout)
        layout.addWidget(voice_group)

        # ── Alert Output ─────────────────────────────────────────────────
        alert_group = QGroupBox("Alert Output")
        alert_layout = QGridLayout()

        mode_label = QLabel("Alert Mode:")
        mode_label.setFont(QFont("Arial", 10, QFont.Bold))
        self._mode_group = QButtonGroup(self)
        self._both_mode_radio = QRadioButton("Both")
        self._voice_mode_radio = QRadioButton("Voice only")
        self._beep_mode_radio = QRadioButton("Beep only")
        self._off_mode_radio = QRadioButton("Off")
        self._off_mode_radio.setVisible(False)
        self._off_mode_radio.setEnabled(False)
        self._mode_group.addButton(self._both_mode_radio)
        self._mode_group.addButton(self._voice_mode_radio)
        self._mode_group.addButton(self._beep_mode_radio)
        self._mode_group.addButton(self._off_mode_radio)

        current_mode = self.cfg.get("alerts", {}).get("mode", "both")
        if current_mode == "beep":
            self._beep_mode_radio.setChecked(True)
        elif current_mode == "both":
            self._both_mode_radio.setChecked(True)
        elif current_mode == "off":
            self._off_mode_radio.setChecked(True)
        else:
            self._voice_mode_radio.setChecked(True)

        alert_layout.addWidget(mode_label, 0, 0, 1, 3)
        alert_layout.addWidget(self._both_mode_radio, 1, 0)
        alert_layout.addWidget(self._voice_mode_radio, 1, 1)
        alert_layout.addWidget(self._beep_mode_radio, 1, 2)
        alert_layout.addWidget(self._off_mode_radio, 2, 0)

        alert_group.setLayout(alert_layout)
        layout.addWidget(alert_group)

        # ── Path Zone ────────────────────────────────────────────────────
        path_group = QGroupBox("Detection Zone Settings")
        path_layout = QGridLayout()

        path_label = QLabel("Path Zone (% of frame width):")
        path_label.setFont(QFont("Arial", 10, QFont.Bold))
        current_path_zone = self.cfg.get("alerts", {}).get("path_zone", 0.70)
        
        self._path_slider = QSlider(Qt.Horizontal)
        self._path_slider.setMinimum(20)
        self._path_slider.setMaximum(100)
        self._path_slider.setValue(int(current_path_zone * 100))
        self._path_slider.setTickPosition(QSlider.TicksBelow)
        self._path_slider.setTickInterval(10)
        self._path_slider.sliderMoved.connect(self._on_path_slider_change)

        self._path_value_label = QLabel(f"{current_path_zone * 100:.0f}%")
        self._path_value_label.setFont(QFont("Arial", 11, QFont.Bold))
        self._path_value_label.setFixedWidth(50)
        self._path_value_label.setAlignment(Qt.AlignCenter)

        path_layout.addWidget(path_label, 0, 0, 1, 2)
        path_layout.addWidget(self._path_slider, 1, 0)
        path_layout.addWidget(self._path_value_label, 1, 1)

        # Bold NOTE description
        path_note = QLabel(
            "<b>NOTE:</b> Narrower zone = Smaller Travel Path, means stricter detection zone<br>"
            "Wider zone = Catches pedestrians further to the sides"
        )
        path_note.setStyleSheet("color: #888888; font-size: 9pt;")
        path_note.setWordWrap(True)
        path_layout.addWidget(path_note, 2, 0, 1, 2)

        path_group.setLayout(path_layout)
        layout.addWidget(path_group)

        # ── Spacer ───────────────────────────────────────────────────────
        layout.addStretch()

        # ── Buttons ──────────────────────────────────────────────────────
        button_layout = QHBoxLayout()
        
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._on_apply)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)

        button_layout.addStretch()
        button_layout.addWidget(apply_btn)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def _populate_voices(self) -> None:
        """Scan for available voice models."""
        voice_dir = resource_path("models", "voice")
        voices = []
        available_files = set()
        if os.path.exists(voice_dir):
            available_files = {f for f in os.listdir(voice_dir) if f.endswith(".onnx")}

        for label, file_name in VOICE_CHOICES:
            if file_name in available_files or not available_files:
                voices.append((label, resource_path("models", "voice", file_name)))

        if not voices:
            voices = [(VOICE_CHOICES[0][0], resource_path("models", "voice", VOICE_CHOICES[0][1]))]

        for label, file_name in voices:
            self._voice_combo.addItem(label, file_name)

        # Set current voice
        current_voice = os.path.basename(
            self.cfg.get("alerts", {}).get("voice_model", resource_path("models", "voice", "en_US-hfc_male-medium (1).onnx"))
        )
        selected_index = None
        for index in range(self._voice_combo.count()):
            if os.path.basename(str(self._voice_combo.itemData(index))) == current_voice:
                selected_index = index
                break
        if selected_index is not None:
            self._voice_combo.setCurrentIndex(selected_index)
        elif self._voice_combo.count() > 0:
            self._voice_combo.setCurrentIndex(0)

    def _on_path_slider_change(self) -> None:
        """Update path zone value label when slider moves."""
        value = self._path_slider.value()
        self._path_value_label.setText(f"{value}%")

    def _on_apply(self) -> None:
        """Apply settings and emit signal."""
        if self._both_mode_radio.isChecked():
            alert_mode = "both"
        elif self._voice_mode_radio.isChecked():
            alert_mode = "voice"
        elif self._beep_mode_radio.isChecked():
            alert_mode = "beep"
        else:
            alert_mode = "off"

        changes = {
            "path_zone": self._path_slider.value() / 100.0,
            "voice_model": self._voice_combo.currentData(),
            "alert_mode": alert_mode,
        }
        
        self.settings_changed.emit(changes)
        self.close()

    def select_voice_by_label(self, label: str) -> bool:
        """Select a voice in the combo by visible label (e.g. Male/Female)."""
        for index in range(self._voice_combo.count()):
            if self._voice_combo.itemText(index).strip().lower() == label.strip().lower():
                self._voice_combo.setCurrentIndex(index)
                return True
        return False

    def selected_voice_model(self) -> str | None:
        """Return currently selected voice model path."""
        return self._voice_combo.currentData()

    def apply_settings(self) -> None:
        """Public wrapper to apply and close from external triggers (e.g. voice)."""
        self._on_apply()

    def get_settings(self) -> dict:
        """Return current settings as a dict."""
        if self._both_mode_radio.isChecked():
            alert_mode = "both"
        elif self._voice_mode_radio.isChecked():
            alert_mode = "voice"
        elif self._beep_mode_radio.isChecked():
            alert_mode = "beep"
        else:
            alert_mode = "off"

        return {
            "path_zone": self._path_slider.value() / 100.0,
            "voice_model": self._voice_combo.currentData(),
            "alert_mode": alert_mode,
        }
