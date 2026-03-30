"""
clip.py – Danger Event Clip Recorder
Maintains a rolling buffer of video frames and automatically saves
short clips when a danger event is triggered.  Each clip captures
frames from *before* the event (pre-buffer) through *after* the event
(post-buffer), giving full context for what happened.
The clip includes the HUD overlay (bounding boxes, labels, alerts)
because frames are fed after drawing.
Usage inside ProcessingThread:
    recorder = ClipRecorder("recordings", fps=20.0)
    # every frame (after HUD draw):
    recorder.feed(frame)
    # when danger detected:
    recorder.trigger("danger")
    # on shutdown:
    recorder.release()
"""

import collections
import datetime
import os
import threading
import time

import cv2


class ClipRecorder:
    """
    Saves short video clips around danger events.
    Keeps a rolling ``collections.deque`` of the last *pre_seconds* worth
    of frames.  When ``trigger()`` is called the buffer is frozen and the
    recorder continues collecting *post_seconds* more frames, then writes
    everything to an AVI file in a background thread.
    If ``trigger()`` is called while a clip is already being built the
    post-event window is extended (up to *max_duration*), so a sustained
    danger event produces one longer clip rather than many short ones.
    A *cooldown* prevents back-to-back clips from flooding the disk.
    """

    def __init__(
        self,
        output_dir: str,
        fps: float = 20.0,
        pre_seconds: float = 3.0,
        post_seconds: float = 3.0,
        cooldown: float = 10.0,
        max_duration: float = 30.0,
    ) -> None:
        self.output_dir = output_dir
        self.fps = fps
        self.pre_seconds = pre_seconds
        self.post_seconds = post_seconds
        self.cooldown = cooldown

        buf_size = int(fps * pre_seconds) + 1
        self._buffer: collections.deque = collections.deque(maxlen=buf_size)

        self._max_clip_frames = int(fps * max_duration)

        # ── clip state ──
        self._active = False
        self._pre_snapshot: list = []
        self._post_frames: list = []
        self._post_target: int = 0
        # Per-level last-save timestamps so warning clips don't block danger clips
        self._last_save: dict = {}
        self._level: str = "danger"
        self._lock = threading.Lock()

    # ── public API ───────────────────────────────────────────────────────────

    def feed(self, frame) -> None:
        """Add a frame to the rolling buffer (or active clip).  Call once
        per processed frame, *after* drawing the HUD."""
        with self._lock:
            self._buffer.append(frame.copy())

            if self._active:
                self._post_frames.append(frame.copy())
                total = len(self._pre_snapshot) + len(self._post_frames)
                if (len(self._post_frames) >= self._post_target
                        or total >= self._max_clip_frames):
                    self._finalize()

    def trigger(self, level: str = "danger") -> bool:
        """Request a clip save.
        * First call starts a new clip (pre-buffer snapshot + post capture).
        * Subsequent calls while active extend the post-event window.
        * Returns ``False`` if suppressed by cooldown.
        """
        with self._lock:
            now = time.monotonic()

            if self._active:
                # Extend post-event window from current position
                extra = int(self.fps * self.post_seconds)
                self._post_target = len(self._post_frames) + extra
                # Escalate level if needed (warning → danger)
                if level == "danger":
                    self._level = level
                return True

            if now - self._last_save.get(level, 0.0) < self.cooldown:
                return False

            # Snapshot the pre-buffer and begin post-event capture
            self._pre_snapshot = list(self._buffer)
            self._post_frames = []
            self._post_target = int(self.fps * self.post_seconds)
            self._active = True
            self._level = level
            return True

    def release(self) -> None:
        """Flush any in-progress clip (call on shutdown)."""
        with self._lock:
            if self._active:
                self._finalize()

    # ── internals ────────────────────────────────────────────────────────────

    def _finalize(self) -> None:
        """Package and hand off frames to a writer thread (called under lock)."""
        frames = self._pre_snapshot + self._post_frames
        level = self._level

        self._pre_snapshot = []
        self._post_frames = []
        self._active = False
        self._last_save[level] = time.monotonic()

        if frames:
            threading.Thread(
                target=self._write, args=(frames, level), daemon=True
            ).start()

    def _write(self, frames: list, level: str) -> None:
        """Write frames to an AVI file (runs in a background thread)."""
        os.makedirs(self.output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"clip_{level}_{ts}.avi"
        path = os.path.join(self.output_dir, name)

        h, w = frames[0].shape[:2]
        writer = cv2.VideoWriter(
            path, cv2.VideoWriter_fourcc(*"MJPG"), self.fps, (w, h)
        )
        for f in frames:
            writer.write(f)
        writer.release()

        duration = len(frames) / self.fps
        print(f"[DriveSafe] Clip saved: {name} "
              f"({len(frames)} frames, {duration:.1f}s)")