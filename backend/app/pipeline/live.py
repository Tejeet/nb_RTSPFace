"""Shared buffer holding the latest annotated frame for the live MJPEG view."""

import threading
import time

import cv2
import numpy as np

from app.pipeline.tracker import Track

OVERLAY_COLOR = (80, 220, 80)
OVERLAY_TEXT = (255, 255, 255)


class LiveFrameBuffer:
    """Latest annotated JPEG, written by the detection worker, read by the API."""

    def __init__(self, target_width: int, max_fps: float, jpeg_quality: int = 70) -> None:
        self._target_width = target_width
        self._min_interval = 1.0 / max_fps
        self._jpeg_params = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._updated_at = 0.0

    def update(
        self,
        frame_bgr: np.ndarray,
        tracks: list[Track],
        fps: float,
        camera_name: str,
    ) -> None:
        """Annotate and encode the frame if enough time has passed (rate-capped)."""
        now = time.monotonic()
        if now - self._updated_at < self._min_interval:
            return

        height, width = frame_bgr.shape[:2]
        scale = self._target_width / width if width > self._target_width else 1.0
        display = (
            cv2.resize(frame_bgr, (int(width * scale), int(height * scale)))
            if scale < 1.0
            else frame_bgr.copy()
        )

        for track in tracks:
            x, y, w, h = track.bbox
            x1, y1 = int(x * scale), int(y * scale)
            x2, y2 = int((x + w) * scale), int((y + h) * scale)
            cv2.rectangle(display, (x1, y1), (x2, y2), OVERLAY_COLOR, 2)
            label = f"ID {track.track_id} {track.score:.2f}"
            cv2.putText(
                display, label, (x1, max(14, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, OVERLAY_COLOR, 1, cv2.LINE_AA,
            )

        banner = f"{camera_name}  |  {fps:.1f} FPS  |  faces: {len(tracks)}"
        cv2.putText(
            display, banner, (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX, 0.65, OVERLAY_TEXT, 2, cv2.LINE_AA,
        )

        ok, encoded = cv2.imencode(".jpg", display, self._jpeg_params)
        if ok:
            with self._lock:
                self._jpeg = encoded.tobytes()
                self._updated_at = now

    def latest(self) -> bytes | None:
        """Most recent encoded frame, or None before first frame."""
        with self._lock:
            return self._jpeg
