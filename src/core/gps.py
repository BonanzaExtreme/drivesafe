"""
gps.py – USB GPS Speed Reader

Reads NMEA sentences directly from a USB GPS receiver over serial and
extracts the vehicle's current ground speed.

Usage
-----
    reader = GPSReader()
    reader.start()

    speed = reader.speed_kmh   # float or None if no fix yet
    lat, lon = reader.position # (float, float) or (None, None) if no fix

    reader.stop()

Requirements
------------
- pyserial:                  pip install pyserial
- USB GPS device connected and available as a serial port

The reader runs as a daemon thread so it will not block process exit.
If the GPS device is unavailable or the device loses its fix, speed_kmh returns None
and the display gracefully shows "-- km/h".
"""

import logging
import os
import threading
import time

from .braking import BrakingModel

logger = logging.getLogger(__name__)

# ── serial import (graceful degradation) ──────────────────────────────────────

try:
    import serial as _serial_module
    from serial import SerialException
    _SERIAL_AVAILABLE = True
except ImportError:
    _serial_module = None
    SerialException = Exception
    _SERIAL_AVAILABLE = False
    logger.warning(
        "[GPS] 'pyserial' package not found. "
        "Install it with: pip install pyserial\n"
        "Speed will show as unavailable."
    )


# knots → km/h
_KNOTS_TO_KMH = 1.852

_DEFAULT_PORTS = (
    "/dev/ttyUSB0",
    "/dev/ttyACM0",
    "/dev/ttyS0",
)


def _safe_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_lat_lon(value: str | None, hemisphere: str | None) -> float | None:
    if not value or not hemisphere:
        return None

    try:
        raw = float(value)
    except ValueError:
        return None

    degrees = int(raw // 100)
    minutes = raw - (degrees * 100)
    decimal = degrees + (minutes / 60.0)
    if hemisphere in ("S", "W"):
        decimal = -decimal
    return decimal


def _resolve_serial_port(preferred: str | None) -> str:
    env_port = os.getenv("DRIVESAFE_GPS_PORT")
    if env_port:
        return env_port

    if preferred:
        return preferred

    for candidate in _DEFAULT_PORTS:
        if os.path.exists(candidate):
            return candidate

    return _DEFAULT_PORTS[0]


class GPSReader:
    """
    Background thread that polls a serial GPS receiver for speed and position.

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
                 serial_port: str | None = None,
                 baud_rate: int = 9600,
                 reconnect_delay: float = 3.0,
                 timeout: float = 1.0) -> None:
        self._serial_port     = _resolve_serial_port(serial_port)
        self._baud_rate       = int(os.getenv("DRIVESAFE_GPS_BAUDRATE", baud_rate))
        self._reconnect_delay = reconnect_delay
        self._timeout         = timeout

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

    def _update(self,
                speed_kmh: float | None = None,
                lat: float | None = None,
                lon: float | None = None) -> None:
        with self._lock:
            if speed_kmh is not None:
                self._speed_kmh = max(0.0, round(speed_kmh, 1))

            if lat is not None:
                self._lat = lat
            if lon is not None:
                self._lon = lon

            self._has_fix = lat is not None

    def _run(self) -> None:
        """Main loop: connect to the serial GPS device and stream NMEA sentences."""
        if not _SERIAL_AVAILABLE:
            logger.warning("[GPS] serial client unavailable – reader inactive.")
            return

        while self._running:
            serial_port = None
            try:
                logger.info(
                    f"[GPS] Connecting to serial GPS at {self._serial_port} "
                    f"({self._baud_rate} baud)"
                )
                serial_port = _serial_module.Serial(
                    port=self._serial_port,
                    baudrate=self._baud_rate,
                    timeout=self._timeout,
                )

                while self._running:
                    raw = serial_port.readline()
                    if not raw:
                        continue

                    line = raw.decode("ascii", errors="replace").strip()
                    if not line.startswith("$"):
                        continue

                    fields = line.split(",")
                    sentence = fields[0][1:]

                    if sentence == "GPVTG" or sentence == "GNVTG":
                        # VTG speed is usually in km/h at field 7.
                        speed_kmh = _safe_float(fields[7] if len(fields) > 7 else None)
                        if speed_kmh is not None:
                            self._update(speed_kmh=speed_kmh)
                        continue

                    if sentence in ("GPRMC", "GNRMC"):
                        # RMC speed is in knots at field 7, position is fields 3-6.
                        speed_knots = _safe_float(fields[7] if len(fields) > 7 else None)
                        lat = _parse_lat_lon(fields[3] if len(fields) > 3 else None,
                                             fields[4] if len(fields) > 4 else None)
                        lon = _parse_lat_lon(fields[5] if len(fields) > 5 else None,
                                             fields[6] if len(fields) > 6 else None)
                        if speed_knots is not None:
                            self._update(speed_kmh=speed_knots * _KNOTS_TO_KMH,
                                         lat=lat, lon=lon)
                        elif lat is not None or lon is not None:
                            self._update(lat=lat, lon=lon)
                        continue

                    if sentence in ("GPGGA", "GNGGA"):
                        # GGA carries position but not speed.
                        lat = _parse_lat_lon(fields[2] if len(fields) > 2 else None,
                                             fields[3] if len(fields) > 3 else None)
                        lon = _parse_lat_lon(fields[4] if len(fields) > 4 else None,
                                             fields[5] if len(fields) > 5 else None)
                        if lat is not None or lon is not None:
                            self._update(lat=lat, lon=lon)

            except SerialException as exc:
                logger.warning(
                    f"[GPS] Could not open {self._serial_port}: {exc} "
                    f"– retrying in {self._reconnect_delay}s"
                )
                self._set_no_fix()
            except Exception as exc:
                logger.warning(f"[GPS] Error: {exc} – retrying in {self._reconnect_delay}s")
                self._set_no_fix()
            finally:
                try:
                    if serial_port is not None:
                        serial_port.close()
                except Exception:
                    pass

            if self._running:
                time.sleep(self._reconnect_delay)

        logger.info("[GPS] Reader stopped.")
