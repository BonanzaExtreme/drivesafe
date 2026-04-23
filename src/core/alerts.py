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

from .paths import resource_path

_BEEP_SOUNDS: dict[str, str] = {
    "danger": resource_path("assets", "soundeffects", "mixkit-vintage-warning-alarm-990.wav"),
    "warning": resource_path("assets", "soundeffects", "mixkit-classic-short-alarm-993.wav"),
}
_DEFAULT_BEEP = _BEEP_SOUNDS["warning"]
_PIPER_BIN   = resource_path("tools", "piper", "piper")
_PIPER_DIR = os.path.dirname(_PIPER_BIN)
_DEFAULT_VOICE_MODEL = resource_path("models", "voice", "en_US-hfc_male-medium (1).onnx")
_VOICE_SAMPLE_RATE = 22050


def _first_available_voice_model() -> str:
    voice_dir = resource_path("models", "voice")
    try:
        candidates = sorted(
            name for name in os.listdir(voice_dir)
            if name.endswith(".onnx")
        )
        if candidates:
            return os.path.join(voice_dir, candidates[0])
    except Exception:
        pass
    return _DEFAULT_VOICE_MODEL


def _resolve_voice_model_path(voice_model: str | None) -> str:
    if not voice_model:
        return _first_available_voice_model()

    if os.path.isabs(voice_model):
        return voice_model if os.path.exists(voice_model) else _first_available_voice_model()

    # Bare filename: look inside models/voice.
    if os.sep not in voice_model and "/" not in voice_model:
        candidate = resource_path("models", "voice", voice_model)
        return candidate if os.path.exists(candidate) else _first_available_voice_model()

    # Relative path from bundle root.
    candidate = resource_path(voice_model)
    return candidate if os.path.exists(candidate) else _first_available_voice_model()

class AlertManager:
    """
    Non-blocking voice alert manager backed by espeak.

    Each alert is identified by a *key* string so its cooldown is tracked
    independently from other alerts.  If espeak is not installed the class
    degrades silently – the rest of the app is unaffected.
    """
    LEVEL_PRIORITY = {
        "danger": 3,
        "warning": 2,
        "crosswalk": 1,
    }

    # Default seconds between repeats of the same alert key
    DEFAULT_COOLDOWNS: dict[str, float] = {
        "danger":    2.5,
        "warning":   5.0,
        "crosswalk": 7.0,
    }

    VALID_MODES = {"beep", "voice", "both", "off"}

    def __init__(self, enabled: bool = True, voice_rate=160, cooldowns=None, mode: str = "voice", voice_model: str | None = None):
        self.enabled = enabled
        self.voice_rate = voice_rate
        self._cooldowns = {**self.DEFAULT_COOLDOWNS, **(cooldowns or {})}
        self._last = {}
        self._lock = threading.Lock()
     # Alert hierarchy: track current alert
        self._current_alert = None  # (process_dict, level)
        self._alert_lock = threading.Lock()
        self._mode = self._normalize_mode(mode)
        self._voice_model = _resolve_voice_model_path(voice_model)
        
    # ── public API ───────────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def voice_model(self) -> str:
        return self._voice_model

    def set_mode(self, mode: str) -> None:
        self._mode = self._normalize_mode(mode)

    def set_voice_model(self, voice_model: str) -> None:
        self._voice_model = _resolve_voice_model_path(voice_model)

    def _normalize_mode(self, mode: str) -> str:
        if mode not in self.VALID_MODES:
            return "voice"
        return mode

    def fire(self, key: str, message: str, level: str = "warning") -> bool:
        """
        Speak *message* if the cooldown for *key* has expired.

        Returns True when the alert actually fires, False when suppressed
        (cooldown active, or alerts disabled).
        """
        if not self.enabled or self.mode == "off":
            return False

        level_priority = self.LEVEL_PRIORITY.get(level, 0)
        
        with self._alert_lock:
            if self._current_alert:
                current_priority = self.LEVEL_PRIORITY.get(self._current_alert[1], 0)
                if level_priority <= current_priority:
                    # Lower or equal priority - don't interrupt
                    return False
                # Higher priority - kill current alert
                self._kill_current_alert()

        now = time.monotonic()
        cooldown = self._cooldowns.get(level, 5.0)

        with self._lock:
            if now - self._last.get(key, 0.0) < cooldown:
                return False
            self._last[key] = now

        threading.Thread(target=self._speak, args=(message, level, self.mode, self.voice_model, key), daemon=True).start()
        return True

    def stop_current_alert(self, key_prefix: str | None = None) -> None:
        with self._alert_lock:
            if not self._current_alert:
                return
            processes, _, current_key = self._current_alert
            if key_prefix is not None and not current_key.startswith(key_prefix):
                return
            self._kill_processes(processes)
            self._current_alert = None

    def reset(self, key: str | None = None) -> None:
        """Clear cooldown for *key*, or all cooldowns if *key* is None."""
        with self._lock:
            if key is None:
                self._last.clear()
            else:
                self._last.pop(key, None)
        
    def _kill_current_alert(self):
        """Kill beep and speech of current alert (must be called with _alert_lock held)."""
        if self._current_alert:
            processes, _, _ = self._current_alert
            self._kill_processes(processes)
            self._current_alert = None

    def _kill_processes(self, processes: dict) -> None:
        for proc in [processes.get("beep"), processes.get("aplay"), processes.get("piper")]:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=0.5)
                except Exception:
                    pass

    # ── private ──────────────────────────────────────────────────────────────

    def _speak(self, message: str, level: str = "warning", mode: str = "voice", voice_model: str | None = None, key: str = "") -> None:
        try:
            beep_file = _BEEP_SOUNDS.get(level, _DEFAULT_BEEP)

            processes = {}
            if mode in {"beep", "both"}:
                beep = subprocess.Popen(
                    ["aplay", beep_file],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                processes["beep"] = beep
                with self._alert_lock:
                    self._current_alert = (processes, level, key)

            if mode in {"voice", "both"}:
                model_path = voice_model or _DEFAULT_VOICE_MODEL
                piper_env = os.environ.copy()
                piper_env["LD_LIBRARY_PATH"] = f"{_PIPER_DIR}:{piper_env.get('LD_LIBRARY_PATH', '')}".rstrip(":")
                piper_env["ESPEAK_DATA_PATH"] = os.path.join(_PIPER_DIR, "espeak-ng-data")
                piper = subprocess.Popen(
                    [_PIPER_BIN, "--model", model_path, "--output_raw"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=piper_env,
                )
                processes["piper"] = piper
                with self._alert_lock:
                    self._current_alert = (processes, level, key)

                aplay = subprocess.Popen(
                    ["aplay", "-r", str(_VOICE_SAMPLE_RATE), "-f", "S16_LE", "-t", "raw", "-"],
                    stdin=piper.stdout,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                processes["aplay"] = aplay

                if piper.stdin:
                    piper.stdin.write(message.encode("utf-8"))
                    piper.stdin.close()

                aplay.wait(timeout=10)

                if mode == "both" and "beep" in processes:
                    processes["beep"].terminate()
                    try:
                        processes["beep"].wait(timeout=0.5)
                    except Exception:
                        pass

            if mode == "beep":
                beep.wait(timeout=10)

        except FileNotFoundError:
            pass
        except Exception:
            pass
        finally:
            # Cleanup
            with self._alert_lock:
                if self._current_alert and self._current_alert[1] == level and self._current_alert[2] == key:
                    self._current_alert = None
