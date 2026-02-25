# DriveSafe – Feature Reference

This document explains every driver-assistance feature in the system,
why each one exists, and how to tune it.

---

## 1. In-Path Detection

### What it does
The frame is divided into three horizontal zones.  Only the **centre 40 %**
of the frame is considered the car's travel path.  Pedestrians detected
outside that zone (e.g. on a pavement to the left or right) are still drawn
on screen but will **never trigger a voice alert**.

```
|  side  |        car's path (40 %)         |  side  |
|  30 %  |                                  |  30 %  |
         ^                                  ^
      left edge                         right edge
      of path zone                      of path zone
```

Pedestrians inside the path zone get an extra `!` appended to their label
so you can tell them apart at a glance, and the top-bar counter turns red:
`PED 3   CW 1   PATH 2`.

### How to tune
In `config.yaml`, change `alerts.path_zone`:
```yaml
alerts:
  path_zone: 0.40   # 0.30 = narrower / stricter,  0.55 = wider / more sensitive
```

---

## 2. Voice Alerts (espeak)

Alerts fire from a background thread so they **never block the video loop**.
Each alert key has its own cooldown timer so the same message is not
repeated until enough time has passed.

| Situation | Voice message | Cooldown |
|---|---|---|
| In-path pedestrian at WARNING distance | *"Slow down, pedestrian ahead"* | 5 s |
| In-path pedestrian at DANGER distance | *"Brake now!"* | 2.5 s |
| Two or more pedestrians in danger zone | *"Multiple pedestrians! Brake now!"* | 2.5 s |
| Crosswalk within WARNING/DANGER range | *"Crosswalk ahead, be careful"* | 7 s |

If `espeak` is not installed the system runs silently — no crash, no error.

### Install espeak (Jetson / Ubuntu)
```bash
sudo apt install espeak
```

### Mute / unmute at runtime
Press **M** while the app is running.  A message prints to the terminal:
```
[DriveSafe] Audio alerts OFF
[DriveSafe] Audio alerts ON
```

### How to tune
```yaml
alerts:
  enabled: true
  voice_rate: 160          # words per minute (120 = slow, 200 = fast)
  danger_cooldown: 2.5     # seconds
  warning_cooldown: 5.0
  crosswalk_cooldown: 7.0
```

---

## 3. On-Screen Alert Banner

When an audio alert fires, a matching **text banner** appears on the video
feed just below the top status bar.  It stays visible for as long as the
threat condition holds — it disappears the moment it is resolved.

| Condition | Banner text | Colour |
|---|---|---|
| In-path pedestrian – WARNING | `SLOW DOWN` | Amber |
| In-path pedestrian – DANGER | `BRAKE NOW` | Red |
| Multiple pedestrians in DANGER | `BRAKE NOW  (N IN PATH)` | Red |
| Crosswalk in range (no ped alert) | `CROSSWALK AHEAD — BE CAREFUL` | Amber |

The banner is purposely placed so it does not cover the centre of the video.

---

## 4. Path Zone Guide Lines

Two soft dashed vertical lines are drawn on the video frame to show the
driver exactly which zone is being monitored as the travel path.  They are
intentionally low-contrast so they do not distract during normal driving.

---

## 5. Crosswalk Caution System

A crosswalk detection by itself (even with no pedestrian visible yet) will
trigger a voice alert and on-screen banner when the crosswalk enters the
WARNING or DANGER distance range.  This gives the driver advance warning
that a crossing area is approaching, even if pedestrians have not stepped
out yet.

The crosswalk safety thresholds are configured independently from
pedestrian thresholds:

```yaml
safety:
  crosswalk:
    danger:  5.0    # metres – red
    warning: 8.0    # metres – amber
```

---

## 6. Multi-Pedestrian Escalation

If **two or more** in-path pedestrians are simultaneously in the DANGER
zone, the voice alert automatically escalates:

- 1 pedestrian → *"Brake now!"*
- 2+ pedestrians → *"Multiple pedestrians! Brake now!"*

The banner also shows the count: `BRAKE NOW  (3 IN PATH)`.

---

## 7. Alert Priority

When multiple threats exist at the same time, the on-screen banner shows
the most important one and does not stack messages:

1. **DANGER pedestrian in path** (highest priority)
2. **WARNING pedestrian in path**
3. **Crosswalk in range** (shown only when no pedestrian alert is active)

Audio alerts for all active threats still fire independently on their own
cooldown timers.

---

## 8. Safety Level Colour Coding (existing, unchanged)

| Colour | Level | Pedestrian | Crosswalk |
|---|---|---|---|
| 🟢 Green | SAFE | ≥ 5.0 m | ≥ 8.0 m |
| 🟡 Amber | WARNING | 2.5 – 5.0 m | 5.0 – 8.0 m |
| 🔴 Red | DANGER | < 2.5 m | < 5.0 m |

Thresholds are configurable in `config.yaml` under `safety:`.

---

## Keyboard Controls

| Key | Action |
|---|---|
| `I` | Toggle info panel |
| `M` | Mute / unmute audio alerts |
| `Q` / `ESC` | Quit |

---

## Files Changed / Added

| File | Change |
|---|---|
| `core/alerts.py` | **New** – AlertManager class (voice alerts, cooldowns) |
| `core/safety.py` | Added `is_in_path()` helper function |
| `ui/display.py` | Added path zone lines, alert banner, updated `draw_hud()` |
| `main.py` | Wired up AlertManager, in-path logic, M-key mute |
| `config.yaml` | Added `alerts:` section |
