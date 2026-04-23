"""
roadcorridor.py - Lightweight dynamic drivable corridor estimation.

Uses classical CV (Canny + Hough lines) to estimate left/right lane boundaries
from the lower road region. When no reliable lane pair is found, callers should
fall back to the fixed center path-zone logic.
"""

from __future__ import annotations

import cv2
import numpy as np


class LaneCorridorEstimator:
    """Estimate a normalized drivable corridor (left_x, right_x) from each frame."""

    def __init__(
        self,
        update_every_frames: int = 5,
        ema_alpha: float = 0.30,
        roi_top_fraction: float = 0.55,
        min_width_fraction: float = 0.20,
        max_width_fraction: float = 0.95,
        max_missed_updates: int = 8,
        temporal_alpha: float = 0.18,
    ) -> None:
        self.update_every_frames = max(1, int(update_every_frames))
        self.ema_alpha = float(max(0.05, min(1.0, ema_alpha)))
        self.temporal_alpha = float(max(0.05, min(1.0, temporal_alpha)))
        self.roi_top_fraction = float(max(0.30, min(0.90, roi_top_fraction)))
        self.min_width_fraction = float(max(0.05, min(0.80, min_width_fraction)))
        self.max_width_fraction = float(max(self.min_width_fraction + 0.05, min(1.0, max_width_fraction)))
        self.max_missed_updates = max(0, int(max_missed_updates))

        self._frame_idx = 0
        self._corridor_norm: tuple[float, float] | None = None
        self._lane_lines_norm: tuple[tuple[float, float, float, float], tuple[float, float, float, float]] | None = None
        self._left_line_norm: tuple[float, float, float, float] | None = None
        self._right_line_norm: tuple[float, float, float, float] | None = None
        self._missed_updates = 0
        self._left_missed_updates = 0
        self._right_missed_updates = 0

    @property
    def lane_lines_norm(self):
        """Latest normalized lane boundary lines, or None when unavailable."""
        return self._lane_lines_norm

    def update(self, frame) -> tuple[tuple[float, float] | None, bool]:
        """
        Return (corridor_norm, dynamic_active).

        corridor_norm is (left_norm, right_norm), both in [0, 1].
        dynamic_active is True when a lane-derived corridor is available.
        """
        self._frame_idx += 1

        # Reuse the previous result between expensive updates.
        if self._frame_idx % self.update_every_frames != 0:
            return self._corridor_norm, self._corridor_norm is not None

        estimate = self._estimate_candidates(frame)
        if estimate is None:
            self._missed_updates += 1
            if self._corridor_norm is not None and self._missed_updates <= self.max_missed_updates:
                return self._corridor_norm, True
            self._corridor_norm = None
            self._lane_lines_norm = None
            self._left_line_norm = None
            self._right_line_norm = None
            return None, False

        self._missed_updates = 0
        left_candidate, right_candidate = estimate

        left_line = self._update_side_state("left", left_candidate)
        right_line = self._update_side_state("right", right_candidate)

        if left_line is None or right_line is None:
            if self._corridor_norm is not None and self._missed_updates <= self.max_missed_updates:
                return self._corridor_norm, True
            self._corridor_norm = None
            self._lane_lines_norm = None
            return None, False

        new_corridor = (left_line[0], right_line[0])
        if new_corridor[1] <= new_corridor[0]:
            return None, False

        if self._corridor_norm is None:
            self._corridor_norm = new_corridor
        else:
            prev_left, prev_right = self._corridor_norm
            new_left, new_right = new_corridor
            a = self.ema_alpha
            self._corridor_norm = (
                (1.0 - a) * prev_left + a * new_left,
                (1.0 - a) * prev_right + a * new_right,
            )

        self._lane_lines_norm = (left_line, right_line)

        return self._corridor_norm, True

    def _update_side_state(self, side: str, candidate):
        prev_line = self._left_line_norm if side == "left" else self._right_line_norm
        missed_attr = "_left_missed_updates" if side == "left" else "_right_missed_updates"
        missed_updates = getattr(self, missed_attr)

        if candidate is None:
            missed_updates += 1
            setattr(self, missed_attr, missed_updates)
            if prev_line is not None and missed_updates <= self.max_missed_updates:
                return prev_line
            if side == "left":
                self._left_line_norm = None
            else:
                self._right_line_norm = None
            return None

        setattr(self, missed_attr, 0)
        if prev_line is None:
            new_line = candidate
        else:
            new_line = self._smooth_line(prev_line, candidate)

        if side == "left":
            self._left_line_norm = new_line
        else:
            self._right_line_norm = new_line
        return new_line

    def _estimate_candidates(self, frame):
        h, w = frame.shape[:2]
        roi_top = int(h * self.roi_top_fraction)
        roi = frame[roi_top:h, :]

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 50, 150)

        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=35,
            minLineLength=max(30, w // 20),
            maxLineGap=max(24, w // 28),
        )
        if lines is None:
            return None

        left_pts = []
        right_pts = []
        center_x = w / 2.0

        for ln in lines[:, 0, :]:
            x1, y1, x2, y2 = map(float, ln)
            y1 += roi_top
            y2 += roi_top

            # Normalize segment orientation so (x1, y1) is always the lower point.
            if y1 < y2:
                x1, x2 = x2, x1
                y1, y2 = y2, y1

            dx = x2 - x1
            dy = y2 - y1
            if abs(dx) < 1e-6:
                continue

            slope = dy / dx
            if abs(slope) < 0.35:
                continue

            bottom_x = x1
            # After orientation normalization, left boundary should trend right as y decreases
            # and right boundary should trend left as y decreases.
            if bottom_x < center_x and dx > 0:
                left_pts.extend([(x1, y1), (x2, y2)])
            elif bottom_x > center_x and dx < 0:
                right_pts.extend([(x1, y1), (x2, y2)])

        left_line = self._fit_lane_line(left_pts, h, w, roi_top)
        right_line = self._fit_lane_line(right_pts, h, w, roi_top)

        if left_line is None and right_line is None:
            return None

        return left_line, right_line

    def _fit_lane_line(self, points, h: int, w: int, roi_top: int):
        if len(points) < 4:
            return None

        y_bottom = float(h - 1)
        y_top = float(roi_top)
        x_bottom = self._fit_x_at_y(points, y=y_bottom)
        x_top = self._fit_x_at_y(points, y=y_top)
        if None in (x_bottom, x_top):
            return None

        bottom_norm = max(0.0, min(1.0, x_bottom / max(w - 1, 1)))
        top_norm = max(0.0, min(1.0, x_top / max(w - 1, 1)))
        y_top_norm = max(0.0, min(1.0, y_top / max(h - 1, 1)))
        y_bottom_norm = 1.0

        return (bottom_norm, y_bottom_norm, top_norm, y_top_norm)

    def _smooth_line(
        self,
        prev_line: tuple[float, float, float, float],
        new_line: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float]:
        a = self.temporal_alpha
        return tuple((1.0 - a) * prev + a * new for prev, new in zip(prev_line, new_line))

    @staticmethod
    def _fit_x_at_y(points: list[tuple[float, float]], y: float) -> float | None:
        if len(points) < 2:
            return None
        xs = np.array([p[0] for p in points], dtype=np.float32)
        ys = np.array([p[1] for p in points], dtype=np.float32)

        # Fit x = m*y + b for improved stability on near-vertical lines.
        try:
            m, b = np.polyfit(ys, xs, 1)
        except Exception:
            return None
        return float(m * y + b)
