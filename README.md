# DriveSafe – Pedestrian Detection & Distance Estimation

Real-time pedestrian detection and distance estimation
using **YOLOv9 + ByteTrack**, designed for dashcam video analysis.

---

## Project Structure

```
main.py              Entry point – config loading, main loop, keyboard
config.yaml          All tuneable parameters (thresholds, paths, etc.)

core/
  detector.py        YOLOv9 inference + ByteTrack multi-object tracking
  distance.py        Monocular distance estimation (pinhole camera model)
  safety.py          SAFE / WARNING / DANGER classification

ui/
  display.py         All OpenCV drawing (boxes, HUD, info panel)

weights/
  best.engine            Fine-tuned YOLOv9 model weights
```

**5 Python files, ~350 total lines.** Every file does one thing.

---

## How to Run

```bash
pip install ultralytics opencv-python numpy pyyaml lap
python main.py
```

---

## Keyboard

| Key       | Action              |
|-----------|---------------------|
| `I`       | Toggle info panel   |
| `Q / ESC` | Quit               |

---

## How It Works

### 1. Detection (`core/detector.py`)

Uses YOLOv9 (fine-tuned on two classes: pedestrian and crosswalk)
with ByteTrack for persistent tracking across frames. Each detection
gets a unique track ID that stays consistent as the object moves.

### 2. Distance Estimation (`core/distance.py`)

**Pedestrian** — Pinhole camera model:
```
distance = (person_height × focal_length) / bbox_height_pixels
```
A far-away person has a small bounding box; a close person has a
large one. The ratio gives us the distance.

**Crosswalk** — Linear ground-plane mapping:
```
distance = a × y_bottom + b
```
Objects at the bottom of the frame are closer to the camera.

### 3. Safety Assessment (`core/safety.py`)

Each detection is classified into three levels:

| Level   | Pedestrian  | Crosswalk  | Colour |
|---------|-------------|------------|--------|
| DANGER  | < 2.5 m     | < 5.0 m   | Red    |
| WARNING | 2.5 – 5.0 m| 5.0 – 8.0 m| Amber |
| SAFE    | > 5.0 m     | > 8.0 m   | Green  |

The overall status is the **worst** level among all detections.

### 4. Display (`ui/display.py`)

Draws directly onto the video frame:
- Corner-style bounding boxes (minimal, non-intrusive)
- Distance labels above each detection
- Top bar: FPS + detection counts
- Bottom bar: overall safety level colour strip

### 5. Main Loop (`main.py`)

```
while True:
    frame ← read from video
    detections ← detector.track(frame)
    draw_hud(frame, detections, ...)
    cv2.imshow(frame)
```

---

## Model

| Property  | Value                              |
|-----------|------------------------------------|
| Base      | YOLOv9 (fine-tuned)                |
| Classes   | 0 = crosswalk, 1 = pedestrian     |
| Dataset   | drivesafe-ped-lane (Roboflow)      |
| Weights   | `weights/last.pt`                  |

---

## Configuration (`config.yaml`)

All numbers are in one file – no magic values in the code:

- `model.confidence` – minimum detection confidence (0.35)
- `model.iou` – NMS IoU threshold (0.7)
- `distance.focal_length` – camera focal length in pixels (615)
- `distance.person_height` – assumed pedestrian height in metres (1.7)
- `safety.pedestrian.danger` / `warning` – zone boundaries in metres

---

## Dependencies

| Library     | Purpose                                |
|-------------|----------------------------------------|
| ultralytics | YOLOv9 inference + ByteTrack tracking  |
| opencv      | Video capture, drawing, display        |
| numpy       | Array operations (used by OpenCV)      |
| pyyaml      | Config file parsing                    |
| lap         | Linear assignment for ByteTrack        |
