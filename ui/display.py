"""
display.py – All Drawing & Rendering

Single file that handles everything displayed on screen:  - Startup screen with project info  - Detection bounding boxes with corner accents
  - Distance labels on each detection
  - Top status bar (FPS + detection counts)
  - Bottom safety bar (overall safety colour strip + label)
  - Info panel toggle (press I) showing shortcuts + system info
"""

import datetime

import cv2
import numpy as np


from core.safety import SafetyLevel, is_in_path

# Fonts (OpenCV built-ins only – no BOLD or ITALIC, they don't exist)
FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_SM = cv2.FONT_HERSHEY_DUPLEX

# Colours (BGR)
WHITE = (255, 255, 255)
GRAY = (200, 200, 200)
BLACK = (0, 0, 0)


# ── Helpers ───────────────────────────────────────────────────────

def put_text(frame, text, pos, scale=0.7, color=WHITE, thickness=2, bg=None):
    """Draw text at pos. If bg is set, draw a filled rectangle behind it."""
    (tw, th), baseline = cv2.getTextSize(text, FONT, scale, thickness)
    x, y = pos
    if bg is not None:
        pad = 8
        cv2.rectangle(frame, (x - pad, y - th - pad),
                       (x + tw + pad, y + baseline + pad), bg, cv2.FILLED)
    cv2.putText(frame, text, (x, y), FONT, scale, color, thickness, cv2.LINE_AA)


def draw_panel(frame, x1, y1, x2, y2, alpha=0.6):
    """Draw a semi-transparent black rectangle (in-place, no full copy)."""
    h, w = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    roi = frame[y1:y2, x1:x2]
    dark = np.zeros_like(roi)
    cv2.addWeighted(dark, alpha, roi, 1 - alpha, 0, dst=roi)


# ── Corner-Style Bounding Box ────────────────────────────────────

def draw_corners(frame, x1, y1, x2, y2, color, t=2, length=18):
    """Draw only the four corners of a rectangle (minimalist look)."""
    L = length
    cv2.line(frame, (x1, y1), (x1 + L, y1), color, t, cv2.LINE_AA)
    cv2.line(frame, (x1, y1), (x1, y1 + L), color, t, cv2.LINE_AA)
    cv2.line(frame, (x2, y1), (x2 - L, y1), color, t, cv2.LINE_AA)
    cv2.line(frame, (x2, y1), (x2, y1 + L), color, t, cv2.LINE_AA)
    cv2.line(frame, (x1, y2), (x1 + L, y2), color, t, cv2.LINE_AA)
    cv2.line(frame, (x1, y2), (x1, y2 - L), color, t, cv2.LINE_AA)
    cv2.line(frame, (x2, y2), (x2 - L, y2), color, t, cv2.LINE_AA)
    cv2.line(frame, (x2, y2), (x2, y2 - L), color, t, cv2.LINE_AA)


# ── Startup Screen ────────────────────────────────────────────────

def _center_text(frame, text, y, scale, thickness, color):
    """Draw text horizontally centered on the frame."""
    (tw, _), _ = cv2.getTextSize(text, FONT, scale, thickness)
    cx = frame.shape[1] // 2
    cv2.putText(frame, text, (cx - tw // 2, y), FONT, scale, color, thickness, cv2.LINE_AA)


def draw_startup_screen(frame):
    """Show project info, version, developers on startup."""
    h, w = frame.shape[:2]
    frame[:] = (25, 25, 25)  # dark background
    # Scale factor so layout adapts to any resolution
    sf = max(min(w / 1280.0, h / 720.0), 0.45)

    # Title
    _center_text(frame, "DriveSafe", h // 3,
                 scale=2.0 * sf, thickness=max(2, int(4 * sf)), color=WHITE)

    # Subtitle – always centered so it never goes off-screen
    _center_text(frame, "Pedestrian Detection & Distance Estimation System",
                 h // 3 + int(65 * sf), scale=0.65 * sf, thickness=2, color=GRAY)

    # Version
    _center_text(frame, "Version 2.0",
                 h // 3 + int(115 * sf), scale=0.6 * sf, thickness=2, color=(150, 150, 150))

    # Divider
    cx = w // 2
    cv2.line(frame, (cx - int(220 * sf), h // 2 - 10),
             (cx + int(220 * sf), h // 2 - 10), (100, 100, 100), 2)

    # About
    about = [
        "YOLOv9 + ByteTrack Object Detection",
        "Monocular Distance Estimation",
        "Real-time Safety Assessment",
    ]
    row_gap = int(36 * sf)
    for i, line in enumerate(about):
        _center_text(frame, line,
                     h // 2 + int(35 * sf) + i * row_gap,
                     scale=0.62 * sf, thickness=2, color=GRAY)

    # Developers
    _center_text(frame, "Developed by: Your Team Name",
                 h - int(80 * sf), scale=0.6 * sf, thickness=2, color=(130, 130, 130))

    # Instructions
    _center_text(frame, "Press ENTER to start",
                 h - int(40 * sf), scale=0.72 * sf, thickness=2, color=WHITE)


# ── Path Zone & Alert Banner (private helpers) ──────────────────

def _draw_path_zone(frame, zone_fraction: float, top_offset: int) -> None:
    """Dashed vertical guide lines showing the car's travel path zone."""
    h, w = frame.shape[:2]
    margin = int(w * (1.0 - zone_fraction) / 2)
    color  = (160, 160, 100)   # muted yellow-white – visible but not distracting
    dash, gap = 14, 8
    for x in (margin, w - margin):
        y = top_offset
        while y < h:
            cv2.line(frame, (x, y), (x, min(y + dash, h)), color, 1, cv2.LINE_AA)
            y += dash + gap


def _draw_alert_banner(frame, text: str, color, bar_top: int, sf: float) -> None:
    """Full-width banner strip drawn just below the top status bar."""
    h, w = frame.shape[:2]
    bh   = int(46 * sf)
    y0, y1 = bar_top, bar_top + bh

    # Semi-transparent dark background so video still shows through
    roi = frame[y0:y1, 0:w]
    dark = np.zeros_like(roi)
    cv2.addWeighted(dark, 0.55, roi, 0.45, 0, dst=roi)

    # Left colour accent stripe
    cv2.rectangle(frame, (0, y0), (max(int(6 * sf), 4), y1), color, cv2.FILLED)

    # Centred text with a thin black shadow for readability on any background
    scale = 0.82 * sf
    thick = max(2, int(2.5 * sf))
    (tw, th), _ = cv2.getTextSize(text, FONT, scale, thick)
    tx = (w - tw) // 2
    ty = y0 + (bh + th) // 2
    cv2.putText(frame, text, (tx + 1, ty + 1), FONT, scale, BLACK,  thick + 1, cv2.LINE_AA)
    cv2.putText(frame, text, (tx,     ty),     FONT, scale, color,  thick,     cv2.LINE_AA)


# ── Main HUD ─────────────────────────────────────────────────────

def draw_hud(frame, detections, assessor, estimator,
             path_zone: float = 0.40,
             alert_text: str | None = None,
             alert_color=None):
    """
    Draw the complete heads-up display on the video frame.

    path_zone   – fraction of frame width treated as the car's travel path.
    alert_text  – when set, shows a bold warning banner below the top bar.
    alert_color – BGR colour for the banner (defaults to WARNING amber).

    Returns the overall SafetyLevel for this frame.
    """
    h, w = frame.shape[:2]
    sf      = max(w / 1280.0, 0.5)
    bar_top = int(44 * sf)
    ts      = 0.65 * sf

    # ── Path zone guide lines ─────────────────────────────────────
    _draw_path_zone(frame, path_zone, bar_top)

    levels     = []
    n_in_path  = 0

    # ── Draw each detection ───────────────────────────────────────
    for det in detections:
        dist  = estimator.estimate(det.cls_name, det.bbox)
        level = assessor.assess(det.cls_name, dist)
        levels.append(level)
        color = assessor.color(level)
        x1, y1, x2, y2 = map(int, det.bbox)

        in_path = (det.cls_name == "pedestrian" and
                   is_in_path(det.bbox, w, path_zone))
        if in_path:
            n_in_path += 1

        # Corner-style bounding box – slightly thicker when in path
        t = max(2, int(3 * sf)) + (1 if in_path else 0)
        draw_corners(frame, x1, y1, x2, y2, color,
                     t=t, length=max(int(22 * sf), 10))

        # Label: "PED #4  6.2m  !" (! = in-path pedestrian)
        tag = det.cls_name[:3].upper()
        if det.track_id >= 0:
            tag += f" #{det.track_id}"
        tag += f"  {dist:.1f}m"
       
        put_text(frame, tag, (x1, max(y1 - int(10 * sf), bar_top + 5)),
                 scale=ts, color=WHITE, thickness=2, bg=color)
        if in_path:
            badge      = "IN PATH"
            b_scale    = 0.55 * sf
            b_thick    = max(1, int(2 * sf))
            (bw, bh), _ = cv2.getTextSize(badge, FONT, b_scale, b_thick)
            bx = x1 + max(int(6 * sf), 4)
            by = y2 - max(int(8 * sf), 6)
            pad_b = int(4 * sf)
            cv2.rectangle(frame,
                          (bx - pad_b, by - bh - pad_b),
                          (bx + bw + pad_b, by + pad_b),
                          color, cv2.FILLED)
            cv2.putText(frame, badge, (bx, by),
                        FONT, b_scale, WHITE, b_thick, cv2.LINE_AA)

    overall     = assessor.worst(levels)
    level_color = assessor.color(overall)
    level_label = assessor.label(overall)

    # ── Alert banner ──────────────────────────────────────────────
    if alert_text:
        _draw_alert_banner(frame, alert_text,
                           alert_color or (0, 200, 255), bar_top, sf)

    # ── Top status bar (clock + detection counts) ──────────────────
    draw_panel(frame, 0, 0, w, bar_top)
    ty  = int(bar_top * 0.76)
    pad = int(12 * sf)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d   %H:%M:%S")
    put_text(frame, now_str, (pad, ty), scale=ts, color=GRAY, thickness=2)

    n_ped = sum(1 for d in detections if d.cls_name == "pedestrian")
    n_cw  = sum(1 for d in detections if d.cls_name == "crosswalk")
    counts     = f"PED {n_ped}   CW {n_cw}"
    counts_col = (0, 80, 230) if n_in_path else GRAY
    (cw_px, _), _ = cv2.getTextSize(counts, FONT, ts, 2)
    put_text(frame, counts, (w - cw_px - pad, ty), scale=ts,
             color=counts_col, thickness=2)

    if n_in_path:
        ip_text = f"IN PATH: {n_in_path}"
        ip_col  = (0, 30, 200)
        (ip_w, _), _ = cv2.getTextSize(ip_text, FONT, ts, 2)
        # Position it to the left of the PED/CW count
        ip_x = w - cw_px - pad - ip_w - int(24 * sf)
        put_text(frame, ip_text, (ip_x, ty),
                 scale=ts, color=WHITE, thickness=2, bg=ip_col)
        
    return overall


# ── Info Panel (toggle with I key) ────────────────────────────────

def draw_info_panel(frame, cfg, fps):
    """Show a full-screen modal-style info panel."""
    h, w = frame.shape[:2]
    sf = max(w / 1280.0, 0.5)

    # Dim the entire background (modal effect) – in-place, no full copy
    dark = np.zeros_like(frame)
    cv2.addWeighted(dark, 0.75, frame, 0.25, 0, dst=frame)

    # Panel clamped to frame size so it never overflows
    pw = min(int(620 * sf), w - 20)
    ph = min(int(500 * sf), h - 20)
    x0 = (w - pw) // 2
    y0 = (h - ph) // 2

    ts  = 0.58 * sf   # body text scale
    ths = 0.62 * sf   # section header scale
    pad = int(20 * sf)
    row = int(28 * sf)

    # Panel background with border
    cv2.rectangle(frame, (x0, y0), (x0 + pw, y0 + ph), (40, 40, 40), cv2.FILLED)
    cv2.rectangle(frame, (x0, y0), (x0 + pw, y0 + ph), (100, 100, 100), 2)

    # Title bar
    title_h = int(52 * sf)
    cv2.rectangle(frame, (x0, y0), (x0 + pw, y0 + title_h), (50, 50, 50), cv2.FILLED)
    put_text(frame, "DriveSafe v2.0", (x0 + pad, y0 + int(38 * sf)),
             scale=0.85 * sf, color=WHITE, thickness=2)

    y_offset = y0 + title_h + int(18 * sf)

    # About section
    put_text(frame, "ABOUT", (x0 + pad, y_offset), scale=ths, color=(220, 220, 220), thickness=2)
    y_offset += row
    about = [
        "Pedestrian Detection & Distance Estimation",
        "System using YOLOv9 + ByteTrack Tracking",
    ]
    for line in about:
        put_text(frame, line, (x0 + pad, y_offset), scale=ts, color=GRAY, thickness=2)
        y_offset += row

    y_offset += int(8 * sf)
    cv2.line(frame, (x0 + pad, y_offset), (x0 + pw - pad, y_offset), (80, 80, 80), 1)
    y_offset += int(16 * sf)

    # System info
    put_text(frame, "SYSTEM", (x0 + pad, y_offset), scale=ths, color=(220, 220, 220), thickness=2)
    y_offset += row
    info_lines = [
        f"Model:       {cfg['model']['weights']}",
        f"Confidence:  {cfg['model']['confidence']}",
        f"Focal Len:   {cfg['distance']['focal_length']} px",
        f"Person H:    {cfg['distance']['person_height']} m",
        f"FPS:         {fps:.1f}",
    ]
    for line in info_lines:
        put_text(frame, line, (x0 + pad, y_offset), scale=ts, color=GRAY, thickness=2)
        y_offset += row

    y_offset += int(8 * sf)
    cv2.line(frame, (x0 + pad, y_offset), (x0 + pw - pad, y_offset), (80, 80, 80), 1)
    y_offset += int(16 * sf)

    # Controls
    put_text(frame, "CONTROLS", (x0 + pad, y_offset), scale=ths, color=(220, 220, 220), thickness=2)
    y_offset += row
    for line in [
        "I            Toggle this panel",
        "M            Mute / unmute alerts",
        "Q / ESC      Quit application",
    ]:
        put_text(frame, line, (x0 + pad, y_offset), scale=ts, color=GRAY, thickness=2)
        y_offset += row

    # Footer
    put_text(frame, "Developed by: Your Team Name",
             (x0 + pad, y0 + ph - int(14 * sf)), scale=ts, color=(120, 120, 120), thickness=2)
