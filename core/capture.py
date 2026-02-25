"""
capture.py – Camera Initialisation & Threaded Capture

open_camera      – opens a V4L2/GStreamer camera and forces MJPG codec.
VideoCaptureAsync – wraps an OpenCV VideoCapture in a background thread so
                   the main loop never blocks waiting for the next frame.
"""

import sys
import threading

import cv2


def open_camera(cfg: dict) -> cv2.VideoCapture:
    """Open a USB camera with MJPG + forced resolution/FPS.

    On failure the process exits with a message; this keeps callers simple.
    """
    cam    = cfg["camera"]
    source = cam["source"]
    w      = cam.get("width",     1280)
    h      = cam.get("height",    720)
    fps    = cam.get("framerate", 30)

    cap = cv2.VideoCapture(source, cv2.CAP_V4L2)

    if not cap.isOpened():
        print(f"[ERROR] Cannot open camera (source={source})")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    cap.set(cv2.CAP_PROP_FPS,          fps)

    actual_w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"[DriveSafe] Camera opened: {actual_w}x{actual_h} @ {actual_fps:.0f} FPS (MJPG)")

    return cap


class VideoCaptureAsync:
    """Wraps a VideoCapture in a daemon thread to avoid blocking the main loop."""

    def __init__(self, cap: cv2.VideoCapture) -> None:
        self.cap = cap
        self.grabbed, self.frame = self.cap.read()
        self.lock    = threading.Lock()
        self.running = False

    def start(self) -> "VideoCaptureAsync":
        self.running = True
        self.thread  = threading.Thread(target=self._update, daemon=True)
        self.thread.start()
        return self

    def _update(self) -> None:
        while self.running:
            grabbed, frame = self.cap.read()
            with self.lock:
                self.grabbed, self.frame = grabbed, frame

    def read(self):
        with self.lock:
            return self.grabbed, (self.frame.copy() if self.frame is not None else None)

    def release(self) -> None:
        self.running = False
        self.thread.join()
        self.cap.release()
