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

import subprocess
import threading
import time


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

    def __init__(
        self,
        enabled: bool = True,
        voice_rate: int = 160,
        cooldowns: dict[str, float] | None = None,
    ) -> None:
        self.enabled = enabled
        self.voice_rate = voice_rate
        self._cooldowns = {**self.DEFAULT_COOLDOWNS, **(cooldowns or {})}
        self._last: dict[str, float] = {}
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

        threading.Thread(target=self._speak, args=(message,), daemon=True).start()
        return True

    def reset(self, key: str | None = None) -> None:
        """Clear cooldown for *key*, or all cooldowns if *key* is None."""
        with self._lock:
            if key is None:
                self._last.clear()
            else:
                self._last.pop(key, None)

    # ── private ──────────────────────────────────────────────────────────────

    def _speak(self, message: str) -> None:
        try:
            subprocess.run(
                ["espeak", "-s", str(self.voice_rate), "-v", "en", message],
                capture_output=True,
                timeout=6,
            )
        except FileNotFoundError:
            pass  # espeak not installed – silent degradation
        except Exception:
            pass
