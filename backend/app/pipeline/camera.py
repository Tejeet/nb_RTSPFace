"""RTSP camera reader.

Runs in a dedicated thread, reconnects forever with exponential backoff,
and pushes frames into a bounded queue using drop-oldest semantics so the
capture rate is never blocked by slow downstream stages.
"""

import queue
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.logging_setup import get_logger

logger = get_logger("pipeline.camera")


@dataclass
class FramePacket:
    """One frame captured from the camera."""

    frame: np.ndarray
    frame_index: int
    captured_at: float  # time.time()


@dataclass
class CameraState:
    """Thread-safe snapshot of camera health (read by API/health monitor)."""

    connected: bool = False
    fps: float = 0.0
    frame_width: int = 0
    frame_height: int = 0
    reconnect_attempts: int = 0
    last_frame_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, **kwargs: object) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "connected": self.connected,
                "fps": self.fps,
                "frame_width": self.frame_width,
                "frame_height": self.frame_height,
                "reconnect_attempts": self.reconnect_attempts,
                "last_frame_at": self.last_frame_at,
            }


class CameraReader(threading.Thread):
    """Continuously reads an RTSP stream and feeds the frame queue."""

    def __init__(
        self,
        rtsp_url: str,
        frame_queue: "queue.Queue[FramePacket]",
        reconnect_min_delay: float,
        reconnect_max_delay: float,
    ) -> None:
        super().__init__(name="camera-reader", daemon=True)
        self._rtsp_url = rtsp_url
        self._queue = frame_queue
        self._min_delay = reconnect_min_delay
        self._max_delay = reconnect_max_delay
        self._stop_event = threading.Event()
        self.state = CameraState()

    def stop(self) -> None:
        """Signal the thread to exit."""
        self._stop_event.set()

    # -- internals -------------------------------------------------------

    def _open(self) -> cv2.VideoCapture | None:
        """Try to open the RTSP stream once."""
        capture = cv2.VideoCapture(self._rtsp_url, cv2.CAP_FFMPEG)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        if not capture.isOpened():
            capture.release()
            return None
        return capture

    def _put_frame(self, packet: FramePacket) -> None:
        """Insert with drop-oldest: the camera never blocks on consumers."""
        while True:
            try:
                self._queue.put_nowait(packet)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass

    def run(self) -> None:  # noqa: C901
        """Main loop: connect, read frames, reconnect on failure, forever."""
        delay = self._min_delay
        frame_index = 0

        while not self._stop_event.is_set():
            capture = self._open()
            if capture is None:
                self.state.update(
                    connected=False,
                    reconnect_attempts=self.state.reconnect_attempts + 1,
                )
                logger.warning(
                    "Camera connection failed; retrying in %.1fs "
                    "(attempt %d)", delay, self.state.reconnect_attempts,
                )
                self._stop_event.wait(delay)
                delay = min(delay * 2, self._max_delay)
                continue

            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.state.update(connected=True, frame_width=width, frame_height=height)
            logger.info("Camera connected (%dx%d)", width, height)
            delay = self._min_delay

            fps_counter = 0
            fps_window_start = time.monotonic()

            while not self._stop_event.is_set():
                ok, frame = capture.read()
                if not ok or frame is None:
                    logger.warning("Camera stream lost; reconnecting")
                    break

                frame_index += 1
                now = time.time()
                self._put_frame(FramePacket(frame=frame, frame_index=frame_index, captured_at=now))

                fps_counter += 1
                elapsed = time.monotonic() - fps_window_start
                if elapsed >= 2.0:
                    self.state.update(fps=fps_counter / elapsed, last_frame_at=now)
                    fps_counter = 0
                    fps_window_start = time.monotonic()

            capture.release()
            self.state.update(connected=False, fps=0.0)

        logger.info("Camera reader stopped")
