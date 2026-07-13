"""Capture zone: an optional polygon that gates where faces are captured.

Detection and tracking always cover the full frame (stable Track IDs,
complete live view); the zone only filters the capture/save decision.
Coordinates are normalized (0..1, origin top-left) so one setting works
for any stream resolution.
"""

import numpy as np

import cv2


class CaptureZone:
    """Polygon test for face capture eligibility."""

    def __init__(self, points: list[tuple[float, float]] | None) -> None:
        """`points` are normalized (x, y) vertices; None/empty disables the zone."""
        self._norm_points = points or []
        self._cached_size: tuple[int, int] | None = None
        self._cached_polygon: np.ndarray | None = None

    @property
    def enabled(self) -> bool:
        return len(self._norm_points) >= 3

    def polygon_px(self, frame_w: int, frame_h: int) -> np.ndarray:
        """Vertices in pixel coordinates for the given frame size (cached)."""
        if self._cached_size != (frame_w, frame_h):
            self._cached_polygon = np.array(
                [[int(x * frame_w), int(y * frame_h)] for x, y in self._norm_points],
                dtype=np.int32,
            )
            self._cached_size = (frame_w, frame_h)
        return self._cached_polygon

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
            x, y = float(parts[0]), float(parts[1])
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError(f"CAPTURE_ZONE: point '{pair}' outside 0..1 range")
            points.append((x, y))
        if len(points) < 3:
            raise ValueError("CAPTURE_ZONE: a zone needs at least 3 points")
        return points
