"""Runtime performance counters shared across pipeline workers."""

import threading
import time


class LatencyEma:
    """Exponential moving average of a latency measurement (milliseconds)."""

    def __init__(self, alpha: float = 0.1) -> None:
        self._alpha = alpha
        self._value = 0.0
        self._initialized = False

    def record(self, latency_ms: float) -> None:
        if not self._initialized:
            self._value = latency_ms
            self._initialized = True
        else:
            self._value = self._alpha * latency_ms + (1 - self._alpha) * self._value

    @property
    def value(self) -> float:
        return round(self._value, 2)


class StatsCollector:
    """Thread-safe holder for live pipeline metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = time.time()
        self.detection_latency = LatencyEma()
        self.embedding_latency = LatencyEma()
        self._processing_fps = 0.0
        self._visible_faces = 0
        self._tracked_faces = 0
        self._faces_saved = 0
        self._faces_rejected = 0

    def record_detection(self, latency_ms: float, visible: int, tracked: int) -> None:
        with self._lock:
            self.detection_latency.record(latency_ms)
            self._visible_faces = visible
            self._tracked_faces = tracked

    def record_embedding(self, latency_ms: float) -> None:
        with self._lock:
            self.embedding_latency.record(latency_ms)

    def record_processing_fps(self, fps: float) -> None:
        with self._lock:
            self._processing_fps = round(fps, 2)

    def record_face_saved(self) -> None:
        with self._lock:
            self._faces_saved += 1

    def record_face_rejected(self) -> None:
        with self._lock:
            self._faces_rejected += 1

    def snapshot(self) -> dict[str, float | int]:
        """Point-in-time copy of all counters."""
        with self._lock:
            return {
                "processing_fps": self._processing_fps,
                "visible_faces": self._visible_faces,
                "tracked_faces": self._tracked_faces,
                "faces_saved_session": self._faces_saved,
                "faces_rejected_session": self._faces_rejected,
                "detection_latency_ms": self.detection_latency.value,
                "embedding_latency_ms": self.embedding_latency.value,
                "uptime_seconds": round(time.time() - self.started_at, 1),
            }
