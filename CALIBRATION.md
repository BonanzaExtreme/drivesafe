# DriveSafe – Calibration Guide

This guide walks you through calibrating the system so that distance readings
are accurate for **your camera** and **your environment**.  
All values are set in **`config.yaml`** — you do not need to touch any other file.

---

## Before You Start

> **Mount the camera first.**  
> Attach the camera in the exact position it will be used while driving
> (e.g. on the dashboard, behind the windshield).  
> Every measurement in this guide is specific to that position and angle.  
> If you move the camera later, you must redo the calibration.

---

## What Needs to Be Calibrated

| Step | Parameter | Where | Why |
|------|-----------|--------|-----|
| 1 | `focal_length` | `config.yaml` | Unique to your camera – drives all distance readings |
| 2 | `person_height` | `config.yaml` | Should match the average adult in your region |
| 3 | Safety thresholds | `config.yaml` | Should feel right for your real driving speed |
| 4 | `confidence` & `iou` | `config.yaml` | Balance missed detections vs false positives |

Calibrate **in order** – each step builds on the one before.

---

## Step 1 – Focal Length (Most Important)

**`config.yaml → distance.focal_length`**  
 Default: `615.0` 

Focal length in pixels is unique to every camera lens and resolution.
It is the single most important value – every distance reading depends on it.

### What you need

- A tape measure
- A person (or a vertical pole/stick) of known height
- The system running on your camera feed

### Procedure

**1.** Stand a person at a **known distance** from the camera.
Start with **3 metres**, confirmed with the tape measure.

**2.** Run the system:
```bash
python main.py
```

**3.** Read the bounding box height in pixels. Add this one temporary line
inside `core/distance.py` in the `if cls_name == "pedestrian":` block:

```python
bbox_height = max(y2 - y1, 1.0)
print(f"bbox_height = {bbox_height:.1f} px")   # ← add temporarily
return (self.person_height * self.focal_length) / bbox_height
```

Watch the terminal output and note the average number across several frames.

**4.** Calculate your focal length using the pinhole formula:

$$f = \frac{d \times h_{px}}{H_{real}}$$

| Symbol | Meaning | Example |
|--------|---------|---------|
| $d$ | Real distance to the person (metres) | `3.0` |
| $h_{px}$ | Bounding box height in pixels | `350` |
| $H_{real}$ | Real height of the person (metres) | `1.7` |

**Example calculation:**

$$f = \frac{3.0 \times 350}{1.7} = 617.6$$

**5.** Repeat at **3 – 4 different distances** (3 m, 5 m, 8 m, 10 m) and
**average all results**. More distances = better accuracy.

**6.** Remove the temporary print line, then update `config.yaml`:

```yaml
distance:
  focal_length: 617.6   # ← your measured value
```

### Typical values by camera type

| Camera | Typical range |
|--------|---------------|
| Built-in laptop webcam 720p | 500 – 700 px |
| Logitech C920 / C930 1080p | 800 – 950 px |
| Raspberry Pi Camera v2 | 600 – 700 px |
| Wide-angle dashcam 1080p | 400 – 600 px |
| Phone camera 1080p | 900 – 1 200 px |

---

## Step 2 – Person Height

**`config.yaml → distance.person_height`**  
Default: `1.7`

This is the assumed real-world height of a standing adult pedestrian.
A 5 cm error only changes distance readings by about 3 %, so this just
needs a reasonable value for your region.

| Region | Recommended value |
|--------|-------------------|
| Global average | 1.70 m |
| Southeast Asia | 1.62 m |
| Philippines | 1.60 m |
| Europe / North America | 1.75 m |

Update `config.yaml`:

```yaml
distance:
  person_height: 1.62   # adjust for your region
```

---

## Step 3 – Safety Zone Thresholds

**`config.yaml → safety.pedestrian`**

These control when a pedestrian's bounding box changes colour:

| Colour | Meaning | Condition |
|--------|---------|-----------|
| 🟢 Green | Safe | distance ≥ `warning` metres |
| 🟡 Amber | Slow down | `danger` m ≤ distance < `warning` m |
| 🔴 Red | Brake now | distance < `danger` metres |

The same thresholds also decide when voice alerts fire.

### Procedure

1. After calibrating `focal_length`, run the system on live footage or
   a dashcam recording.
2. Watch the colour transitions as pedestrians approach.
3. Ask yourself:
   - Does **red** appear at a distance that genuinely feels dangerous at your
     typical driving speed?
   - Does **amber** appear early enough to give you comfortable reaction time?
4. Adjust until both transitions feel natural.

### Guidelines by driving speed

| Speed | Suggested `danger` | Suggested `warning` |
|-------|-------------------|-------------------|
| Slow  (≤ 20 km/h) | 2.0 m | 4.0 m |
| City  (≤ 40 km/h) | 3.0 m | 6.0 m |
| Suburban (≤ 60 km/h) | 4.0 m | 8.0 m |

```yaml
safety:
  pedestrian:
    danger:  3.0   # metres → box turns RED,  "Brake now!" fires
    warning: 6.0   # metres → box turns AMBER, "Slow down" fires
```

---

## Step 4 – Confidence & IoU

**`config.yaml → model`**  
Defaults: `confidence: 0.35`, `iou: 0.7`

These control how the YOLO detector decides what counts as a valid detection.

### `confidence` – Detection Sensitivity

The minimum score (0 – 1) a detection must reach to be shown on screen.

| Symptom | Fix |
|---------|-----|
| Boxes appearing on things that are **not** pedestrians | Raise: `0.45` or `0.55` |
| Real pedestrians **not being detected** | Lower: `0.25` or `0.30` |
| Everything looks good | Leave at `0.35` |

### `iou` – Duplicate Box Suppression

Controls how aggressively overlapping boxes on the same object are merged.

| Symptom | Fix |
|---------|-----|
| **Two boxes** on the same person | Lower: `0.5` |
| Nearby people **merged** into one box | Raise: `0.8` |
| No issues | Leave at `0.7` |

---

## Quick Reference – `config.yaml`

```yaml
distance:
  focal_length: 615.0     # calibrate in Step 1  (pixels – unique to your camera)
  person_height: 1.70     # calibrate in Step 2  (metres – average adult in your region)

safety:
  pedestrian:
    danger:  2.5          # calibrate in Step 3  (metres → RED)
    warning: 5.0          # calibrate in Step 3  (metres → AMBER)

model:
  confidence: 0.35        # calibrate in Step 4
  iou: 0.7                # calibrate in Step 4
```

---

## After Any Camera Move

If you change the **camera position, angle, or mounting height**, redo
**Steps 1 and 2**.  
Steps 3 and 4 do not depend on camera position and do not need to be redone.
