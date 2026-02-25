# DriveSafe Code Documentation
## Complete Line-by-Line Explanation for Coding Defense

This document explains every file and every significant line of code in the DriveSafe system.

---

## Table of Contents
1. [main.py - Entry Point](#mainpy)
2. [config.yaml - Configuration](#configyaml)
3. [core/detector.py - Detection & Tracking](#coredetectorpy)
4. [core/distance.py - Distance Estimation](#coredistancepy)
5. [core/safety.py - Safety Assessment](#coresafetypy)
6. [ui/display.py - User Interface](#uidisplaypy)

---

## main.py
**Purpose:** Application entry point that orchestrates the entire system.

### Line-by-Line Explanation

```python
"""
main.py – DriveSafe Entry Point
...
"""
```
**Lines 1-10:** Docstring explaining what this file does.

```python
import sys
import time
```
**Lines 12-13:** 
- `sys` - for system operations like exit()
- `time` - for FPS calculation using perf_counter()

```python
import cv2
import numpy as np
import yaml
```
**Lines 15-17:**
- `cv2` - OpenCV library for video capture and display
- `numpy` - for creating arrays (used for startup screen)
- `yaml` - to parse the config.yaml file

```python
from core.detector import Detector
from core.distance import DistanceEstimator
from core.safety import SafetyAssessor
from ui.display import draw_hud, draw_info_panel, draw_startup_screen
```
**Lines 19-22:** Import our custom modules:
- `Detector` - handles YOLOv9 detection + ByteTrack tracking
- `DistanceEstimator` - calculates distance from bounding boxes
- `SafetyAssessor` - classifies detections as SAFE/WARNING/DANGER
- `draw_*` functions - all UI rendering functions

```python
def load_config(path="config.yaml"):
    """Load YAML config file. Returns a plain dict."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```
**Lines 25-28:** Function to load configuration:
- Opens the YAML file in read mode with UTF-8 encoding
- `yaml.safe_load()` parses YAML into a Python dictionary
- Returns the dict so we can access config values like `cfg["model"]["weights"]`

```python
def main():
```
**Line 31:** Main function - entry point of the program.

```python
    cfg = load_config()
```
**Line 33:** Load all settings from config.yaml into `cfg` dictionary.

```python
    source = cfg["camera"]["source"]
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open: {source}")
        sys.exit(1)
```
**Lines 36-40:**
- Get video source from config (file path or camera index)
- `VideoCapture()` opens the video source
- Check if it opened successfully, if not exit with error code 1

```python
    fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps_video = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.release()
```
**Lines 42-45:**
- Get video width (fw) and height (fh) in pixels
- Get video FPS (frames per second), default to 25 if not available
- Release the capture temporarily (we'll reopen after startup screen)

```python
    cv2.namedWindow("DriveSafe", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("DriveSafe", min(fw, 1280), min(fh, 720))
```
**Lines 48-49:**
- Create a resizable window named "DriveSafe"
- Resize to fit screen (max 1280x720) while maintaining aspect ratio

```python
    startup = np.zeros((fh, fw, 3), dtype=np.uint8)
    draw_startup_screen(startup)
    cv2.imshow("DriveSafe", startup)
```
**Lines 51-53:**
- Create blank black image (zeros) with video dimensions
- Draw startup screen graphics onto it
- Display it in the window

```python
    print("[DriveSafe] Press ENTER in the window to start...")
    
    while True:
        key = cv2.waitKey(50) & 0xFF
        if key == 13:  # ENTER
            break
        elif key in (ord("q"), 27):  # Q or ESC
            cv2.destroyAllWindows()
            sys.exit(0)
```
**Lines 55-62:**
- Wait for user to press ENTER to continue
- `waitKey(50)` checks keyboard every 50ms
- `& 0xFF` masks to get only the last 8 bits (standard practice)
- If ENTER (ASCII 13), break loop and continue
- If Q or ESC (ASCII 27), close window and exit

```python
    print("[DriveSafe] Loading model...")
    detector = Detector(
        weights=cfg["model"]["weights"],
        confidence=cfg["model"]["confidence"],
        iou=cfg["model"]["iou"],
    )
```
**Lines 65-70:** Initialize the detector:
- Create Detector object
- Pass model weights path from config
- Pass confidence threshold (minimum score to accept detection)
- Pass IoU threshold (for Non-Maximum Suppression)

```python
    estimator = DistanceEstimator(
        focal_length=cfg["distance"]["focal_length"],
        person_height=cfg["distance"]["person_height"],
    )
```
**Lines 71-74:** Initialize distance estimator:
- Pass camera focal length in pixels (calibrated value)
- Pass assumed pedestrian height in metres (1.7m)

```python
    assessor = SafetyAssessor({
        "pedestrian": (cfg["safety"]["pedestrian"]["danger"],
                       cfg["safety"]["pedestrian"]["warning"]),
        "crosswalk":  (cfg["safety"]["crosswalk"]["danger"],
                       cfg["safety"]["crosswalk"]["warning"]),
    })
```
**Lines 75-80:** Initialize safety assessor:
- Create dictionary mapping class names to threshold tuples
- Each tuple: (danger_threshold_metres, warning_threshold_metres)
- Example: pedestrian danger < 2.5m, warning < 5.0m

```python
    cap = cv2.VideoCapture(source)
    print(f"[DriveSafe] {source} ({fw}x{fh} @ {fps_video:.0f} FPS)")
```
**Lines 83-84:**
- Reopen the video capture after startup screen
- Print video info to console

```python
    frame_id = 0
    fps = 0.0
    prev_time = time.perf_counter()
    show_info = False
```
**Lines 87-90:** Initialize state variables:
- `frame_id` - counter for processed frames
- `fps` - calculated frames per second
- `prev_time` - timestamp for FPS calculation
- `show_info` - whether info panel is visible (toggled by I key)

```python
    print("[DriveSafe] Running – press Q to quit, I for info panel.")
```
**Line 92:** Instructions for user.

```python
    while True:
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue
```
**Lines 95-99:** Main loop:
- `cap.read()` reads next frame from video
- `ret` is True if successful, `frame` is the image
- If video ends, reset to frame 0 (loop video)
- `continue` skips to next iteration

```python
        frame_id += 1
```
**Line 101:** Increment frame counter.

```python
        now = time.perf_counter()
        fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev_time, 1e-9))
        prev_time = now
```
**Lines 104-106:** FPS calculation:
- `perf_counter()` gives high-precision time in seconds
- Calculate instantaneous FPS: 1 / time_since_last_frame
- Use exponential moving average (90% old, 10% new) for smooth value
- `max(..., 1e-9)` prevents division by zero

```python
        detections = detector.track(frame)
```
**Line 109:** Run detection + tracking:
- Pass current frame to detector
- Returns list of Detection objects with bounding boxes and IDs

```python
        draw_hud(frame, detections, assessor, estimator, fps, frame_id)
```
**Line 112:** Draw the heads-up display:
- Draws directly onto the frame (modifies in-place)
- Includes bounding boxes, labels, status bar, safety bar

```python
        if show_info:
            draw_info_panel(frame, cfg, fps)
```
**Lines 115-116:**
- If I key was pressed (show_info is True)
- Draw the info panel overlay on top

```python
        cv2.imshow("DriveSafe", frame)
```
**Line 119:** Display the frame in the window.

```python
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord("i"):
            show_info = not show_info
```
**Lines 122-126:** Keyboard handling:
- Check for key press every 1ms
- Q or ESC: break loop (exit program)
- I: toggle info panel on/off

```python
    cap.release()
    cv2.destroyAllWindows()
    print("[DriveSafe] Done.")
```
**Lines 129-131:** Cleanup:
- Release video capture resource
- Close all OpenCV windows
- Print exit message

```python
if __name__ == "__main__":
    main()
```
**Lines 134-135:**
- Only run main() if this file is executed directly
- Not run if imported as a module

---

## config.yaml
**Purpose:** Centralized configuration for all system parameters.

```yaml
camera:
  source: "Dashcam Footage - Front (Afternoon).mp4"
```
**Lines 3-4:** Video source - can be file path or camera index (0 for webcam).

```yaml
model:
  weights: "weights/last.pt"
  confidence: 0.35
  iou: 0.7
```
**Lines 6-9:** Model configuration:
- `weights` - path to trained YOLOv9 model file
- `confidence` - minimum score (0-1) to accept a detection
- `iou` - Intersection over Union threshold for NMS (removes overlapping boxes)

```yaml
distance:
  focal_length: 615.0
  person_height: 1.7
```
**Lines 11-13:** Distance estimation parameters:
- `focal_length` - camera focal length in pixels (calibrated)
- `person_height` - assumed average adult height in metres

```yaml
safety:
  pedestrian:
    danger: 2.5
    warning: 5.0
  crosswalk:
    danger: 5.0
    warning: 8.0
```
**Lines 15-21:** Safety thresholds in metres:
- `danger` - distance below this = red (DANGER)
- `warning` - distance below this = amber (WARNING), above = green (SAFE)
- Different thresholds for pedestrians vs crosswalks

---

## core/detector.py
**Purpose:** Wraps YOLOv9 model for detection and ByteTrack for multi-object tracking.

```python
from collections import namedtuple
from ultralytics import YOLO
```
**Lines 10-11:**
- `namedtuple` - creates lightweight immutable objects
- `YOLO` - Ultralytics YOLOv9 implementation

```python
Detection = namedtuple("Detection", [
    "track_id",
    "cls_id",
    "cls_name",
    "bbox",
    "confidence",
])
```
**Lines 14-20:** Define Detection data structure:
- Named tuple with 6 fields
- `track_id` - persistent ID across frames (-1 if untracked)
- `cls_id` - class index (0 or 1)
- `cls_name` - human-readable name ("pedestrian" or "crosswalk")
- `bbox` - tuple (x1, y1, x2, y2) in pixels
- `confidence` - detection score 0.0 to 1.0

```python
CLASS_NAMES = {0: "crosswalk", 1: "pedestrian"}
```
**Line 22:** Mapping from class ID to name.

```python
class Detector:
    """Loads a YOLO model and runs detection + tracking per frame."""

    def __init__(self, weights, confidence=0.35, iou=0.7):
        self.model = YOLO(weights)
        self.conf = confidence
        self.iou = iou
```
**Lines 25-31:** Detector class initialization:
- Load YOLOv9 model from weights file
- Store confidence and IoU thresholds as instance variables

```python
    def track(self, frame):
        """Run detection + ByteTrack on a single frame.

        Returns list[Detection] – may be empty if nothing found.
        """
```
**Lines 33-37:** Track method definition - main entry point.

```python
        results = self.model.track(
            source=frame,
            persist=True,
            tracker="bytetrack.yaml",
            conf=self.conf,
            iou=self.iou,
            classes=[0, 1],
            verbose=False,
        )
```
**Lines 38-46:** Call YOLO track method:
- `source=frame` - input image
- `persist=True` - keep tracker state between calls (essential for tracking)
- `tracker="bytetrack.yaml"` - use ByteTrack algorithm
- `conf=self.conf` - confidence threshold
- `iou=self.iou` - NMS threshold
- `classes=[0, 1]` - only detect our two classes
- `verbose=False` - don't print to console

```python
        detections = []
        if not results or results[0].boxes is None:
            return detections
```
**Lines 48-50:**
- Initialize empty list
- Check if results exist and have boxes
- Return empty list if nothing detected

```python
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            track_id = int(box.id[0]) if box.id is not None else -1
            x1, y1, x2, y2 = box.xyxy[0].tolist()
```
**Lines 52-55:** Loop through each detection:
- Extract class ID (convert tensor to int)
- Extract track ID if available, otherwise -1
- Extract bounding box coordinates (top-left, bottom-right)

```python
            detections.append(Detection(
                track_id=track_id,
                cls_id=cls_id,
                cls_name=CLASS_NAMES.get(cls_id, "unknown"),
                bbox=(x1, y1, x2, y2),
                confidence=float(box.conf[0]),
            ))
```
**Lines 57-63:** Create Detection object:
- Use named tuple constructor
- Look up class name from ID
- Convert confidence tensor to float
- Append to list

```python
        return detections
```
**Line 65:** Return list of all detections in this frame.

---

## core/distance.py
**Purpose:** Estimates distance to detected objects using monocular vision.

```python
class DistanceEstimator:
    """Estimates distance to objects using bounding-box geometry."""

    def __init__(self, focal_length=615.0, person_height=1.7):
        self.focal_length = focal_length
        self.person_height = person_height
```
**Lines 17-22:** Initialization:
- Store camera focal length (pixels)
- Store assumed person height (metres)

```python
    def estimate(self, cls_name, bbox):
        """Return estimated distance in metres."""
        x1, y1, x2, y2 = bbox
```
**Lines 24-26:** Main estimation method:
- Takes class name and bounding box
- Unpack bbox coordinates

```python
        if cls_name == "pedestrian":
            bbox_height = max(y2 - y1, 1.0)
            return (self.person_height * self.focal_length) / bbox_height
```
**Lines 28-30:** Pedestrian distance (pinhole camera model):
- Calculate bbox height in pixels
- `max(..., 1.0)` prevents division by zero
- **Formula:** distance = (real_height × focal_length) / pixel_height
- Larger bbox = closer person, smaller bbox = farther person

```python
        y_bottom = y2
        return max(-0.015 * y_bottom + 15.0, 0.5)
```
**Lines 33-34:** Crosswalk distance (linear ground-plane):
- Use bottom edge Y coordinate
- **Formula:** distance = a × y + b (linear approximation)
- Objects lower in frame are closer
- `max(..., 0.5)` prevents negative distances

---

## core/safety.py
**Purpose:** Classifies detections into three safety levels based on distance.

```python
from enum import IntEnum
```
**Line 10:** Import IntEnum for ordered enumeration.

```python
COLORS = {
    0: (0, 200, 0),
    1: (0, 200, 255),
    2: (0, 0, 230),
}

LABELS = {0: "SAFE", 1: "WARNING", 2: "DANGER"}
```
**Lines 13-20:** Hardcoded mappings:
- BGR colors for OpenCV (blue, green, red channels)
- 0=SAFE (green), 1=WARNING (amber), 2=DANGER (red)
- Text labels for display

```python
class SafetyLevel(IntEnum):
    """Ordered so that max() returns the worst state."""
    SAFE = 0
    WARNING = 1
    DANGER = 2
```
**Lines 23-27:** Safety level enumeration:
- IntEnum allows numeric comparison
- Ordered from best to worst
- `max([SAFE, DANGER])` returns `DANGER`

```python
class SafetyAssessor:
    """Maps (class_name, distance) → SafetyLevel."""

    def __init__(self, thresholds=None):
        self.thresholds = thresholds or {
            "pedestrian": (2.5, 5.0),
            "crosswalk":  (5.0, 8.0),
        }
```
**Lines 30-37:** Initialization:
- Accept thresholds dictionary or use defaults
- Each tuple: (danger_threshold, warning_threshold)
- Example: pedestrian DANGER if < 2.5m, WARNING if < 5.0m

```python
    def assess(self, cls_name, distance):
        """Classify a single detection's safety level."""
        danger_m, warning_m = self.thresholds.get(cls_name, (2.5, 5.0))
        if distance < danger_m:
            return SafetyLevel.DANGER
        if distance < warning_m:
            return SafetyLevel.WARNING
        return SafetyLevel.SAFE
```
**Lines 39-46:** Assessment logic:
- Get thresholds for this class (default if unknown)
- If distance below danger threshold → DANGER
- Else if below warning threshold → WARNING
- Else → SAFE

```python
    @staticmethod
    def worst(levels):
        """Return the worst level from a list (for overall status)."""
        return SafetyLevel(max(levels)) if levels else SafetyLevel.SAFE
```
**Lines 48-51:** Find worst safety level:
- `@staticmethod` - doesn't need instance (no self)
- Use `max()` on list of levels (works because IntEnum)
- Return SAFE if list is empty

```python
    @staticmethod
    def color(level):
        """BGR colour tuple for a safety level."""
        return COLORS[level]

    @staticmethod
    def label(level):
        """Text label for a safety level."""
        return LABELS[level]
```
**Lines 53-60:** Helper methods:
- Look up color and label from dictionaries
- Static because they don't need instance data

---

## ui/display.py
**Purpose:** All drawing and rendering functions for the user interface.

### Helper Functions

```python
def put_text(frame, text, pos, scale=0.7, color=WHITE, thickness=2, bg=None):
    """Draw text at pos. If bg is set, draw a filled rectangle behind it."""
    (tw, th), baseline = cv2.getTextSize(text, FONT, scale, thickness)
    x, y = pos
    if bg is not None:
        pad = 8
        cv2.rectangle(frame, (x - pad, y - th - pad),
                       (x + tw + pad, y + baseline + pad), bg, cv2.FILLED)
    cv2.putText(frame, text, (x, y), FONT, scale, color, thickness, cv2.LINE_AA)
```
**Lines 24-33:** Text drawing helper:
- `getTextSize()` returns (width, height) and baseline
- If bg color provided, draw filled rectangle first
- `pad=8` adds 8px padding around text
- `LINE_AA` enables anti-aliasing for smooth text

```python
def draw_panel(frame, x1, y1, x2, y2, alpha=0.6):
    """Draw a semi-transparent black rectangle (in-place, no full copy)."""
    h, w = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    roi = frame[y1:y2, x1:x2]
    dark = np.zeros_like(roi)
    cv2.addWeighted(dark, alpha, roi, 1 - alpha, 0, dst=roi)
```
**Lines 36-43:** Semi-transparent panel:
- Clamp coordinates to frame bounds
- `roi` extracts region of interest (NumPy slice)
- `zeros_like()` creates black array same size as ROI
- `addWeighted()` blends black (alpha) with existing pixels (1-alpha)
- `dst=roi` writes result back to frame (in-place, efficient)

```python
def draw_corners(frame, x1, y1, x2, y2, color, t=2, length=18):
    """Draw only the four corners of a rectangle (minimalist look)."""
    L = length
    cv2.line(frame, (x1, y1), (x1 + L, y1), color, t, cv2.LINE_AA)
    cv2.line(frame, (x1, y1), (x1, y1 + L), color, t, cv2.LINE_AA)
    ...
```
**Lines 49-60:** Corner-only bounding box:
- Draw 8 lines (2 per corner)
- `t` is thickness, `L` is corner length
- Creates minimalist box that doesn't obscure video

### Startup Screen

```python
def draw_startup_screen(frame):
    """Show project info, version, developers on startup."""
    h, w = frame.shape[:2]
    frame[:] = (25, 25, 25)
```
**Lines 65-68:**
- Get frame dimensions
- Fill entire frame with dark gray `[:] =` modifies in-place

```python
    cx = w // 2
    put_text(frame, "DriveSafe", (cx - 170, h // 3),
             scale=2.0, color=WHITE, thickness=4)
```
**Lines 70-72:**
- Calculate center X
- Draw large title at 1/3 height
- `//` is integer division

*(Lines 74-99 continue drawing subtitle, version, about section, developers, instructions)*

### Main HUD

```python
def draw_hud(frame, detections, assessor, estimator, fps, frame_id):
    """Draw the complete heads-up display on the video frame.

    Returns the overall SafetyLevel for this frame.
    """
    h, w = frame.shape[:2]
    from core.safety import SafetyLevel

    levels = []
```
**Lines 108-116:**
- Function takes frame and all detection data
- Import SafetyLevel (inside function to avoid circular import)
- Initialize list to collect safety levels

```python
    for det in detections:
        dist = estimator.estimate(det.cls_name, det.bbox)
        level = assessor.assess(det.cls_name, dist)
        levels.append(level)
        color = assessor.color(level)
        x1, y1, x2, y2 = map(int, det.bbox)

        draw_corners(frame, x1, y1, x2, y2, color, t=3, length=22)

        tag = det.cls_name[:3].upper()
        if det.track_id >= 0:
            tag += f" #{det.track_id}"
        tag += f"  {dist:.1f}m"
        put_text(frame, tag, (x1, y1 - 12), scale=0.75, color=WHITE,
                 thickness=2, bg=color)
```
**Lines 119-133:** For each detection:
- Estimate distance using bbox geometry
- Assess safety level based on distance
- Get color for this level
- Convert bbox floats to integers
- Draw corner-style bounding box
- Build label: "PED #4  6.2m"
- `[:3]` gets first 3 chars of class name
- `.upper()` converts to uppercase
- `f"{dist:.1f}m"` formats to 1 decimal place

```python
    overall = assessor.worst(levels)
    level_color = assessor.color(overall)
    level_label = assessor.label(overall)
```
**Lines 135-137:**
- Find worst level among all detections
- Get color and label for overall status

```python
    draw_panel(frame, 0, 0, w, 50)
    put_text(frame, f"FPS {fps:.0f}", (15, 35), ...)
    ...
    n_ped = sum(1 for d in detections if d.cls_name == "pedestrian")
    n_cw = sum(1 for d in detections if d.cls_name == "crosswalk")
```
**Lines 140-148:**
- Draw semi-transparent top bar
- Show FPS and frame number
- Count pedestrians: `sum(1 for ...)` counts items matching condition
- Count crosswalks the same way

```python
    bar_h = 10
    cv2.rectangle(frame, (0, h - bar_h), (w, h), level_color, cv2.FILLED)
    put_text(frame, level_label, (w - 180, h - 28), ...)

    return overall
```
**Lines 151-156:**
- Draw colored safety bar at bottom (10px tall)
- `FILLED` fills the rectangle solid
- Show safety label in bottom-right
- Return overall level to caller

### Info Panel

```python
def draw_info_panel(frame, cfg, fps):
    """Show a full-screen modal-style info panel."""
    h, w = frame.shape[:2]
    
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), cv2.FILLED)
    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
```
**Lines 162-168:** Create modal effect:
- Make copy of frame
- Draw black rectangle on copy
- Blend 75% black with 25% original frame
- Result: darkened background (modal overlay effect)

```python
    pw, ph = 650, 580
    x0 = (w - pw) // 2
    y0 = (h - ph) // 2
```
**Lines 171-173:**
- Panel dimensions: 650x580 pixels
- Center horizontally: (width - panel_width) / 2
- Center vertically: (height - panel_height) / 2

```python
    cv2.rectangle(frame, (x0, y0), (x0 + pw, y0 + ph), (40, 40, 40), cv2.FILLED)
    cv2.rectangle(frame, (x0, y0), (x0 + pw, y0 + ph), (100, 100, 100), 3)
```
**Lines 176-177:**
- Draw dark gray filled rectangle (panel background)
- Draw lighter gray border (3px thick) on top

```python
    cv2.rectangle(frame, (x0, y0), (x0 + pw, y0 + 60), (50, 50, 50), cv2.FILLED)
    put_text(frame, "DriveSafe v2.0", (x0 + 25, y0 + 45), ...)
```
**Lines 180-182:**
- Draw title bar (60px tall)
- Show version in title bar

*(Lines 184-218 continue drawing About, System, Controls sections with proper spacing)*

---

## Summary

**Total Lines of Code:**
- main.py: 135 lines
- core/detector.py: 65 lines
- core/distance.py: 34 lines
- core/safety.py: 60 lines
- ui/display.py: 218 lines
- **Total: ~512 lines** (excluding blank lines and comments)

**Key Concepts to Remember:**

1. **Data Flow:** Frame → Detector → Distance → Safety → Display
2. **Pinhole Model:** distance = (real_height × focal_length) / pixel_height
3. **ByteTrack:** Assigns persistent IDs to objects across frames
4. **Safety Zones:** DANGER < 2.5m, WARNING < 5m, SAFE ≥ 5m
5. **UI Efficiency:** Direct frame modification, no full-frame copies
6. **Configuration:** All magic numbers in config.yaml, not hardcoded

This documentation should help you explain every line during your defense!
