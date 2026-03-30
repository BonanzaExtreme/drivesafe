"""
detector.py – YOLOv9 + ByteTrack Object Detection & Tracking

Wraps Ultralytics YOLO into a simple track() method.
One call does: inference → NMS → ByteTrack ID assignment.
Returns a list of Detection tuples the rest of the app consumes.
"""

import warnings
from collections import namedtuple

import torch

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Failed to load image Python extension")
    from ultralytics import YOLO

def _torch_nms(boxes, scores, iou_threshold):
    """Pure-PyTorch NMS – drop-in replacement for torchvision.ops.nms."""
    return torch.ops.torchvision.nms(boxes, scores, iou_threshold) \
        if hasattr(torch.ops, 'torchvision') and hasattr(torch.ops.torchvision, 'nms') \
        else _pytorch_nms(boxes, scores, iou_threshold)

def _pytorch_nms(boxes, scores, iou_threshold):
    """Fallback NMS implementation using only torch operations."""
    if boxes.numel() == 0:
        return torch.empty((0,), dtype=torch.long, device=boxes.device)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort(descending=True)
    keep = []
    while order.numel() > 0:
        i = order[0].item()
        keep.append(i)
        if order.numel() == 1:
            break
        rest = order[1:]
        xx1 = x1[rest].clamp(min=x1[i].item())
        yy1 = y1[rest].clamp(min=y1[i].item())
        xx2 = x2[rest].clamp(max=x2[i].item())
        yy2 = y2[rest].clamp(max=y2[i].item())
        inter = (xx2 - xx1).clamp(min=0) * (yy2 - yy1).clamp(min=0)
        iou = inter / (areas[i] + areas[rest] - inter)
        order = rest[iou <= iou_threshold]
    return torch.tensor(keep, dtype=torch.long, device=boxes.device)

try:
    import torchvision.ops as _tv_ops
    _tv_ops.nms = _torch_nms
    # Also patch the internal box reference used by ultralytics
    import torchvision.ops.boxes as _tv_boxes
    _tv_boxes.nms = _torch_nms
except Exception:
    pass
# ─────────────────────────────────────────────────────────────────────────────

# Each detected object in a frame
Detection = namedtuple("Detection", [
    "track_id",    # int  – persistent tracker ID (-1 if unassigned)
    "cls_id",      # int  – class index (0=crosswalk, 1=pedestrian)
    "cls_name",    # str  – human-readable class name
    "bbox",        # tuple – (x1, y1, x2, y2) pixel coordinates
    "confidence",  # float – detection confidence 0..1
])

CLASS_NAMES = {0: "crosswalk", 1: "pedestrian"}


class Detector:
    """Loads a YOLO model and runs detection + tracking per frame."""

    def __init__(self, weights, confidence=0.35, iou=0.7, imgsz=640,
                 device="cpu", half=False):
        self.model = YOLO(weights, task="detect")
        self.conf = confidence
        self.iou = iou
        self.imgsz = imgsz
        # Auto-fall-back: if requested GPU but CUDA not available, use CPU
        if device != "cpu" and not torch.cuda.is_available():
            print("[DriveSafe] CUDA not available – falling back to CPU")
            device = "cpu"
        if half and device == "cpu":
            print("[DriveSafe] FP16 not supported on CPU – disabling half")
            half = False
        self.device = device
        self.half = half

        # ✅ NEW: print device info
        if self.device != "cpu":
            print(f"[DriveSafe] Using GPU: {torch.cuda.get_device_name(0)}")
        else:
            print("[DriveSafe] Using CPU")

    def track(self, frame):
        """Run detection + ByteTrack on a single frame.

        Returns list[Detection] – may be empty if nothing found.
        """
        results = self.model.track(
            source=frame,
            imgsz=self.imgsz,
            persist=True,                # keep tracker state across calls
            tracker="bytetrack.yaml",    # use ByteTrack algorithm
            conf=self.conf,
            iou=self.iou,
            classes=[0, 1],              # only our two classes
            verbose=False,
            device=self.device,          # use GPU on Jetson Nano
            half=self.half,              # FP16 – 2-3x faster on Jetson Nano
        )

        detections = []
        if not results or results[0].boxes is None:
            return detections

        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            track_id = int(box.id[0]) if box.id is not None else -1
            x1, y1, x2, y2 = box.xyxy[0].tolist()

            detections.append(Detection(
                track_id=track_id,
                cls_id=cls_id,
                cls_name=CLASS_NAMES.get(cls_id, "unknown"),
                bbox=(x1, y1, x2, y2),
                confidence=float(box.conf[0]),
            ))

        return detections
