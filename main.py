"""
main.py – DriveSafe Entry Point

Runs the full pipeline each frame:
    capture → detect → estimate distance → assess safety → draw → display

Keyboard:
    I      Toggle info panel
    Q/ESC  Quit
"""

import sys
import time
import threading

import cv2
import yaml

from core.alerts import AlertManager
from core.detector import Detector
from core.distance import DistanceEstimator
from core.safety import COLORS, SafetyAssessor, SafetyLevel, is_in_path
from ui.display import draw_hud, draw_info_panel


def load_config(path="config.yaml"):
    """Load YAML config file. Returns a plain dict."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def open_camera(cfg):
    """Open USB camera with MJPG + forced resolution/FPS for max FPS."""
    cam = cfg["camera"]
    source = cam["source"]
    w = cam.get("width", 1280)
    h = cam.get("height", 720)
    fps = cam.get("framerate", 30)

    cap = cv2.VideoCapture(source, cv2.CAP_V4L2)

    if not cap.isOpened():
        print(f"[ERROR] Cannot open camera (source={source})")
        sys.exit(1)

    # Force MJPG to improve FPS
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    cap.set(cv2.CAP_PROP_FPS,         fps)

    actual_w  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"[DriveSafe] Camera opened: {actual_w}x{actual_h} @ {actual_fps:.0f} FPS (MJPG)")

    return cap



class VideoCaptureAsync:
    """Threaded VideoCapture to avoid blocking the main loop."""
    def __init__(self, cap):
        self.cap = cap
        self.grabbed, self.frame = self.cap.read()
        self.lock = threading.Lock()
        self.running = False

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self.update, daemon=True)
        self.thread.start()
        return self

    def update(self):
        while self.running:
            grabbed, frame = self.cap.read()
            with self.lock:
                self.grabbed, self.frame = grabbed, frame

    def read(self):
        with self.lock:
            return self.grabbed, self.frame.copy() if self.frame is not None else None

    def release(self):
        self.running = False
        self.thread.join()
        self.cap.release()


def main():
    # ── Load config ───────────────────────────────────────────────
    cfg = load_config()

    # ── Open camera ───────────────────────────────────────────────
    cap = open_camera(cfg)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

    if not cap.isOpened():
        print(f"[ERROR] Cannot open camera (source={cfg['camera']['source']})")
        sys.exit(1)

    # Wrap in threaded capture
    cap = VideoCaptureAsync(cap).start()

    fw = int(cap.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh = int(cap.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps_video = cap.cap.get(cv2.CAP_PROP_FPS) or 25.0

    cv2.namedWindow("DriveSafe", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("DriveSafe", min(fw, 1280), min(fh, 720))

    # ── Initialise modules ────────────────────────────────────────
    print("[DriveSafe] Loading model...")
    detector = Detector(
        weights=cfg["model"]["weights"],
        confidence=cfg["model"]["confidence"],
        iou=cfg["model"]["iou"],
        imgsz=cfg["model"].get("imgsz", 640),
        device=str(cfg["model"].get("device", "0")),
        half=cfg["model"].get("half", True),
    )
    estimator = DistanceEstimator(
        focal_length=cfg["distance"]["focal_length"],
        person_height=cfg["distance"]["person_height"],
        crosswalk_a=cfg["distance"].get("crosswalk_a", -0.015),
        crosswalk_b=cfg["distance"].get("crosswalk_b", 15.0),
    )
    assessor = SafetyAssessor({
        "pedestrian": (cfg["safety"]["pedestrian"]["danger"],
                       cfg["safety"]["pedestrian"]["warning"]),
        "crosswalk":  (cfg["safety"]["crosswalk"]["danger"],
                       cfg["safety"]["crosswalk"]["warning"]),
    })

    # ── Alert manager ─────────────────────────────────────────────
    alert_cfg  = cfg.get("alerts", {})
    alert_mgr  = AlertManager(
        enabled    = alert_cfg.get("enabled", True),
        voice_rate = alert_cfg.get("voice_rate", 160),
        cooldowns  = {
            "danger":    alert_cfg.get("danger_cooldown",    2.5),
            "warning":   alert_cfg.get("warning_cooldown",   5.0),
            "crosswalk": alert_cfg.get("crosswalk_cooldown", 7.0),
        },
    )
    path_zone = alert_cfg.get("path_zone", 0.40)

    # ── Open main loop ────────────────────────────────────────────
    source = cfg["camera"]["source"]
    print(f"[DriveSafe] {source} ({fw}x{fh} @ {fps_video:.0f} FPS)")

    # ── State ─────────────────────────────────────────────────────
    frame_id   = 0
    fps        = 0.0
    prev_time  = time.perf_counter()
    show_info  = False
    is_live    = isinstance(source, int) or cfg["camera"].get("use_gstreamer", False)

    print("[DriveSafe] Running – press Q to quit, I for info panel.")

    # ── Main loop ─────────────────────────────────────────────────
    while True:
        frame_start = time.perf_counter()
        ret, frame = cap.read()
        if not ret or frame is None:
            continue  # skip if no frame

        frame_id += 1

        # FPS calculation
        now = time.perf_counter()
        fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev_time, 1e-9))
        prev_time = now

      
        # Detect + track
        detections = detector.track(frame)

        # ── Determine alert state ─────────────────────────────────
        frame_h, frame_w = frame.shape[:2]
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

        # Pedestrian-in-path alerts
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

        # Crosswalk alerts
        if cw_worst is not None and cw_worst >= SafetyLevel.WARNING:
            alert_mgr.fire("crosswalk", "Crosswalk ahead, be careful", level="crosswalk")
            if alert_text is None:
                alert_text  = "CROSSWALK AHEAD  —  BE CAREFUL"
                alert_color = COLORS[SafetyLevel.WARNING]

        ms_id = (time.perf_counter() - frame_start) * 1000.0

        # ── Draw HUD ─────────────────────────────────────────────
        draw_hud(frame, detections, assessor, estimator, fps, ms_id,
                 path_zone=path_zone, alert_text=alert_text, alert_color=alert_color)

        if show_info:
            draw_info_panel(frame, cfg, fps)

        cv2.imshow("DriveSafe", frame)

        # Keyboard
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):  # Q or ESC
            break
        elif key == ord("i"):
            show_info = not show_info
        elif key == ord("m"):
            alert_mgr.enabled = not alert_mgr.enabled
            state = "ON" if alert_mgr.enabled else "OFF"
            print(f"[DriveSafe] Audio alerts {state}")

    cap.release()
    cv2.destroyAllWindows()
    print("[DriveSafe] Done.")


if __name__ == "__main__":
    main()