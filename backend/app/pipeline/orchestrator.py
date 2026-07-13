"""Pipeline orchestrator.

Owns every worker thread and queue, wires them together, and exposes the
read-only views (live buffer, stats, health) consumed by the API layer.
Designed so additional cameras become additional CameraReader +
DetectionWorker pairs feeding the same embedding/storage stages.
"""

import queue

from app.config import Settings
from app.db.repository import FaceRepository
from app.db.session import DatabaseManager
from app.logging_setup import get_logger
from app.pipeline.camera import CameraReader, FramePacket
from app.pipeline.cropper import FaceCropper
from app.pipeline.detector import FaceModels
from app.pipeline.events import EventBus
from app.pipeline.health import HealthMonitor
from app.pipeline.live import LiveFrameBuffer
from app.pipeline.quality import QualityEvaluator
from app.pipeline.stats import StatsCollector
from app.pipeline.tracker import ByteTracker
from app.pipeline.vector_store import VectorStore
from app.pipeline.workers import CaptureJob, DetectionWorker, EmbeddingWorker, PersistJob, StorageWorker

logger = get_logger("pipeline.orchestrator")


class Pipeline:
    """Composition root for the face capture pipeline."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_directories()

        # Shared services
        self.db = DatabaseManager(settings.sqlite_path)
        self.db.create_schema()
        self.repository = FaceRepository(self.db)
        self.camera_id = self.repository.upsert_camera(settings.camera_name, settings.rtsp_url)

        self.event_bus = EventBus()
        self.stats = StatsCollector()

        # Models (loaded once; shared by detection worker and search API)
        self.models = FaceModels(
            model_pack=settings.embedding_model,
            models_dir=settings.models_dir,
            detection_size=settings.detection_size,
            detection_confidence=settings.detection_confidence,
            min_face_size=settings.min_face_size,
        )

        self.vector_store = VectorStore(
            index_path=settings.faiss_index_path,
            dim=self.models.embedding_dim,
            save_interval=settings.faiss_save_interval,
        )

        # Queues (bounded)
        self.frame_queue: queue.Queue[FramePacket] = queue.Queue(settings.frame_queue_size)
        self.embed_queue: queue.Queue[CaptureJob | None] = queue.Queue(settings.embed_queue_size)
        self.persist_queue: queue.Queue[PersistJob | None] = queue.Queue(
            settings.persist_queue_size
        )

        # Stage components
        self.tracker = ByteTracker(
            match_iou=settings.track_match_iou,
            min_hits=settings.track_min_hits,
            max_lost_frames=settings.track_max_lost_frames,
            low_score_threshold=settings.track_low_score_threshold,
            high_score_threshold=settings.detection_confidence,
        )
        self.quality = QualityEvaluator(
            min_score=settings.quality_min_score,
            blur_threshold=settings.quality_blur_threshold,
            brightness_min=settings.quality_brightness_min,
            brightness_max=settings.quality_brightness_max,
            min_face_size=settings.min_face_size,
        )
        self.cropper = FaceCropper(
            faces_dir=settings.faces_dir,
            thumbnails_dir=settings.thumbnails_dir,
            padding=settings.face_crop_padding,
            output_size=settings.face_crop_size,
            jpeg_quality=settings.jpeg_quality,
        )
        self.live_buffer = LiveFrameBuffer(
            target_width=settings.live_stream_width,
            max_fps=settings.live_stream_fps,
        )

        # Workers
        self.camera = CameraReader(
            rtsp_url=settings.rtsp_url,
            frame_queue=self.frame_queue,
            reconnect_min_delay=settings.camera_reconnect_min_delay,
            reconnect_max_delay=settings.camera_reconnect_max_delay,
        )
        self.detection_worker = DetectionWorker(
            settings=settings,
            frame_queue=self.frame_queue,
            embed_queue=self.embed_queue,
            models=self.models,
            tracker=self.tracker,
            quality=self.quality,
            cropper=self.cropper,
            live_buffer=self.live_buffer,
            stats=self.stats,
            camera_fps=lambda: self.camera.state.fps,
        )
        self.embedding_worker = EmbeddingWorker(
            embed_queue=self.embed_queue,
            persist_queue=self.persist_queue,
            models=self.models,
            stats=self.stats,
        )
        self.storage_worker = StorageWorker(
            settings=settings,
            persist_queue=self.persist_queue,
            cropper=self.cropper,
            repository=self.repository,
            vector_store=self.vector_store,
            event_bus=self.event_bus,
            stats=self.stats,
            camera_id=self.camera_id,
        )
        self.health_monitor = HealthMonitor(
            pipeline=self,
            storage_root=settings.storage_root,
            interval=settings.stats_interval,
        )

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start all worker threads."""
        logger.info("Starting pipeline (camera=%s)", self.settings.camera_name)
        self.camera.start()
        self.detection_worker.start()
        self.embedding_worker.start()
        self.storage_worker.start()
        self.health_monitor.start()
        logger.info("Pipeline running")

    def stop(self) -> None:
        """Stop workers in dependency order and flush state to disk."""
        logger.info("Stopping pipeline")
        self.health_monitor.stop()
        self.camera.stop()
        self.detection_worker.stop()
        self.detection_worker.join(timeout=5)
        self.embedding_worker.stop()
        self.embedding_worker.join(timeout=10)
        self.storage_worker.stop()
        self.storage_worker.join(timeout=10)
        self.camera.join(timeout=5)
        self.vector_store.save()
        self.db.dispose()
        logger.info("Pipeline stopped")

    # -- read views for the API -----------------------------------------------

    def queue_sizes(self) -> dict[str, int]:
        """Current depth of each inter-stage queue."""
        return {
            "frames": self.frame_queue.qsize(),
            "embeddings": self.embed_queue.qsize(),
            "persistence": self.persist_queue.qsize(),
        }

    def live_status(self) -> dict[str, object]:
        """Realtime status for the live view page."""
        camera = self.camera.state.snapshot()
        pipeline = self.stats.snapshot()
        return {
            "camera_connected": camera["connected"],
            "camera_name": self.settings.camera_name,
            "fps": camera["fps"],
            "visible_faces": pipeline["visible_faces"],
            "tracked_faces": pipeline["tracked_faces"],
            "frame_width": camera["frame_width"],
            "frame_height": camera["frame_height"],
        }

    def statistics(self) -> dict[str, object]:
        """Aggregate stats for the dashboard and WebSocket broadcast."""
        pipeline = self.stats.snapshot()
        system = self.health_monitor.system_metrics()
        counts = self.repository.counts_summary()
        camera = self.camera.state.snapshot()
        return {
            "faces_total": counts["total"],
            "faces_today": counts["today"],
            "faces_last_hour": counts["last_hour"],
            "current_tracks": pipeline["tracked_faces"],
            "fps": camera["fps"],
            "processing_fps": pipeline["processing_fps"],
            "detection_latency_ms": pipeline["detection_latency_ms"],
            "embedding_latency_ms": pipeline["embedding_latency_ms"],
            "faces_saved_session": pipeline["faces_saved_session"],
            "faces_rejected_session": pipeline["faces_rejected_session"],
            "uptime_seconds": pipeline["uptime_seconds"],
            "queues": self.queue_sizes(),
            **system,
        }

    def health(self) -> dict[str, object]:
        """Deep health check used by /api/health and container healthchecks."""
        database_ok = True
        try:
            self.repository.count_faces_total()
        except Exception:
            database_ok = False

        camera = self.camera.state.snapshot()
        system = self.health_monitor.system_metrics()
        healthy = database_ok and bool(camera["connected"])
        return {
            "status": "healthy" if healthy else "degraded",
            "camera_connected": camera["connected"],
            "fps": camera["fps"],
            "database_ok": database_ok,
            "faiss_ok": True,
            "faiss_vectors": self.vector_store.count,
            "embedding_model_loaded": self.models is not None,
            "queues": self.queue_sizes(),
            "cpu_percent": system["cpu_percent"],
            "ram_percent": system["ram_percent"],
            "disk_percent": system["disk_percent"],
            "temperature_c": system["temperature_c"],
            "uptime_seconds": self.stats.snapshot()["uptime_seconds"],
        }
