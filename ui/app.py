"""
app.py – DriveSafe PyQt5 Application Window

Architecture
------------
ProcessingThread  – QThread that runs the full pipeline (capture → detect →
                    draw → record) and emits QImages + status dicts to the GUI.
MainWindow        – QMainWindow with a video area, toolbar (☰ burger menu,
                    ⏺ Record, Mute, Info Panel, Quit) and a colour-coded
                    status bar.
"""

import datetime
import os
import time
import threading, queue

import cv2
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QColor
from PyQt5.QtWidgets import (
    QAction,
    QLabel,
    QMainWindow,
    QMenu,
    QSizePolicy,
    QStatusBar,
    QToolButton,
    QWidget,
)

from core.alerts import AlertManager
from core.capture import VideoCaptureAsync, open_camera
from core.detector import Detector
from core.distance import DistanceEstimator
from core.safety import COLORS, SafetyAssessor, SafetyLevel, is_in_path
from ui.archive import RECORDINGS_DIR, ArchiveWindow
from ui.display import draw_hud, draw_info_panel


# ── Safety-level colours re-expressed as hex for Qt ──────────────────────────
_LEVEL_COLOR = {
    SafetyLevel.SAFE:    "#1a9e1a",
    SafetyLevel.WARNING: "#c8920a",
    SafetyLevel.DANGER:  "#c01515",
}
_LEVEL_LABEL = {
    SafetyLevel.SAFE:    "SAFE",
    SafetyLevel.WARNING: "WARNING",
    SafetyLevel.DANGER:  "DANGER",
}


# ─────────────────────────────────────────────────────────────────────────────
#  Processing thread
# ─────────────────────────────────────────────────────────────────────────────

class ProcessingThread(QThread):
    """Runs capture → detect → HUD draw in a background thread.

    Signals
    -------
    frame_ready  – QImage ready to paint on screen.
    status_ready – dict with fps, counts, safety level, mute state.
    """

    frame_ready       = pyqtSignal(QImage)
    status_ready      = pyqtSignal(dict)
    recording_changed = pyqtSignal(bool)   # True = started, False = stopped
    ready             = pyqtSignal() 

    def __init__(self, cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self.cfg       = cfg
        self._running  = True

        # State flags – written atomically (GIL-safe for bool/None assignment)
        self.show_info            = False
        self._toggle_alerts_flag  = False
        self._start_rec_flag      = False
        self._stop_rec_flag       = False
        self._writer              = None   # cv2.VideoWriter when recording
        self._pending_rec_path    = None   # path queued before first frame
        self._write_queue         = queue.Queue()
        self._write_thread        = None
    
    def _writer_worker(self) -> None:
        while True:
            item = self._write_queue.get()
            if item is None:  # sentinel to stop
                break
            if self._writer is not None:
                self._writer.write(item)
    

    # ── Controls (called from the GUI thread) ─────────────────────────────────

    def request_toggle_alerts(self) -> None:
        self._toggle_alerts_flag = True

    def request_toggle_info(self) -> None:
        self.show_info = not self.show_info

    def request_start_recording(self) -> None:
        self._start_rec_flag = True

    def request_stop_recording(self) -> None:
        self._stop_rec_flag = True

    def stop(self) -> None:
        self._running = False
        self.wait()

    # ── Thread body ───────────────────────────────────────────────────────────

    def run(self) -> None:  # noqa: C901
        cfg = self.cfg

        # Initialise camera
        cap = VideoCaptureAsync(open_camera(cfg)).start()

        # Initialise pipeline modules
        detector = Detector(
            weights    = cfg["model"]["weights"],
            confidence = cfg["model"]["confidence"],
            iou        = cfg["model"]["iou"],
            imgsz      = cfg["model"].get("imgsz", 640),
            device     = str(cfg["model"].get("device", "0")),
            half       = cfg["model"].get("half", True),
        )
        self.ready.emit()   
        estimator = DistanceEstimator(
            focal_length  = cfg["distance"]["focal_length"],
            person_height = cfg["distance"]["person_height"],
            crosswalk_a   = cfg["distance"].get("crosswalk_a", -0.015),
            crosswalk_b   = cfg["distance"].get("crosswalk_b", 15.0),
        )
        assessor = SafetyAssessor({
            "pedestrian": (cfg["safety"]["pedestrian"]["danger"],
                           cfg["safety"]["pedestrian"]["warning"]),
            "crosswalk":  (cfg["safety"]["crosswalk"]["danger"],
                           cfg["safety"]["crosswalk"]["warning"]),
        })

        alert_cfg = cfg.get("alerts", {})
        alert_mgr = AlertManager(
            enabled    = alert_cfg.get("enabled", True),
            voice_rate = alert_cfg.get("voice_rate", 160),
            cooldowns  = {
                "danger":    alert_cfg.get("danger_cooldown",    2.5),
                "warning":   alert_cfg.get("warning_cooldown",   5.0),
                "crosswalk": alert_cfg.get("crosswalk_cooldown", 7.0),
            },
        )
        path_zone = alert_cfg.get("path_zone", 0.40)

        fps       = 0.0
        prev_time = time.perf_counter()

        while self._running:
            frame_start = time.perf_counter()

            # Handle pending UI toggles
            if self._toggle_alerts_flag:
                alert_mgr.enabled          = not alert_mgr.enabled
                self._toggle_alerts_flag   = False

            # Handle recording stop
            if self._stop_rec_flag:
                self._stop_rec_flag    = False
                self._pending_rec_path = None
                if self._writer is not None:
                    self._write_queue.put(None)          # stop the worker
                    if self._write_thread is not None:
                        self._write_thread.join()
                        self._write_thread = None
                    self._writer.release()
                    self._writer = None
                    self.recording_changed.emit(False)

            # Handle recording start (writer created after first frame for size)
            if self._start_rec_flag:
                self._start_rec_flag = False
                if self._writer is None:
                    os.makedirs(RECORDINGS_DIR, exist_ok=True)
                    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    self._pending_rec_path = os.path.join(
                        RECORDINGS_DIR, f"drivesafe_{ts}.avi"
                    )

            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            # Create writer now that we know the frame dimensions
            if self._pending_rec_path is not None:
                h_f, w_f = frame.shape[:2]
                self._writer = cv2.VideoWriter(
                    self._pending_rec_path,
                    cv2.VideoWriter_fourcc(*"MJPG"),
                    20.0,
                    (w_f, h_f),
                )
                self._pending_rec_path = None
                self.recording_changed.emit(True)
                self._write_thread = threading.Thread(target=self._writer_worker, daemon=True)
                self._write_thread.start()

            # Exponential-moving-average FPS
            now       = time.perf_counter()
            fps       = 0.9 * fps + 0.1 * (1.0 / max(now - prev_time, 1e-9))
            prev_time = now

            detections = detector.track(frame)

            # ── Determine alerts ──────────────────────────────────────────────
            _, frame_w     = frame.shape[:2]
            in_path_levels = []
            cw_worst       = None

            for det in detections:
                dist  = estimator.estimate(det.cls_name, det.bbox)
                level = assessor.assess(det.cls_name, dist)
                if det.cls_name == "pedestrian":
                    if is_in_path(det.bbox, frame_w, path_zone):
                        in_path_levels.append(level)
                elif det.cls_name == "crosswalk":
                    cw_worst = SafetyLevel(max(int(cw_worst or 0), int(level)))

            alert_text  = None
            alert_color = None

            if in_path_levels:
                worst = SafetyLevel(max(in_path_levels))
                count = len(in_path_levels)
                if worst == SafetyLevel.DANGER:
                    voice = "Brake now!" if count == 1 else "Multiple pedestrians! Brake now!"
                    alert_mgr.fire("ped_danger", voice, level="danger")
                    alert_text  = "BRAKE NOW" if count == 1 else f"BRAKE NOW  ({count} IN PATH)"
                    alert_color = COLORS[SafetyLevel.DANGER]
                elif worst == SafetyLevel.WARNING:
                    alert_mgr.fire("ped_warning", "Slow down, pedestrian ahead", level="warning")
                    alert_text  = "SLOW DOWN"
                    alert_color = COLORS[SafetyLevel.WARNING]

            if cw_worst is not None and cw_worst >= SafetyLevel.WARNING:
                alert_mgr.fire("crosswalk", "Crosswalk ahead, be careful", level="crosswalk")
                if alert_text is None:
                    alert_text  = "CROSSWALK AHEAD  —  BE CAREFUL"
                    alert_color = COLORS[SafetyLevel.WARNING]

            ms_id = (time.perf_counter() - frame_start) * 1000.0

            # ── Draw HUD (existing OpenCV pipeline, unchanged) ────────────────
            overall = draw_hud(
                frame, detections, assessor, estimator,
                path_zone=path_zone,
                alert_text=alert_text,
                alert_color=alert_color,
            )

            if self.show_info:
                draw_info_panel(frame, cfg, fps)

            # ── Write frame to recording ──────────────────────────────────────
            if self._writer is not None:
                self._write_queue.put(frame.copy())

            # ── Emit status dict ──────────────────────────────────────────────
            self.status_ready.emit({
                "fps":       fps,
                "ms":        ms_id,
                "n_ped":     sum(1 for d in detections if d.cls_name == "pedestrian"),
                "n_cw":      sum(1 for d in detections if d.cls_name == "crosswalk"),
                "level":     overall,
                "muted":     not alert_mgr.enabled,
                "recording": self._writer is not None,
            })

            # ── Convert BGR frame → QImage and emit ──────────────────────────
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
            self.frame_ready.emit(qimg.copy())

        # Release resources
        if self._writer is not None:
            self._write_queue.put(None)
            if self._write_thread is not None:
                self._write_thread.join()
                self._write_thread = None
            self._writer.release()
            self._writer = None

        cap.release()


# ─────────────────────────────────────────────────────────────────────────────
#  Main window
# ─────────────────────────────────────────────────────────────────────────────

_TOOLBAR_STYLE = """
QToolBar {
    background: #1a1a1a;
    border-bottom: 1px solid #2e2e2e;
    spacing: 4px;
    padding: 4px 8px;
}
QToolButton {
    color: #cccccc;
    font-size: 13px;
    padding: 4px 14px;
    border-radius: 4px;
    background: transparent;
}
QToolButton:hover {
    background: #2e2e2e;
}
QToolButton:checked {
    background: #2a4a7a;
    color: #ffffff;
}
QToolButton#rec_btn:checked {
    background: #8b1010;
    color: #ffffff;
}
"""

_STATUS_BASE = "QStatusBar { background: #1a1a1a; padding: 2px 8px; font-size: 12px; font-weight: bold; }"


class MainWindow(QMainWindow):
    """The main application window."""

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("DriveSafe")
        self.setMinimumSize(900, 560)

        # ── Video display ─────────────────────────────────────────────────────
        self._video = QLabel("Loading model\u2026")
        self._video.setAlignment(Qt.AlignCenter)
        self._video.setStyleSheet("background: #111111; color: #666;")
        self._video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCentralWidget(self._video)

        # ── Toolbar ───────────────────────────────────────────────────────────
        self._toolbar = self.addToolBar("Controls")
        toolbar = self._toolbar
        toolbar.setMovable(False)
        toolbar.setStyleSheet(_TOOLBAR_STYLE)

        # ── Burger menu (left side) ───────────────────────────────────────────
        burger_btn = QToolButton()
        burger_btn.setText("☰")
        burger_btn.setToolTip("Menu")
        burger_menu = QMenu(burger_btn)
        burger_menu.setStyleSheet(
            "QMenu { background: #252525; color: #cccccc; border: 1px solid #3e3e3e; font-size: 13px; }"
            "QMenu::item { padding: 6px 24px; }"
            "QMenu::item:selected { background: #3c64b4; }"
        )
        archive_action = QAction("📁   Archive", self)
        archive_action.triggered.connect(self._on_archive)
        burger_menu.addAction(archive_action)
        burger_btn.setMenu(burger_menu)
        burger_btn.setPopupMode(QToolButton.InstantPopup)
        toolbar.addWidget(burger_btn)

        # Push remaining buttons to the right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        # ── Record button ─────────────────────────────────────────────────────
        self._rec_action = QAction("⏺   Record", self, checkable=True)
        self._rec_action.setToolTip("Start / stop recording  (R)")
        self._rec_action.triggered.connect(self._on_record)
        toolbar.addAction(self._rec_action)
        # Give the record button a distinct object name for red-when-active style
        rec_widget = toolbar.widgetForAction(self._rec_action)
        if rec_widget:
            rec_widget.setObjectName("rec_btn")

        self._mute_action = QAction("Mute Alerts", self, checkable=True)
        self._mute_action.setToolTip("Toggle voice alerts  (M)")
        self._mute_action.triggered.connect(self._on_mute)
        toolbar.addAction(self._mute_action)

        self._info_action = QAction("Info Panel", self, checkable=True)
        self._info_action.setToolTip("Toggle info overlay  (I)")
        self._info_action.triggered.connect(self._on_info)
        toolbar.addAction(self._info_action)

        quit_action = QAction("Quit", self)
        quit_action.setToolTip("Quit DriveSafe  (Q)")
        quit_action.triggered.connect(self.close)
        toolbar.addAction(quit_action)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.setStyleSheet(_STATUS_BASE + " color: #888;")
        self._status_bar.showMessage("Starting…")

        # ── Processing thread ─────────────────────────────────────────────────
        self._thread = ProcessingThread(cfg, parent=self)
        self._thread.frame_ready.connect(self._on_frame)
        self._thread.status_ready.connect(self._on_status)
        self._thread.recording_changed.connect(self._on_recording_changed)
        self._thread.start()

        self.showFullScreen()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_frame(self, img: QImage) -> None:
        pix = QPixmap.fromImage(img).scaled(
            self._video.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._video.setPixmap(pix)

    def _on_status(self, info: dict) -> None:
        level     = info["level"]
        color_hex = _LEVEL_COLOR.get(level, "#888888")
        muted_tag = "  |  MUTED" if info["muted"] else ""
        rec_tag   = "  |  ● REC" if info.get("recording") else ""

        msg = (
            f"FPS: {info['fps']:.0f}  ({info['ms']:.1f} ms)"
            f"   PED: {info['n_ped']}"
            f"   CW: {info['n_cw']}"
            f"{muted_tag}"
            f"{rec_tag}"
        )
        self._status_bar.showMessage(msg)
        self._status_bar.setStyleSheet(
            _STATUS_BASE + f" color: {color_hex};"
        )

        # Keep mute button in sync with alert_mgr state
        if self._mute_action.isChecked() != info["muted"]:
            self._mute_action.blockSignals(True)
            self._mute_action.setChecked(info["muted"])
            self._mute_action.blockSignals(False)

        # Update title bar with REC indicator
        rec_title = "  ●  REC" if info.get("recording") else ""
        self.setWindowTitle(f"DriveSafe{rec_title}")

    def _on_mute(self) -> None:
        self._thread.request_toggle_alerts()

    def _on_info(self) -> None:
        self._thread.request_toggle_info()

    def _on_record(self) -> None:
        if self._rec_action.isChecked():
            self._thread.request_start_recording()
        else:
            self._thread.request_stop_recording()

    def _on_archive(self) -> None:
        ArchiveWindow(parent=self).exec_()

    def _on_recording_changed(self, is_recording: bool) -> None:
        """Keep Record button checked-state in sync with the actual writer."""
        self._rec_action.blockSignals(True)
        self._rec_action.setChecked(is_recording)
        self._rec_action.blockSignals(False)

    # ── Keyboard shortcuts ────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key_F11:
            self._toggle_fullscreen()
        elif key == Qt.Key_Escape:
            if self.isFullScreen():
                self._toggle_fullscreen()
            else:
                self.close()
        elif key == Qt.Key_Q:
            self.close()
        elif key == Qt.Key_R:
            self._rec_action.setChecked(not self._rec_action.isChecked())
            self._on_record()
        elif key == Qt.Key_M:
            self._mute_action.trigger()
        elif key == Qt.Key_I:
            self._info_action.setChecked(not self._info_action.isChecked())
            self._on_info()
        
    def _toggle_fullscreen(self) -> None:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()

    def changeEvent(self, event) -> None:
            super().changeEvent(event)
            from PyQt5.QtCore import QEvent
            if event.type() == QEvent.WindowStateChange:
                is_fs = self.isFullScreen()
                self._toolbar.setVisible(not is_fs)
                self._status_bar.setVisible(not is_fs)
    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._thread.stop()
        event.accept()
