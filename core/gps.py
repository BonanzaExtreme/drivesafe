"""
gps.py – USB GPS Speed Reader

Connects to gpsd (the system GPS daemon) via its socket and continuously
reads TPV (Time-Position-Velocity) reports to extract the vehicle's current
ground speed.

Usage
-----
    reader = GPSReader()
    reader.start()

    speed = reader.speed_kmh   # float or None if no fix yet
    lat, lon = reader.position # (float, float) or (None, None) if no fix

    reader.stop()

Requirements
------------
- gpsd must be running:      sudo systemctl start gpsd
- Python gps package:        pip install gps  (or 'gpsd-py3' as fallback)

The reader runs as a daemon thread so it will not block process exit.
If gpsd is unavailable or the device loses its fix, speed_kmh returns None
and the display gracefully shows "-- km/h".
"""

import threading
import time
import logging

from core.braking import BrakingModel

logger = logging.getLogger(__name__)

# ── gpsd client import (graceful degradation) ─────────────────────────────────

try:
    import gps as _gps_module
    _GPSD_AVAILABLE = True
except ImportError:
    _gps_module = None
    _GPSD_AVAILABLE = False
    logger.warning(
        "[GPS] 'gps' package not found. "
        "Install it with: pip install gps\n"
        "Speed will show as unavailable."
    )


# m/s  →  km/h
_MS_TO_KMH = 3.6

# Minimum speed (m/s) to report – below this threshold we treat it as 0
# (eliminates GPS drift noise when stationary)
_MIN_SPEED_MS = 0.3


class GPSReader:
    """
    Background thread that polls gpsd for vehicle speed and position.

    Attributes (read from any thread)
    ----------
    speed_kmh : float | None
        Current ground speed in km/h, or None when there is no valid GPS fix.
    position : tuple[float, float] | None
        (latitude, longitude) in decimal degrees, or (None, None) when unknown.
    has_fix : bool
        True when the last report contained a 2D or 3D position fix.
    """

    def __init__(self,
                 host: str = "127.0.0.1",
                 port: int = 2947,
                 reconnect_delay: float = 3.0) -> None:
        self._host            = host
        self._port            = port
        self._reconnect_delay = reconnect_delay

        # Shared state – written only inside the reader thread
        self._lock      = threading.Lock()
        self._speed_kmh: float | None = None
        self._lat:       float | None = None
        self._lon:       float | None = None
        self._has_fix:   bool         = False

        self._thread  = threading.Thread(target=self._run, name="GPSReader", daemon=True)
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> "GPSReader":
        """Start the background reader thread. Chainable."""
        self._running = True
        self._thread.start()
        return self

    def stop(self) -> None:
        """Signal the thread to stop. Does not block."""
        self._running = False

    @property
    def speed_kmh(self) -> float | None:
        """Current ground speed in km/h, or None if no fix."""
        with self._lock:
            return self._speed_kmh

    @property
    def position(self) -> tuple:
        """(lat, lon) in decimal degrees, or (None, None) if no fix."""
        with self._lock:
            return (self._lat, self._lon)

    @property
    def has_fix(self) -> bool:
        with self._lock:
            return self._has_fix

    def stopping_distance_m(self, model: BrakingModel | None = None) -> float | None:
        """Compute stopping distance in meters from the latest GPS speed.

        Returns None when no speed is currently available.
        """
        with self._lock:
            speed_kmh = self._speed_kmh

        if speed_kmh is None:
            return None

        braking_model = model or BrakingModel()
        return braking_model.stopping_distance_m(speed_kmh)

    def danger_for_distance(self,
                            object_distance_m: float,
                            model: BrakingModel | None = None) -> bool:
        """Check if an object is inside GPS-derived stopping distance.

        Returns False when speed is unavailable.
        """
        with self._lock:
            speed_kmh = self._speed_kmh

        if speed_kmh is None:
            return False

        braking_model = model or BrakingModel()
        return braking_model.danger_for_distance(object_distance_m, speed_kmh)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _set_no_fix(self) -> None:
        with self._lock:
            self._speed_kmh = None
            self._has_fix   = False

    def _update(self, speed_ms: float | None, lat: float | None, lon: float | None) -> None:
        with self._lock:
            if speed_ms is not None and speed_ms >= _MIN_SPEED_MS:
                self._speed_kmh = round(speed_ms * _MS_TO_KMH, 1)
            elif speed_ms is not None:
                self._speed_kmh = 0.0
            # else: keep previous value

            if lat is not None:
                self._lat = lat
            if lon is not None:
                self._lon = lon

            self._has_fix = lat is not None

    def _run(self) -> None:
        """Main loop: connect to gpsd and stream TPV reports."""
        if not _GPSD_AVAILABLE:
            logger.warning("[GPS] gpsd client unavailable – reader inactive.")
            return

        while self._running:
            session = None
            try:
                logger.info(f"[GPS] Connecting to gpsd at {self._host}:{self._port}")
                session = _gps_module.gps(
                    host=self._host,
                    port=self._port,
                    mode=_gps_module.WATCH_ENABLE | _gps_module.WATCH_NEWSTYLE,
                )

                for report in session:
                    if not self._running:
                        break

                    if report["class"] != "TPV":
                        continue

                    # Extract fields – getattr with sentinel avoids KeyError
                    speed_ms = getattr(report, "speed", None)   # m/s, float or None
                    lat      = getattr(report, "lat",   None)
                    lon      = getattr(report, "lon",   None)

                    self._update(speed_ms, lat, lon)

            except StopIteration:
                # gpsd closed the stream (e.g. device disconnected)
                logger.warning("[GPS] gpsd stream ended.")
                self._set_no_fix()
            except Exception as exc:
                logger.warning(f"[GPS] Error: {exc}  – retrying in {self._reconnect_delay}s")
                self._set_no_fix()
            finally:
                try:
                    if session is not None:
                        session.close()
                except Exception:
                    pass

            if self._running:
                time.sleep(self._reconnect_delay)

        logger.info("[GPS] Reader stopped.")
