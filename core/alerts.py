"""
alerts.py – Driver Alert System

Fires non-blocking voice alerts (espeak) with independent per-key cooldowns
so the driver hears important messages without being spammed.

Usage:
    mgr = AlertManager(enabled=True, voice_rate=160)
    mgr.fire("ped_danger",  "Brake now!",               level="danger")
    mgr.fire("ped_warning", "Slow down, pedestrian ahead", level="warning")
    mgr.fire("crosswalk",   "Crosswalk ahead, be careful", level="crosswalk")
"""
import os
import subprocess
import threading
import time

# Paths resolved relative to this file so they work from any working directory
_HERE        = os.path.dirname(os.path.abspath(__file__))
_BEEP_SOUNDS: dict[str, str] = {
    "danger": os.path.join(_HERE, "..", "soundeffects", "mixkit-vintage-warning-alarm-990.wav"),
    "warning": os.path.join(_HERE, "..", "soundeffects", "mixkit-classic-short-alarm-993.wav"),
}
_DEFAULT_BEEP = _BEEP_SOUNDS["warning"]
_PIPER_BIN   = os.path.join(_HERE, "..", "piper", "piper")
_VOICE_MODEL = os.path.join(_HERE, "..", "voice",
                            "en_US-hfc_male-medium.onnx")
_SAMPLE_RATE = "22050"

class AlertManager:
    """
    Non-blocking voice alert manager backed by espeak.

    Each alert is identified by a *key* string so its cooldown is tracked
    independently from other alerts.  If espeak is not installed the class
    degrades silently – the rest of the app is unaffected.
    """

    # Default seconds between repeats of the same alert key
    DEFAULT_COOLDOWNS: dict[str, float] = {
        "danger":    2.5,
        "warning":   5.0,
        "crosswalk": 7.0,
    }

    def __init__(self, enabled: bool=True, voice_rate=160, cooldowns=None):
        self.enabled = enabled
        self.voice_rate = voice_rate
        self._cooldowns = {**self.DEFAULT_COOLDOWNS, **(cooldowns or {})}
        self._last = {}
        self._lock = threading.Lock()

    # ── public API ───────────────────────────────────────────────────────────

    def fire(self, key: str, message: str, level: str = "warning") -> bool:
        """
        Speak *message* if the cooldown for *key* has expired.

        Returns True when the alert actually fires, False when suppressed
        (cooldown active, or alerts disabled).
        """
        if not self.enabled:
            return False

        now = time.monotonic()
        cooldown = self._cooldowns.get(level, 5.0)

        with self._lock:
            if now - self._last.get(key, 0.0) < cooldown:
                return False
            self._last[key] = now

        threading.Thread(target=self._speak, args=(message, level), daemon=True).start()
        return True

    def reset(self, key: str | None = None) -> None:
        """Clear cooldown for *key*, or all cooldowns if *key* is None."""
        with self._lock:
            if key is None:
                self._last.clear()
            else:
                self._last.pop(key, None)

    # ── private ──────────────────────────────────────────────────────────────

    def _speak(self, message: str, level: str = "warning") -> None:
        try:
            beep_file = _BEEP_SOUNDS.get(level, _DEFAULT_BEEP)

            try:
                subprocess.run(
                    ["aplay", beep_file],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=1.0,
                )
            except subprocess.TimeoutExpired:
                pass

            piper = subprocess.Popen(
                [_PIPER_BIN, "--model", _VOICE_MODEL, "--output_raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            # 3) Play Piper raw PCM output
            aplay = subprocess.Popen(
                ["aplay", "-r", _SAMPLE_RATE, "-f", "S16_LE", "-t", "raw", "-"],
                stdin=piper.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            if piper.stdin:
                piper.stdin.write(message.encode("utf-8"))
                piper.stdin.close()

            # Wait so child processes don't get cut off
            aplay.wait(timeout=10)

        except FileNotFoundError:
            pass
        except Exception:
            pass
