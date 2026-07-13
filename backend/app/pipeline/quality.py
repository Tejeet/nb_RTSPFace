"""Face image quality evaluation.

Rejects blurry, badly exposed, tiny or edge-clipped faces before they
reach storage, and produces a composite quality score in [0, 1] for
every accepted face.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from app.logging_setup import get_logger

logger = get_logger("pipeline.quality")


@dataclass
class QualityResult:
    """Outcome of a quality evaluation."""

    accepted: bool
    score: float
    reason: str  # "ok" or the rejection reason


class QualityEvaluator:
    """Scores face crops and gates which ones are worth storing."""

    def __init__(
        self,
        min_score: float,
        blur_threshold: float,
        brightness_min: int,
        brightness_max: int,
        min_face_size: int,
        edge_margin_ratio: float = 0.01,
    ) -> None:
        self._min_score = min_score
        self._blur_threshold = blur_threshold
        self._brightness_min = brightness_min
        self._brightness_max = brightness_max
        self._min_face_size = min_face_size
        self._edge_margin_ratio = edge_margin_ratio

    def evaluate(
        self,
        face_crop_bgr: np.ndarray,
        bbox: tuple[int, int, int, int],
        frame_shape: tuple[int, int],
    ) -> QualityResult:
        """Evaluate a face crop; frame_shape is (height, width)."""
        x, y, w, h = bbox
        frame_h, frame_w = frame_shape

        if min(w, h) < self._min_face_size:
            return QualityResult(False, 0.0, "too_small")

        margin_x = int(frame_w * self._edge_margin_ratio)
        margin_y = int(frame_h * self._edge_margin_ratio)
        if x <= margin_x or y <= margin_y or x + w >= frame_w - margin_x or (
            y + h >= frame_h - margin_y
        ):
            return QualityResult(False, 0.0, "partially_outside_frame")

        gray = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2GRAY)

        brightness = float(gray.mean())
        if brightness < self._brightness_min:
            return QualityResult(False, 0.0, "too_dark")
        if brightness > self._brightness_max:
            return QualityResult(False, 0.0, "too_bright")

        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if sharpness < self._blur_threshold:
            return QualityResult(False, 0.0, "blurry")

        score = self._composite_score(sharpness, brightness, min(w, h))
        if score < self._min_score:
            return QualityResult(False, score, "low_quality_score")
        return QualityResult(True, score, "ok")

    def _composite_score(self, sharpness: float, brightness: float, face_side: int) -> float:
        """Weighted blend of sharpness, exposure centering and face size."""
        # Sharpness: saturates at 4x the blur floor.
        sharp_score = min(1.0, sharpness / (self._blur_threshold * 4.0))

        # Exposure: 1.0 at the center of the allowed brightness band.
        band_center = (self._brightness_min + self._brightness_max) / 2.0
        band_half = (self._brightness_max - self._brightness_min) / 2.0
        exposure_score = max(0.0, 1.0 - abs(brightness - band_center) / band_half)

        # Size: saturates at 4x the minimum face size.
        size_score = min(1.0, face_side / (self._min_face_size * 4.0))

        return round(0.5 * sharp_score + 0.25 * exposure_score + 0.25 * size_score, 4)
