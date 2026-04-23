"""
display.py – All Drawing & Rendering

Single file that handles everything displayed on screen:  - Startup screen with project info  - Detection bounding boxes with corner accents
  - Distance labels on each detection
  - Top status bar (FPS + detection counts)
  - Bottom safety bar (overall safety colour strip + label)
  - Info panel toggle (press I) showing shortcuts + system info
"""

import datetime
from typing import Optional, Tuple

import cv2
import numpy as np
from ..core.safety import SafetyLevel, is_in_corridor

# OpenCV drawing APIs expect a cv2 font face constant (not Tkinter fonts).
FONT = cv2.FONT_HERSHEY_SIMPLEX

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


# ── Path Zone & Alert Banner (private helpers) ──────────────────

def _draw_path_zone(
    frame,
    zone_fraction: float,
    top_offset: int,
    corridor: Optional[Tuple[float, float]] = None,
    lane_lines: Optional[Tuple[Tuple[float, float, float, float], Tuple[float, float, float, float]]] = None,
) -> None:
    """Draw a tapered lane sketch, or fixed fallback guide lines."""
    h, w = frame.shape[:2]
    if corridor is not None and corridor[1] > corridor[0]:
        left_x = int(max(0.0, min(1.0, corridor[0])) * w)
        right_x = int(max(0.0, min(1.0, corridor[1])) * w)
        xs = (left_x, right_x)
        color = (80, 220, 220)  # cyan-ish for dynamic mode

        if lane_lines is not None:
            polygon_pts = []
            for x1n, y1n, x2n, y2n in lane_lines:
                x1 = int(max(0.0, min(1.0, x1n)) * w)
                y1 = int(max(0.0, min(1.0, y1n)) * h)
                x2 = int(max(0.0, min(1.0, x2n)) * w)
                y2 = int(max(0.0, min(1.0, y2n)) * h)
                polygon_pts.append((x1, y1))
                polygon_pts.append((x2, y2))

            if len(polygon_pts) >= 4:
                # Build a tapered quadrilateral from the fitted side lines.
                left_line = lane_lines[0]
                right_line = lane_lines[1]
                lbx = int(max(0.0, min(1.0, left_line[0])) * w)
                lby = int(max(0.0, min(1.0, left_line[1])) * h)
                ltx = int(max(0.0, min(1.0, left_line[2])) * w)
                lty = int(max(0.0, min(1.0, left_line[3])) * h)
                rbx = int(max(0.0, min(1.0, right_line[0])) * w)
                rby = int(max(0.0, min(1.0, right_line[1])) * h)
                rtx = int(max(0.0, min(1.0, right_line[2])) * w)
                rty = int(max(0.0, min(1.0, right_line[3])) * h)
                quad = np.array([
                    [lbx, lby],
                    [ltx, lty],
                    [rtx, rty],
                    [rbx, rby],
                ], dtype=np.int32)
                cv2.polylines(frame, [quad], True, (0, 120, 120), 6, cv2.LINE_AA)
                cv2.polylines(frame, [quad], True, (0, 255, 255), 2, cv2.LINE_AA)
    else:
        margin = int(w * (1.0 - zone_fraction) / 2)
        xs = (margin, w - margin)
        color = (160, 160, 100)  # muted yellow-white fallback

    dash, gap = 14, 8
    for x in xs:
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
             corridor: Optional[Tuple[float, float]] = None,
             lane_lines: Optional[Tuple[Tuple[float, float, float, float], Tuple[float, float, float, float]]] = None,
             info_text: str | None = None,
             alert_text: str | None = None,
             alert_color=None,
             speed_kmh: float | None = None):
    """
    Draw the complete heads-up display on the video frame.

    path_zone   – fallback fraction of frame width for fixed travel path lines.
    corridor    – dynamic lane corridor as (left_norm, right_norm) in [0, 1].
    lane_lines  – optional left/right lane boundary lines for visual sketch.
    info_text   – non-critical informational banner (shown when no alert banner).
    alert_text  – when set, shows a bold warning banner below the top bar.
    alert_color – BGR colour for the banner (defaults to WARNING amber).
    speed_kmh   – current GPS ground speed in km/h, or None when unavailable.

    Returns the overall SafetyLevel for this frame.
    """
    h, w = frame.shape[:2]
    sf      = max(w / 1280.0, 0.5)
    bar_top = int(44 * sf)
    ts      = 0.65 * sf

    # ── Path zone guide lines ─────────────────────────────────────
    _draw_path_zone(frame, path_zone, bar_top, corridor=corridor, lane_lines=lane_lines)

    levels     = []
    n_in_path  = 0

    # ── Draw each detection ───────────────────────────────────────
    for det in detections:
        dist  = estimator.estimate(det.cls_name, det.bbox)
        level = assessor.assess(det.cls_name, dist)
        levels.append(level)
        color = assessor.color(level)
        x1, y1, x2, y2 = map(int, det.bbox)

        in_path = (
            det.cls_name == "pedestrian"
            and is_in_corridor(
                det.bbox,
                w,
                corridor,
                path_zone,
                lane_lines_norm=lane_lines,
                frame_height=h,
            )
        )
        if in_path:
            n_in_path += 1

        # Corner-style bounding box – slightly thicker when in path
        t = max(2, int(3 * sf)) + (1 if in_path else 0)
        draw_corners(frame, x1, y1, x2, y2, color,
                     t=t, length=max(int(22 * sf), 10))

        # Label: "PED #4  6.2m  !" (! = in-path pedestrian)
        # Don't show label for crosswalks
        if det.cls_name != "crosswalk":
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
    elif info_text:
        _draw_alert_banner(frame, info_text, (180, 180, 180), bar_top, sf)

    # ── Top status bar (clock + detection counts) ──────────────────
    draw_panel(frame, 0, 0, w, bar_top)
    ty  = int(bar_top * 0.76)
    pad = int(12 * sf)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d   %H:%M:%S")
    put_text(frame, now_str, (pad, ty), scale=ts, color=GRAY, thickness=2)

    # ── Speed readout (GPS) – centred in the top bar ──────────────
    # if speed_kmh is not None:
    #      spd_text = f"{speed_kmh:.0f} km/h"
    #      spd_col  = (100, 220, 100)   # muted green when normal
    #      if speed_kmh > 50:
    #          spd_col = (0, 200, 255)  # amber above 50 km/h
    #      if speed_kmh > 100:
    #          spd_col = (0, 80, 230)   # red above 100 km/h
    # else:
    #     spd_text = "-- km/h"
    #     spd_col  = (100, 100, 100)
    # (spd_w, _), _ = cv2.getTextSize(spd_text, FONT, ts, 2)
    # spd_x = (w - spd_w) // 2
    # put_text(frame, spd_text, (spd_x, ty), scale=ts, color=spd_col, thickness=2)

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
    put_text(frame, "Developed by: TIPQC DriveSafe",
             (x0 + pad, y0 + ph - int(14 * sf)), scale=ts, color=(120, 120, 120), thickness=2)
