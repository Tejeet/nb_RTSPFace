"""Capture zone: an optional polygon that gates where faces are captured.

Detection and tracking always cover the full frame (stable Track IDs,
complete live view); the zone only filters the capture/save decision.
Coordinates are normalized (0..1, origin top-left) so one setting works
for any stream resolution.

The zone is mutable at runtime (edited from the dashboard) and shared
between the detection worker and API handlers, hence the lock.
"""

import threading

import numpy as np

import cv2


class CaptureZone:
    """Thread-safe polygon test for face capture eligibility."""

    def __init__(self, points: list[tuple[float, float]] | None) -> None:
        """`points` are normalized (x, y) vertices; None/empty disables the zone."""
        self._lock = threading.Lock()
        self._norm_points: list[tuple[float, float]] = []
        self._cache: dict[tuple[int, int], np.ndarray] = {}
        self.set_points(points)

    @property
    def enabled(self) -> bool:
        with self._lock:
            return len(self._norm_points) >= 3

    def get_points(self) -> list[tuple[float, float]]:
        """Current normalized vertices (empty when disabled)."""
        with self._lock:
            return list(self._norm_points)

    def set_points(self, points: list[tuple[float, float]] | None) -> None:
        """Replace the zone polygon (None/empty disables it)."""
        with self._lock:
            self._norm_points = [(float(x), float(y)) for x, y in (points or [])]
            self._cache.clear()

    def polygon_px(self, frame_w: int, frame_h: int) -> np.ndarray:
        """Vertices in pixel coordinates for the given frame size (cached)."""
        key = (frame_w, frame_h)
        with self._lock:
            polygon = self._cache.get(key)
            if polygon is None:
                polygon = np.array(
                    [[int(x * frame_w), int(y * frame_h)] for x, y in self._norm_points],
                    dtype=np.int32,
                )
                self._cache[key] = polygon
            return polygon

    def contains_bbox(
        self, bbox: tuple[int, int, int, int], frame_w: int, frame_h: int
    ) -> bool:
        """True when the face box center lies inside the zone (or zone disabled)."""
        if not self.enabled:
            return True
        x, y, w, h = bbox
        center = (float(x + w / 2), float(y + h / 2))
        polygon = self.polygon_px(frame_w, frame_h)
        return cv2.pointPolygonTest(polygon, center, measureDist=False) >= 0

    @staticmethod
    def validate_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """Validate vertices; empty list = disabled. Raises ValueError otherwise."""
        if not points:
            return []
        if len(points) < 3:
            raise ValueError("A capture zone needs at least 3 points")
        cleaned: list[tuple[float, float]] = []
        for x, y in points:
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError(f"Zone point ({x}, {y}) outside the 0..1 range")
            cleaned.append((float(x), float(y)))
        return cleaned

    @staticmethod
    def parse(spec: str) -> list[tuple[float, float]]:
        """Parse "x1,y1;x2,y2;…" (normalized 0..1) into vertex tuples.

        Empty string → no zone. Raises ValueError on malformed input so a
        bad configuration fails at startup, not silently at runtime.
        """
        spec = spec.strip()
        if not spec:
            return []
        points: list[tuple[float, float]] = []
        for pair in spec.split(";"):
            parts = pair.split(",")
            if len(parts) != 2:
                raise ValueError(f"CAPTURE_ZONE: bad point '{pair}' (expected 'x,y')")
            points.append((float(parts[0]), float(parts[1])))
        return CaptureZone.validate_points(points)
