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
