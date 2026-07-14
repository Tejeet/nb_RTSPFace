"""Face cropping and image persistence with date-organized storage."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

from app.logging_setup import get_logger

logger = get_logger("pipeline.cropper")

THUMBNAIL_SIZE = 96


@dataclass
class SavedImage:
    """Result of writing a face crop to disk."""

    face_uuid: str
    image_path: Path
    thumbnail_path: Path
    file_size_bytes: int
    width: int
    height: int


class FaceCropper:
    """Crops faces with padding, resizes, and saves date-organized JPEGs."""

    def __init__(
        self,
        faces_dir: Path,
        thumbnails_dir: Path,
        frames_dir: Path,
        padding: float,
        output_size: int,
        jpeg_quality: int,
    ) -> None:
        self._faces_dir = faces_dir
        self._thumbnails_dir = thumbnails_dir
        self._frames_dir = frames_dir
        self._padding = padding
        self._output_size = output_size
        self._jpeg_params = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]

    def crop(self, frame_bgr: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
        """Square crop centered on the face with padding, clamped to the frame.

        The crop side is max(w, h) grown by the padding on each side, so the
        result includes context and keeps the face's aspect ratio when resized
        to the square output size (no stretching).
        """
        x, y, w, h = bbox
        frame_h, frame_w = frame_bgr.shape[:2]
        side = int(max(w, h) * (1.0 + 2.0 * self._padding))
        center_x = x + w / 2.0
        center_y = y + h / 2.0
        x1 = max(0, int(center_x - side / 2.0))
        y1 = max(0, int(center_y - side / 2.0))
        x2 = min(frame_w, x1 + side)
        y2 = min(frame_h, y1 + side)
        # Re-anchor when clamped at the right/bottom edge to keep it square.
        x1 = max(0, x2 - side)
        y1 = max(0, y2 - side)
        return frame_bgr[y1:y2, x1:x2]

    def save(self, face_crop_bgr: np.ndarray, captured_at: datetime | None = None) -> SavedImage:
        """Resize and write the crop (plus thumbnail) under faces/YYYY/MM/DD/HH/MM/."""
        when = captured_at or datetime.now(UTC)
        face_uuid = str(uuid.uuid4())

        resized = cv2.resize(
            face_crop_bgr,
            (self._output_size, self._output_size),
            interpolation=cv2.INTER_AREA,
        )

        rel_dir = Path(when.strftime("%Y")) / when.strftime("%m") / when.strftime(
            "%d"
        ) / when.strftime("%H") / when.strftime("%M")

        image_dir = self._faces_dir / rel_dir
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / f"face_{face_uuid}.jpg"
        cv2.imwrite(str(image_path), resized, self._jpeg_params)

        thumb_dir = self._thumbnails_dir / rel_dir
        thumb_dir.mkdir(parents=True, exist_ok=True)
        thumbnail_path = thumb_dir / f"face_{face_uuid}.jpg"
        thumbnail = cv2.resize(
            resized, (THUMBNAIL_SIZE, THUMBNAIL_SIZE), interpolation=cv2.INTER_AREA
        )
        cv2.imwrite(str(thumbnail_path), thumbnail, self._jpeg_params)

        return SavedImage(
            face_uuid=face_uuid,
            image_path=image_path,
            thumbnail_path=thumbnail_path,
            file_size_bytes=image_path.stat().st_size,
            width=self._output_size,
            height=self._output_size,
        )

    def save_frame_jpeg(self, jpeg_bytes: bytes, face_uuid: str, when: datetime) -> Path:
        """Write the pre-encoded full camera frame next to a captured face."""
        rel_dir = Path(when.strftime("%Y")) / when.strftime("%m") / when.strftime(
            "%d"
        ) / when.strftime("%H") / when.strftime("%M")
        frame_dir = self._frames_dir / rel_dir
        frame_dir.mkdir(parents=True, exist_ok=True)
        frame_path = frame_dir / f"frame_{face_uuid}.jpg"
        frame_path.write_bytes(jpeg_bytes)
        return frame_path
