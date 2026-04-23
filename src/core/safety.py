"""
safety.py – Three-Level Safety Assessment

Classifies each detection into SAFE, WARNING, or DANGER
based on its estimated distance and class-specific thresholds.

Pedestrian:  DANGER < 2.5m,  WARNING < 5.0m,  SAFE >= 5.0m
Crosswalk:   DANGER < 5.0m,  WARNING < 8.0m,  SAFE >= 8.0m
"""

from enum import IntEnum

# BGR colours (OpenCV convention)
COLORS = {
    0: (0, 200, 0),      # SAFE   → green
    1: (0, 200, 255),    # WARNING → amber
    2: (0, 0, 230),      # DANGER  → red
}

LABELS = {0: "SAFE", 1: "WARNING", 2: "DANGER"}


class SafetyLevel(IntEnum):
    """Ordered so max() gives the worst state."""
    SAFE = 0
    WARNING = 1
    DANGER = 2


class SafetyAssessor:
    """Maps (class_name, distance) → SafetyLevel."""

    def __init__(self, thresholds=None):
        # thresholds: {class_name: (danger_m, warning_m)}
        self.thresholds = thresholds or {
            "pedestrian": (2.5, 5.0),
            "crosswalk":  (5.0, 8.0),
        }

    def assess(self, cls_name, distance):
        """Classify a single detection's safety level."""
        danger_m, warning_m = self.thresholds.get(cls_name, (2.5, 5.0))
        if distance < danger_m:
            return SafetyLevel.DANGER
        if distance < warning_m:
            return SafetyLevel.WARNING
        return SafetyLevel.SAFE

    @staticmethod
    def worst(levels):
        """Return the worst level from a list (for overall status)."""
        return SafetyLevel(max(levels)) if levels else SafetyLevel.SAFE

    @staticmethod
    def color(level):
        """BGR colour tuple for a safety level."""
        return COLORS[level]

    @staticmethod
    def label(level):
        """Text label for a safety level."""
        return LABELS[level]


def is_in_path(bbox, frame_width: int, zone_fraction: float = 0.40) -> bool:
    """
    Returns True when the object's bounding-box horizontal centre lies inside
    the central *zone_fraction* of the frame – i.e. directly in the car's path.

    zone_fraction=0.40 means the middle 40 % of the frame width is the
    "danger lane"; objects outside it are beside the road, not ahead.
    """
    cx = (bbox[0] + bbox[2]) / 2
    margin = frame_width * (1.0 - zone_fraction) / 2
    return margin <= cx <= (frame_width - margin)


def is_in_corridor(
    bbox,
    frame_width: int,
    corridor_norm: tuple[float, float] | None,
    fallback_zone_fraction: float = 0.40,
    lane_lines_norm: tuple[tuple[float, float, float, float], tuple[float, float, float, float]] | None = None,
    frame_height: int | None = None,
) -> bool:
    """
    Returns True if the bbox center lies inside the dynamic lane corridor.

    corridor_norm is (left_norm, right_norm) in [0, 1]. If corridor_norm is
    unavailable/invalid, falls back to the fixed central zone_fraction check.

    When lane_lines_norm is available, the check follows lane shape by
    evaluating lane boundaries at the pedestrian's vertical position.
    """
    if lane_lines_norm is not None and frame_height and frame_height > 0:
        lane_bounds = _lane_bounds_at_bbox_y(bbox, lane_lines_norm, frame_width, frame_height)
        if lane_bounds is not None:
            left_x, right_x = lane_bounds
            cx = (bbox[0] + bbox[2]) / 2
            return left_x <= cx <= right_x

    if corridor_norm is None:
        return is_in_path(bbox, frame_width, fallback_zone_fraction)

    left_norm, right_norm = corridor_norm
    left_norm = max(0.0, min(1.0, float(left_norm)))
    right_norm = max(0.0, min(1.0, float(right_norm)))
    if right_norm <= left_norm:
        return is_in_path(bbox, frame_width, fallback_zone_fraction)

    cx = (bbox[0] + bbox[2]) / 2
    left_x = left_norm * frame_width
    right_x = right_norm * frame_width
    return left_x <= cx <= right_x


def _lane_bounds_at_bbox_y(
    bbox,
    lane_lines_norm: tuple[tuple[float, float, float, float], tuple[float, float, float, float]],
    frame_width: int,
    frame_height: int,
) -> tuple[float, float] | None:
    """Return (left_x, right_x) lane bounds at bbox bottom-center y, or None."""
    left_line, right_line = lane_lines_norm
    y_norm = max(0.0, min(1.0, float(bbox[3]) / max(frame_height - 1, 1)))

    left_x_norm = _line_x_at_y_norm(left_line, y_norm)
    right_x_norm = _line_x_at_y_norm(right_line, y_norm)
    if left_x_norm is None or right_x_norm is None:
        return None
    if right_x_norm <= left_x_norm:
        return None

    return left_x_norm * frame_width, right_x_norm * frame_width


def _line_x_at_y_norm(line: tuple[float, float, float, float], y_norm: float) -> float | None:
    """Interpolate x on line (x1,y1,x2,y2) for y_norm, with segment clamping."""
    x1, y1, x2, y2 = line
    y_min, y_max = (y1, y2) if y1 <= y2 else (y2, y1)
    y = min(max(y_norm, y_min), y_max)

    dy = y2 - y1
    if abs(dy) < 1e-6:
        return max(0.0, min(1.0, float(x1)))

    t = (y - y1) / dy
    x = x1 + t * (x2 - x1)
    return max(0.0, min(1.0, float(x)))
