"""
distance.py – Monocular Distance Estimation

Two methods depending on object class:

Pedestrian (pinhole camera model):
    distance = (real_height × focal_length) / bbox_height_px

Crosswalk (linear ground-plane mapping):
    distance = a × y_bottom + b
    (objects lower in frame are closer)
"""


class DistanceEstimator:
    """Estimates distance to objects using bounding-box geometry."""

    def __init__(self, focal_length=615.0, person_height=1.7,
                 crosswalk_a=-0.015, crosswalk_b=15.0):
        self.focal_length = focal_length     # camera focal length (pixels)
        self.person_height = person_height   # average adult height (metres)
        self.crosswalk_a = crosswalk_a       # crosswalk linear slope
        self.crosswalk_b = crosswalk_b       # crosswalk linear intercept

    def estimate(self, cls_name, bbox):
        """Return estimated distance in metres."""
        x1, y1, x2, y2 = bbox

        if cls_name == "pedestrian":
            bbox_height = max(y2 - y1, 1.0)   # avoid division by zero
            return (self.person_height * self.focal_length) / bbox_height

        # Crosswalk – linear approximation based on vertical position
        y_bottom = y2
        return max(self.crosswalk_a * y_bottom + self.crosswalk_b, 0.5)
