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
import logging

import cv2
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap, QColor
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QFrame,
    QSizePolicy,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.alerts import AlertManager
from ..core.braking import BrakingModel
from ..core.clip import ClipRecorder
from ..core.capture import VideoCaptureAsync, open_camera
from ..core.detector import Detector
from ..core.distance import DistanceEstimator
from ..core.gps import GPSReader
from ..core.roadcorridor import LaneCorridorEstimator
from ..core.safety import COLORS, SafetyAssessor, SafetyLevel, is_in_corridor
from ..core.voicecommand import VoiceCommandRecognizer
from ..core.paths import resource_path
from .archive import RECORDINGS_DIR, ArchiveWindow
from .display import draw_hud
from .settings import SettingsWindow


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
    voice_command     = pyqtSignal(dict)   # {"action": "...", "confidence": 0.95, "text": "..."}
    ready             = pyqtSignal() 

    def __init__(self, cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self.cfg       = cfg
        self._running  = True

        # State flags – written atomically (GIL-safe for bool/None assignment)
        self.show_info            = False
        self._toggle_alerts_flag  = False
        self._set_alerts_enabled_flag = None
        self._start_rec_flag      = False
        self._stop_rec_flag       = False
        self._writer              = None   # cv2.VideoWriter when recording
        self._pending_rec_path    = None   # path queued before first frame
        self._write_queue         = queue.Queue(maxsize=16)
        self._write_thread        = None
        self._gps                 = GPSReader()
        self._voice_recognizer    = None  # Initialized in run() with config
        self._voice_command_queue = queue.Queue(maxsize=8)  # Non-blocking voice results
        self._voice_worker_thread = None
        
        # Runtime settings that can be changed via UI
        self._path_zone = cfg.get("alerts", {}).get("path_zone", 0.70)
        self._alert_mode = cfg.get("alerts", {}).get("mode", "voice")
        self._voice_model = cfg.get("alerts", {}).get("voice_model", resource_path("models", "voice", "en_US-hfc_male-medium (1).onnx"))
        self._ped_path_hold_s = cfg.get("alerts", {}).get("ped_path_hold_s", 1.5)
        self._ped_path_alert_until = 0.0
        self._ped_path_alert_level = None
        self._ped_path_audio_level = None
        self._dynamic_corridor = None
        self._dynamic_lane_lines = None
        self._lane_status_notice_until = 0.0
        self._last_lane_detected = None
    
    def _writer_worker(self) -> None:
        while True:
            item = self._write_queue.get()
            if item is None:  # sentinel to stop
                break
            if self._writer is not None:
                self._writer.write(item)

    @staticmethod
    def _put_latest(q: queue.Queue, item) -> None:
        """Queue the newest item; drop oldest one if queue is full."""
        try:
            q.put_nowait(item)
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(item)
            except queue.Full:
                pass

    @staticmethod
    def _drain_queue(q: queue.Queue) -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break

    def _voice_worker(self) -> None:
        """Background thread: continuously recognize voice commands (non-blocking)."""
        while self._running and self._voice_recognizer is not None:
            try:
                cmd = self._voice_recognizer.recognize()
                if cmd is not None and cmd.get("action"):
                    confidence = cmd.get("confidence", 0.0)
                    if confidence >= 0.7:  # Only queue high-confidence matches
                        self._put_latest(self._voice_command_queue, cmd)
            except Exception as e:
                logger_app = logging.getLogger(__name__)
                logger_app.debug(f"Voice worker error: {e}")
                time.sleep(0.1)  # Brief pause before retry
    

    # ── Controls (called from the GUI thread) ─────────────────────────────────

    def request_toggle_alerts(self) -> None:
        self._toggle_alerts_flag = True

    def request_set_alerts_enabled(self, enabled: bool) -> None:
        self._set_alerts_enabled_flag = enabled

    def request_toggle_info(self) -> None:
        self.show_info = not self.show_info

    def set_path_zone(self, value: float) -> None:
        """Update path zone at runtime (thread-safe)."""
        self._path_zone = max(0.1, min(1.0, value))

    def set_alert_mode(self, value: str) -> None:
        self._alert_mode = value if value in {"beep", "voice", "both", "off"} else "both"
        if hasattr(self, "_alert_mgr") and self._alert_mgr is not None:
            self._alert_mgr.set_mode(self._alert_mode)

    def set_voice_model(self, value: str) -> None:
        self._voice_model = value or resource_path("models", "voice", "en_US-hfc_male-medium (1).onnx")
        if hasattr(self, "_alert_mgr") and self._alert_mgr is not None:
            self._alert_mgr.set_voice_model(self._voice_model)

    def request_start_recording(self) -> None:
        self._start_rec_flag = True

    def request_stop_recording(self) -> None:
        self._stop_rec_flag = True

    def stop(self) -> None:
        self._running = False
        self._gps.stop()
        self.wait()

    # ── Thread body ───────────────────────────────────────────────────────────

    def run(self) -> None:  # noqa: C901
        cfg = self.cfg

        # Initialise camera
        cap = VideoCaptureAsync(open_camera(cfg)).start()

        # Start GPS reader (daemon thread – safe to start before model loads)
        self._gps.start()

        # Initialize voice command recognizer (if enabled)
        voice_enabled = cfg.get("voice_commands", {}).get("enabled", False)
        if voice_enabled:
            model_path = cfg["voice_commands"].get("model_path", "models/vosk-model-small-en-us-0.15")
            if model_path and not os.path.isabs(model_path):
                model_path = resource_path(model_path)
            device_idx = cfg["voice_commands"].get("device_index")
            sample_rate = cfg["voice_commands"].get("sample_rate", 16000)
            try:
                self._voice_recognizer = VoiceCommandRecognizer(
                    model_path=model_path,
                    device_index=device_idx,
                    sample_rate=sample_rate,
                )
                print("[DriveSafe] ✓ Voice commands enabled")
                # Start background thread for voice recognition
                self._voice_worker_thread = threading.Thread(
                    target=self._voice_worker,
                    name="VoiceWorker",
                    daemon=True
                )
                self._voice_worker_thread.start()
            except Exception as e:
                print(f"[DriveSafe] ✗ Failed to initialize voice commands: {e}")
                self._voice_recognizer = None
        detector = Detector(
            weights    = cfg["model"]["weights"],
            confidence = cfg["model"]["confidence"],
            iou        = cfg["model"]["iou"],
            imgsz      = cfg["model"].get("imgsz", 640),
            device     = str(cfg["model"].get("device", "0")),
            half       = cfg["model"].get("half", True),
            tracker    = (
                resource_path(cfg["model"].get("tracker"))
                if cfg["model"].get("tracker")
                and cfg["model"].get("tracker") != "bytetrack.yaml"
                and not os.path.isabs(cfg["model"].get("tracker"))
                else cfg["model"].get("tracker", "bytetrack.yaml")
            ),
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
        braking_cfg = cfg.get("braking", {})
        braking_model = BrakingModel(
            reaction_time_s=braking_cfg.get("reaction_time_s", 1.5),
            safety_margin=braking_cfg.get("safety_margin", 1.20),
            mu=braking_cfg.get("dry_asphalt_mu", 0.75),
        )
        self._alert_mgr = AlertManager(
            enabled    = alert_cfg.get("enabled", True),
            voice_rate = alert_cfg.get("voice_rate", 160),
            cooldowns  = {
                "danger":    alert_cfg.get("danger_cooldown",    1.5),
                "warning":   alert_cfg.get("warning_cooldown",   5.0),
                "crosswalk": alert_cfg.get("crosswalk_cooldown", 2.5),
            },
            mode       = self._alert_mode,
            voice_model = self._voice_model,
        )
        alert_mgr = self._alert_mgr

        # ── Clip recorder (automatic danger clips) ────────────────────────
        clip_cfg     = cfg.get("clips", {})
        clip_enabled = clip_cfg.get("enabled", True)
        clip_trigger = (SafetyLevel.DANGER
                        if clip_cfg.get("trigger_level", "danger") == "danger"
                        else SafetyLevel.WARNING)
        clip_recorder = ClipRecorder(
            output_dir  = RECORDINGS_DIR,
            fps         = 20.0,
            pre_seconds  = clip_cfg.get("pre_seconds", 3.0),
            post_seconds = clip_cfg.get("post_seconds", 3.0),
            cooldown     = clip_cfg.get("cooldown", 10.0),
        )

        dyn_cfg = alert_cfg.get("dynamic_path", {})
        dynamic_path_enabled = dyn_cfg.get("enabled", True)
        lane_status_notice_duration_s = dyn_cfg.get("lane_status_notice_duration_s", 3.0)
        corridor_estimator = LaneCorridorEstimator(
            update_every_frames=dyn_cfg.get("update_every_frames", 5),
            ema_alpha=dyn_cfg.get("ema_alpha", 0.30),
            roi_top_fraction=dyn_cfg.get("roi_top_fraction", 0.55),
            min_width_fraction=dyn_cfg.get("min_width_fraction", 0.20),
            max_width_fraction=dyn_cfg.get("max_width_fraction", 0.95),
            max_missed_updates=dyn_cfg.get("max_missed_updates", 8),
        )

        fps       = 0.0
        prev_time = time.perf_counter()
        run_start_time = prev_time

        while self._running:
            frame_start = time.perf_counter()

            # Handle pending UI toggles
            if self._set_alerts_enabled_flag is not None:
                alert_mgr.enabled = self._set_alerts_enabled_flag
                self._set_alerts_enabled_flag = None
            if self._toggle_alerts_flag:
                alert_mgr.enabled          = not alert_mgr.enabled
                self._toggle_alerts_flag   = False

            # Handle recording stop
            if self._stop_rec_flag:
                self._stop_rec_flag    = False
                self._pending_rec_path = None
                if self._writer is not None:
                    self._drain_queue(self._write_queue)
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
            speed_kmh = self._gps.speed_kmh
            is_stationary = speed_kmh is not None and speed_kmh <= 0.5
            is_moving = speed_kmh is not None and speed_kmh > 0.5

            if dynamic_path_enabled:
                corridor, _ = corridor_estimator.update(frame)
                self._dynamic_corridor = corridor
                self._dynamic_lane_lines = corridor_estimator.lane_lines_norm
            else:
                self._dynamic_corridor = None
                self._dynamic_lane_lines = None

            lane_detected = dynamic_path_enabled and self._dynamic_corridor is not None
            if self._last_lane_detected is None or lane_detected != self._last_lane_detected:
                self._last_lane_detected = lane_detected
                self._lane_status_notice_until = time.perf_counter() + lane_status_notice_duration_s
                if lane_detected:
                    msg = "LANE DETECTED"
                else:
                    msg = "NO LANE DETECTED - USING DEFAULT PATH LINES"
                print(f"[DriveSafe] {msg}")

            # ── Determine alerts ──────────────────────────────────────────────
            _, frame_w     = frame.shape[:2]
            in_path_levels = []
            crosswalk_detected = False
            now_alert      = time.perf_counter()

            for det in detections:
                dist  = estimator.estimate(det.cls_name, det.bbox)
                level = assessor.assess(det.cls_name, dist)
                if det.cls_name == "pedestrian":
                    if is_in_corridor(
                        det.bbox,
                        frame_w,
                        self._dynamic_corridor,
                        self._path_zone,
                        lane_lines_norm=self._dynamic_lane_lines,
                        frame_height=frame.shape[0],
                    ):
                        if is_moving:
                            stop_dist_m = self._gps.stopping_distance_m(model=braking_model)
                            if stop_dist_m is not None and stop_dist_m > 0.0:
                                ratio = dist / stop_dist_m
                                if ratio <= 1.0:
                                    level = SafetyLevel.DANGER
                                elif ratio <= 1.5:
                                    level = SafetyLevel.WARNING
                                else:
                                    level = SafetyLevel.SAFE
                        elif is_stationary:
                            level = assessor.assess(det.cls_name, dist)
                        in_path_levels.append(level)
                elif det.cls_name == "crosswalk":
                    crosswalk_detected = True

            alert_text  = None
            alert_color = None

            if not in_path_levels:
                alert_mgr.stop_current_alert("ped_")
                self._ped_path_audio_level = None

            if in_path_levels:
                worst = SafetyLevel(max(in_path_levels))
                count = len(in_path_levels)
                # Only warning/danger states should persist briefly after a frame drop.
                if worst >= SafetyLevel.WARNING:
                    self._ped_path_alert_until = now_alert + self._ped_path_hold_s
                    self._ped_path_alert_level = worst
                else:
                    self._ped_path_alert_level = None
                if worst == SafetyLevel.DANGER:
                    if not is_stationary:
                        voice = "BRAKE NOW!" if count == 1 else "Multiple pedestrians! BRAKE NOW!"
                        alert_mgr.fire("ped_danger", voice, level="danger")
                    self._ped_path_audio_level = worst
                elif worst == SafetyLevel.WARNING:
                    if not is_stationary:
                        voice = "SLOW DOWN!" if count == 1 else f"{count} pedestrians ahead, SLOW DOWN!"
                        alert_mgr.fire("ped_warning", voice, level="warning")
                    self._ped_path_audio_level = worst

                if worst == SafetyLevel.DANGER:
                    alert_text  = "BRAKE NOW" if count == 1 else f"BRAKE NOW  ({count} IN PATH)"
                    alert_color = COLORS[SafetyLevel.DANGER]
                elif worst == SafetyLevel.WARNING:
                    alert_text  = "SLOW DOWN"
                    alert_color = COLORS[SafetyLevel.WARNING]
            elif (
                self._ped_path_alert_until > now_alert
                and self._ped_path_alert_level in (SafetyLevel.WARNING, SafetyLevel.DANGER)
            ):
                if self._ped_path_alert_level == SafetyLevel.DANGER:
                    alert_text  = "BRAKE NOW"
                    alert_color = COLORS[SafetyLevel.DANGER]
                elif self._ped_path_alert_level == SafetyLevel.WARNING:
                    alert_text  = "SLOW DOWN"
                    alert_color = COLORS[SafetyLevel.WARNING]
            else:
                self._ped_path_alert_level = None

            if crosswalk_detected:
                alert_mgr.fire("crosswalk", "Crosswalk ahead", level="warning")
                if alert_text is None:
                    alert_text  = "CROSSWALK AHEAD"
                    alert_color = COLORS[SafetyLevel.WARNING]

            ms_id = (time.perf_counter() - frame_start) * 1000.0
            info_text = None
            if time.perf_counter() <= self._lane_status_notice_until:
                info_text = (
                    "LANE DETECTED"
                    if self._last_lane_detected
                    else "NO LANE DETECTED - USING DEFAULT PATH LINES"
                )

            # ── Draw HUD (existing OpenCV pipeline, unchanged) ────────────────
            overall = draw_hud(
                frame, detections, assessor, estimator,
                path_zone=self._path_zone,
                corridor=self._dynamic_corridor,
                lane_lines=self._dynamic_lane_lines,
                info_text=info_text,
                alert_text=alert_text,
                alert_color=alert_color,
                speed_kmh=speed_kmh,
            )



            # ── Write frame to recording ──────────────────────────────────────
            if self._writer is not None:
                self._put_latest(self._write_queue, frame.copy())
            # ── Clip recorder: feed every frame, trigger on danger ────────────
            if clip_enabled:
                clip_recorder.feed(frame)
                if overall >= clip_trigger:
                    clip_recorder.trigger(SafetyAssessor.label(overall).lower())

            # ── Emit status dict ──────────────────────────────────────────────
            self.status_ready.emit({
                "fps":       fps,
                "ms":        ms_id,
                "n_ped":     sum(1 for d in detections if d.cls_name == "pedestrian"),
                "n_cw":      sum(1 for d in detections if d.cls_name == "crosswalk"),
                "level":     overall,
                "muted":     (not alert_mgr.enabled) or alert_mgr.mode == "off",
                "recording": self._writer is not None,
            })

            # ── Convert BGR frame → QImage and emit ──────────────────────────
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
            self.frame_ready.emit(qimg.copy())

            # ── Check for voice commands (non-blocking queue check) ──────────────
            latest_cmd = None
            while True:
                try:
                    latest_cmd = self._voice_command_queue.get_nowait()
                except queue.Empty:
                    break
            if latest_cmd is not None:
                print(f"[DriveSafe] 🎤 Voice: {latest_cmd['text']} → {latest_cmd['action']} ({latest_cmd.get('confidence', 0.0):.1%})")
                self.voice_command.emit(latest_cmd)

        # Release resources
        clip_recorder.release()

        # Stop voice worker thread
        if self._voice_recognizer is not None:
            self._voice_recognizer.close()
            self._voice_recognizer = None
        if self._voice_worker_thread is not None:
            self._voice_worker_thread.join(timeout=2.0)
            self._voice_worker_thread = None

        if self._writer is not None:
            self._drain_queue(self._write_queue)
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
    font-size: 15px;
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


class LegendDialog(QDialog):
    """Small color legend shown automatically on startup."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DriveSafe Color Legend")
        self.setModal(False)
        self.setWindowFlags(Qt.Tool | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setMinimumWidth(420)
        self.setStyleSheet(
            "QDialog { background-color: #1a1a1a; color: #d7d7d7; }"
            "QLabel { color: #d7d7d7; font-size: 12px; }"
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Safety Color Indicators")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #f2f2f2;")
        layout.addWidget(title)

        subtitle = QLabel("This guide closes automatically.")
        subtitle.setStyleSheet("color: #9d9d9d;")
        layout.addWidget(subtitle)

        self._add_row(layout, "#1a9e1a", "Green", "SAFE: normal condition")
        self._add_row(layout, "#c8920a", "Yellow", "WARNING: slow down and watch ahead")
        self._add_row(layout, "#c01515", "Red", "DANGER: brake immediately")

        self.setLayout(layout)

    def _add_row(self, parent_layout: QVBoxLayout, color_hex: str, name: str, text: str) -> None:
        row = QHBoxLayout()
        swatch = QFrame()
        swatch.setFixedSize(22, 22)
        swatch.setStyleSheet(f"background: {color_hex}; border: 1px solid #666;")

        label = QLabel(f"{name}: {text}")
        row.addWidget(swatch)
        row.addWidget(label)
        row.addStretch()
        parent_layout.addLayout(row)

    def show_with_auto_close(self, close_after_ms: int = 5000) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(close_after_ms, self.close)


class MainWindow(QMainWindow):
    """The main application window."""

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.cfg = cfg
        self._settings_window = None
        self._archive_window = None
        self._legend_dialog = None
        self._last_voice_action_ts = {}
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
        archive_action = QAction("💾   Archive", self)
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
        self._rec_action = QAction("🔴  Record", self, checkable=True)
        self._rec_action.setToolTip("Start / stop recording  (R)")
        self._rec_action.triggered.connect(self._on_record)
        toolbar.addAction(self._rec_action)
        # Give the record button a distinct object name for red-when-active style
        rec_widget = toolbar.widgetForAction(self._rec_action)
        if rec_widget:
            rec_widget.setObjectName("rec_btn")

        self._mute_action = QAction("🔇  Mute Alerts", self, checkable=True)
        self._mute_action.setToolTip("Toggle voice alerts  (M)")
        self._mute_action.triggered.connect(self._on_mute)
        toolbar.addAction(self._mute_action)

        self._info_action = QAction("⚙️  Settings", self, checkable=False)
        self._info_action.setToolTip("Open settings  (I)")
        self._info_action.triggered.connect(self._on_settings)
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
        self._thread.voice_command.connect(self._on_voice_command)
        self._thread.start()

        self.showFullScreen()
        QTimer.singleShot(2000, self._show_entry_legend)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_frame(self, img: QImage) -> None:
        pix = QPixmap.fromImage(img).scaled(
            self._video.size(),
            Qt.IgnoreAspectRatio,
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

    def _on_settings(self) -> None:
        """Open the settings dialog."""
        if self._settings_window is not None and self._settings_window.isVisible():
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return
        self._settings_window = SettingsWindow(self.cfg, parent=self)
        self._settings_window.settings_changed.connect(self._on_settings_changed)
        self._settings_window.exec_()
        self._settings_window = None

    def _on_archive(self) -> None:
        if self._archive_window is not None and self._archive_window.isVisible():
            self._archive_window.raise_()
            self._archive_window.activateWindow()
            return
        self._archive_window = ArchiveWindow(parent=self)
        self._archive_window.exec_()
        self._archive_window = None

    def _is_voice_action_rate_limited(self, action: str, cooldown_s: float = 1.2) -> bool:
        """Return True when the same voice action fired too recently."""
        now = time.monotonic()
        last = self._last_voice_action_ts.get(action, 0.0)
        if now - last < cooldown_s:
            return True
        self._last_voice_action_ts[action] = now
        return False

    def _on_settings_changed(self, settings: dict) -> None:
        """Handle settings changes from the settings dialog."""
        # Update config
        if "path_zone" in settings:
            self.cfg["alerts"]["path_zone"] = settings["path_zone"]
            self._thread.set_path_zone(settings["path_zone"])
        if "voice_model" in settings:
            self.cfg["alerts"]["voice_model"] = settings["voice_model"]
            self._thread.set_voice_model(settings["voice_model"])
        if "alert_mode" in settings:
            self.cfg["alerts"]["mode"] = settings["alert_mode"]
            self._thread.set_alert_mode(settings["alert_mode"])
        
        print(f"[DriveSafe] ✓ Settings updated: {settings}")

    def _show_entry_legend(self) -> None:
        self._show_legend_popup(auto_close_ms=5000)

    def _show_legend_popup(self, auto_close_ms: int = 5000) -> None:
        if self._legend_dialog is None:
            self._legend_dialog = LegendDialog(self)
        self._legend_dialog.show_with_auto_close(close_after_ms=auto_close_ms)

    def _on_record(self) -> None:
        if self._rec_action.isChecked():
            self._thread.request_start_recording()
        else:
            self._thread.request_stop_recording()

    def _on_recording_changed(self, is_recording: bool) -> None:
        """Keep Record button checked-state in sync with the actual writer."""
        self._rec_action.blockSignals(True)
        self._rec_action.setChecked(is_recording)
        self._rec_action.blockSignals(False)

    @pyqtSlot(dict)
    def _on_voice_command(self, cmd: dict) -> None:
        """Handle recognized voice commands."""
        action = cmd.get("action")
        confidence = cmd.get("confidence", 0.0)
        text = cmd.get("text", "")
        
        print(f" Voice command received: '{text}' → executing '{action}'")
        
        if action == "open_archive":
            if self._is_voice_action_rate_limited("open_archive"):
                print("[DriveSafe] → Ignoring duplicate 'open archive' command")
                return
            print(f"[DriveSafe] → Opening archive...")
            self._on_archive()
        elif action == "close_archive":
            print(f"[DriveSafe] → Closing archive...")
            if self._archive_window is not None and self._archive_window.isVisible():
                self._archive_window.close()
            else:
                # Fallback: close any visible archive dialog if reference was lost.
                for widget in QApplication.topLevelWidgets():
                    if isinstance(widget, ArchiveWindow) and widget.isVisible():
                        widget.close()
                        break
        elif action == "open_settings":
            if self._is_voice_action_rate_limited("open_settings"):
                print("[DriveSafe] → Ignoring duplicate 'open settings' command")
                return
            print("[DriveSafe] → Opening settings...")
            self._on_settings()
        elif action == "close_settings":
            if self._settings_window is not None and self._settings_window.isVisible():
                print("[DriveSafe] → Closing settings...")
                self._settings_window.close()
            else:
                print("[DriveSafe] → Settings is not open.")
        elif action == "apply_settings":
            if self._settings_window is not None and self._settings_window.isVisible():
                print("[DriveSafe] → Applying settings...")
                self._settings_window.apply_settings()
            else:
                print("[DriveSafe] → Open settings first, then say 'apply settings'.")
        elif action == "start_recording":
            print(f"[DriveSafe] → Starting recording...")
            if not self._rec_action.isChecked():
                self._rec_action.setChecked(True)
                self._on_record()
        elif action == "stop_recording":
            print(f"[DriveSafe] → Stopping recording...")
            if self._rec_action.isChecked():
                self._rec_action.setChecked(False)
                self._on_record()
        elif action in ("mute_alerts", "unmute_alerts"):
            enabled = action == "unmute_alerts"
            print(f"[DriveSafe] → {'Unmuting' if enabled else 'Muting'} alerts...")
            self._thread.request_set_alerts_enabled(enabled)
        elif action in ("set_voice_male", "set_voice_female"):
            if self._settings_window is not None and self._settings_window.isVisible():
                target = "Male" if action == "set_voice_male" else "Female"
                if self._settings_window.select_voice_by_label(target):
                    model_path = self._settings_window.selected_voice_model()
                    if model_path:
                        self._on_settings_changed({"voice_model": model_path})
                        print(f"[DriveSafe] → Voice set to {target} (via settings)")
                else:
                    print(f"[DriveSafe] → Could not find '{target}' voice option in settings")
            else:
                print("[DriveSafe] → Open settings first, then say 'male voice' or 'female voice'.")

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
            self._on_settings()
        
    def _toggle_fullscreen(self) -> None:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()

    def changeEvent(self, event) -> None:
            super().changeEvent(event)
            from PyQt5.QtCore import QEvent
            if event.type() == QEvent.WindowStateChange:
                self._status_bar.setVisible(True)
    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._thread.stop()
        event.accept()
