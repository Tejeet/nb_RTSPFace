"""Pipeline worker threads.

DetectionWorker : frames → detections → tracks → capture decisions
EmbeddingWorker : aligned crops → 512-d embeddings
StorageWorker   : images + embeddings → disk, SQLite, FAISS, WebSocket events

Workers communicate only through bounded queues; a slow stage drops work
instead of blocking the camera.
"""

import queue
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.config import Settings
from app.db.models import Face
from app.db.repository import FaceRepository
from app.logging_setup import get_logger
from app.pipeline.camera import FramePacket
from app.pipeline.cropper import FaceCropper
from app.pipeline.detector import FaceModels
from app.pipeline.events import EventBus
from app.pipeline.live import LiveFrameBuffer
from app.pipeline.quality import QualityEvaluator
from app.pipeline.stats import StatsCollector
from app.pipeline.tracker import ByteTracker

logger = get_logger("pipeline.workers")

_SENTINEL = None


@dataclass
class CaptureJob:
    """A quality-approved face crop awaiting embedding."""

    face_crop: np.ndarray  # padded crop (for saving)
    aligned: np.ndarray  # 112x112 aligned crop (for embedding)
    bbox: tuple[int, int, int, int]
    track_id: int
    detection_confidence: float
    quality_score: float
    captured_at: datetime


@dataclass
class PersistJob:
    """A capture with its embedding, ready to persist."""

    capture: CaptureJob
    embedding: np.ndarray


class DetectionWorker(threading.Thread):
    """Detects, tracks and selects faces worth capturing."""

    def __init__(
        self,
        settings: Settings,
        frame_queue: "queue.Queue[FramePacket]",
        embed_queue: "queue.Queue[CaptureJob | None]",
        models: FaceModels,
        tracker: ByteTracker,
        quality: QualityEvaluator,
        cropper: FaceCropper,
        live_buffer: LiveFrameBuffer,
        stats: StatsCollector,
        camera_fps: "callable",
    ) -> None:
        super().__init__(name="detection-worker", daemon=True)
        self._settings = settings
        self._frame_queue = frame_queue
        self._embed_queue = embed_queue
        self._models = models
        self._tracker = tracker
        self._quality = quality
        self._cropper = cropper
        self._live = live_buffer
        self._stats = stats
        self._camera_fps = camera_fps
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        frame_counter = 0
        processed = 0
        window_start = time.monotonic()

        while not self._stop_event.is_set():
            try:
                packet = self._frame_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            frame_counter += 1
            if frame_counter % self._settings.detect_every_n_frames != 0:
                continue

            try:
                self._process_frame(packet)
            except Exception:
                logger.exception("Detection failed on frame %d", packet.frame_index)

            processed += 1
            elapsed = time.monotonic() - window_start
            if elapsed >= 2.0:
                self._stats.record_processing_fps(processed / elapsed)
                processed = 0
                window_start = time.monotonic()

        logger.info("Detection worker stopped")

    def _process_frame(self, packet: FramePacket) -> None:
        started = time.perf_counter()
        detections = self._models.detect(packet.frame)
        tracks = self._tracker.update(detections)
        latency_ms = (time.perf_counter() - started) * 1000.0
        self._stats.record_detection(latency_ms, len(tracks), self._tracker.tracked_count)

        now = time.time()
        for track in tracks:
            due = (
                track.last_saved_at == 0.0
                or now - track.last_saved_at >= self._settings.save_interval_seconds
            )
            if not due:
                continue

            face_crop = self._cropper.crop(packet.frame, track.bbox)
            result = self._quality.evaluate(face_crop, track.bbox, packet.frame.shape[:2])
            if not result.accepted:
                self._stats.record_face_rejected()
                logger.debug("Track %d rejected: %s", track.track_id, result.reason)
                continue  # retry on a later frame

            track.last_saved_at = now
            job = CaptureJob(
                face_crop=face_crop.copy(),
                aligned=self._models.align(packet.frame, track.kps),
                bbox=track.bbox,
                track_id=track.track_id,
                detection_confidence=track.score,
                quality_score=result.score,
                captured_at=datetime.now(UTC),
            )
            try:
                self._embed_queue.put_nowait(job)
                logger.info(
                    "Face captured: track=%d quality=%.2f conf=%.2f",
                    track.track_id, result.score, track.score,
                )
            except queue.Full:
                track.last_saved_at = 0.0  # give it another chance later
                logger.warning("Embed queue full; capture for track %d dropped",
                               track.track_id)

        self._live.update(packet.frame, tracks, self._camera_fps(), self._settings.camera_name)


class EmbeddingWorker(threading.Thread):
    """Computes ArcFace embeddings for captured faces."""

    def __init__(
        self,
        embed_queue: "queue.Queue[CaptureJob | None]",
        persist_queue: "queue.Queue[PersistJob | None]",
        models: FaceModels,
        stats: StatsCollector,
    ) -> None:
        super().__init__(name="embedding-worker", daemon=True)
        self._embed_queue = embed_queue
        self._persist_queue = persist_queue
        self._models = models
        self._stats = stats

    def stop(self) -> None:
        self._embed_queue.put(_SENTINEL)

    def run(self) -> None:
        while True:
            job = self._embed_queue.get()
            if job is _SENTINEL:
                break
            try:
                started = time.perf_counter()
                embedding = self._models.embed_aligned(job.aligned)
                self._stats.record_embedding((time.perf_counter() - started) * 1000.0)
                self._persist_queue.put(PersistJob(capture=job, embedding=embedding), timeout=5)
            except queue.Full:
                logger.warning("Persist queue full; capture dropped (track=%d)", job.track_id)
            except Exception:
                logger.exception("Embedding failed (track=%d)", job.track_id)
        logger.info("Embedding worker stopped")


class StorageWorker(threading.Thread):
    """Persists captures: image files, embedding files, SQLite row, FAISS."""

    def __init__(
        self,
        settings: Settings,
        persist_queue: "queue.Queue[PersistJob | None]",
        cropper: FaceCropper,
        repository: FaceRepository,
        vector_store,  # VectorStore; untyped to avoid import cycle in tooling
        event_bus: EventBus,
        stats: StatsCollector,
        camera_id: int,
    ) -> None:
        super().__init__(name="storage-worker", daemon=True)
        self._settings = settings
        self._persist_queue = persist_queue
        self._cropper = cropper
        self._repo = repository
        self._vectors = vector_store
        self._events = event_bus
        self._stats = stats
        self._camera_id = camera_id

    def stop(self) -> None:
        self._persist_queue.put(_SENTINEL)

    def run(self) -> None:
        while True:
            job = self._persist_queue.get()
            if job is _SENTINEL:
                break
            try:
                self._persist(job)
            except Exception:
                logger.exception("Persistence failed (track=%d)", job.capture.track_id)
        self._vectors.save()
        logger.info("Storage worker stopped")

    def _persist(self, job: PersistJob) -> None:
        capture = job.capture

        saved = self._cropper.save(capture.face_crop, capture.captured_at)

        embedding_path = self._embedding_path(saved.face_uuid, capture.captured_at)
        embedding_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(embedding_path, job.embedding)

        # Duplicate check runs BEFORE insertion so the face never matches itself.
        matches = self._vectors.search(job.embedding, top_k=3)
        duplicates = [
            (face_id, sim) for face_id, sim in matches
            if sim >= self._settings.duplicate_threshold
        ]

        x, y, w, h = capture.bbox
        face = self._repo.insert_face(
            Face(
                uuid=saved.face_uuid,
                camera_id=self._camera_id,
                track_id=capture.track_id,
                captured_at=capture.captured_at,
                image_path=str(saved.image_path),
                thumbnail_path=str(saved.thumbnail_path),
                embedding_path=str(embedding_path),
                detection_confidence=round(capture.detection_confidence, 4),
                quality_score=capture.quality_score,
                bbox_x=x, bbox_y=y, bbox_w=w, bbox_h=h,
                image_width=saved.width,
                image_height=saved.height,
                file_size_bytes=saved.file_size_bytes,
                embedding_model=self._settings.embedding_model,
                is_possible_duplicate=1 if duplicates else 0,
            )
        )

        for matched_id, similarity in duplicates:
            self._repo.insert_duplicate_link(face.id, matched_id, round(similarity, 4))

        self._vectors.add(face.id, job.embedding)
        self._stats.record_face_saved()
        logger.info(
            "Face saved: id=%d uuid=%s track=%d duplicates=%d",
            face.id, saved.face_uuid, capture.track_id, len(duplicates),
        )

        self._events.publish(
            "face_captured",
            {
                "id": face.id,
                "uuid": face.uuid,
                "track_id": face.track_id,
                "captured_at": capture.captured_at.isoformat(),
                "quality_score": face.quality_score,
                "detection_confidence": face.detection_confidence,
                "is_possible_duplicate": face.is_possible_duplicate,
                "camera_id": self._camera_id,
                "thumbnail_url": f"/api/faces/{face.id}/thumbnail",
                "image_url": f"/api/faces/{face.id}/image",
            },
        )

    def _embedding_path(self, face_uuid: str, when: datetime) -> Path:
        rel = Path(when.strftime("%Y")) / when.strftime("%m") / when.strftime("%d")
        return self._settings.embeddings_dir / rel / f"{face_uuid}.npy"
