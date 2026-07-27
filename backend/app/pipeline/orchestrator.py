"""Pipeline orchestrator.

Owns every worker thread and queue, wires them together, and exposes the
read-only views (live buffer, stats, health) consumed by the API layer.
Designed so additional cameras become additional CameraReader +
DetectionWorker pairs feeding the same embedding/storage stages.
"""

import json
import queue

from app.config import Settings
from app.db.repository import FaceRepository
from app.db.session import DatabaseManager
from app.logging_setup import get_logger
from app.pipeline.camera_pipeline import CameraPipeline
from app.pipeline.cropper import FaceCropper
from app.pipeline.detector import FaceModels, npu_runtime_available, resolve_providers
from app.pipeline.enrollment import PersonManager
from app.pipeline.events import EventBus
from app.pipeline.health import HealthMonitor
from app.pipeline.quality import QualityEvaluator
from app.pipeline.stats import StatsCollector
from app.pipeline.vector_store import VectorStore
from app.pipeline.workers import CaptureJob, EmbeddingWorker, PersistJob, StorageWorker
from app.pipeline.zone import CaptureZone
from app.runtime_settings import RuntimeSettings

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
        # First run: seed the camera table from the RTSP_URL env so existing
        # single-camera setups keep working; afterwards cameras are managed
        # from the dashboard and this seed is skipped.
        if self.repository.count_cameras() == 0:
            self.repository.upsert_camera(settings.camera_name, settings.rtsp_url)

        self.event_bus = EventBus()

        # Inference backend: dashboard-saved value overrides the env default.
        self.runtime_settings = RuntimeSettings(settings.database_dir / "settings.json")
        self.inference_backend = str(
            self.runtime_settings.get("inference_backend", settings.inference_backend)
        )
        self.npu_active = False
        self.hailo_active = False
        self.backend_error: str | None = None

        # Models (loaded once; shared by detection worker and search API)
        self.models = self._build_models()

        self.vector_store = VectorStore(
            index_path=settings.faiss_index_path,
            dim=self.models.embedding_dim,
            save_interval=settings.faiss_save_interval,
        )

        # Enrolled-person recognition (separate index from captures).
        self.person_manager = PersonManager(
            index_path=settings.persons_faiss_path,
            dim=self.models.embedding_dim,
            threshold=settings.recognition_threshold,
            save_interval=settings.faiss_save_interval,
        )

        # Shared queues (bounded): every camera feeds these single back-end stages.
        self.embed_queue: queue.Queue[CaptureJob | None] = queue.Queue(settings.embed_queue_size)
        self.persist_queue: queue.Queue[PersistJob | None] = queue.Queue(
            settings.persist_queue_size
        )

        # Shared stage components
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
            frames_dir=settings.frames_dir,
            padding=settings.face_crop_padding,
            output_size=settings.face_crop_size,
            jpeg_quality=settings.jpeg_quality,
        )
        # One capture zone per camera (persisted as zone-<camera_id>.json).
        self.capture_zones: dict[int, CaptureZone] = {}

        # One CameraPipeline per configured camera, all feeding embed_queue.
        self.camera_pipelines: dict[int, CameraPipeline] = {}
        for cam in self.repository.list_cameras():
            zone = CaptureZone(self._load_zone_points(cam.id))
            self.capture_zones[cam.id] = zone
            if zone.enabled:
                logger.info("Camera %d capture zone: %s", cam.id, zone.get_points())
            self.camera_pipelines[cam.id] = CameraPipeline(
                camera_id=cam.id,
                camera_name=cam.name,
                rtsp_url=cam.rtsp_url,
                settings=settings,
                models=self.models,
                cropper=self.cropper,
                quality=self.quality,
                embed_queue=self.embed_queue,
                zone=zone,
            )
        logger.info("Configured %d camera(s): %s",
                    len(self.camera_pipelines),
                    ", ".join(p.camera_name for p in self.camera_pipelines.values()))

        # Shared back-end workers
        self.embedding_worker = EmbeddingWorker(
            embed_queue=self.embed_queue,
            persist_queue=self.persist_queue,
            models=self.models,
            stats=self._first_stats(),
        )
        self.storage_worker = StorageWorker(
            settings=settings,
            persist_queue=self.persist_queue,
            cropper=self.cropper,
            repository=self.repository,
            vector_store=self.vector_store,
            person_manager=self.person_manager,
            event_bus=self.event_bus,
            stats=self._first_stats(),
        )
        self.health_monitor = HealthMonitor(
            pipeline=self,
            storage_root=settings.storage_root,
            interval=settings.stats_interval,
        )

    def _first_stats(self) -> StatsCollector:
        """A stats collector for the shared back-end workers.

        Embedding latency is global (one accelerator), so any camera's
        collector works; fall back to a standalone one if no camera exists.
        """
        if self.camera_pipelines:
            return next(iter(self.camera_pipelines.values())).stats
        return StatsCollector()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start all camera pipelines and the shared back-end workers."""
        logger.info("Starting pipeline (%d camera(s))", len(self.camera_pipelines))
        self.embedding_worker.start()
        self.storage_worker.start()
        for pipe in self.camera_pipelines.values():
            pipe.start()
        self.health_monitor.start()
        logger.info("Pipeline running")

    def stop(self) -> None:
        """Stop workers in dependency order and flush state to disk."""
        logger.info("Stopping pipeline")
        self.health_monitor.stop()
        for pipe in self.camera_pipelines.values():
            pipe.stop()
        for pipe in self.camera_pipelines.values():
            pipe.join(timeout=5)
        self.embedding_worker.stop()
        self.embedding_worker.join(timeout=10)
        self.storage_worker.stop()
        self.storage_worker.join(timeout=10)
        self.vector_store.save()
        self.person_manager.save()
        if hasattr(self.models, "close"):
            self.models.close()  # release the accelerator, if one is in use
        self.db.dispose()
        logger.info("Pipeline stopped")

    # -- model construction --------------------------------------------------------

    def _build_models(self):
        """Build the inference backend, falling back to CPU on any failure.

        A misconfigured accelerator must never stop the capture engine: the
        reason is recorded in `backend_error` and surfaced on the Settings
        page instead of crashing the container.
        """
        settings = self.settings

        if self.inference_backend == "hailo":
            models = self._try_build_hailo()
            if models is not None:
                return models

        providers, self.npu_active = resolve_providers(
            "npu" if self.inference_backend == "npu" else "cpu"
        )
        return FaceModels(
            model_pack=settings.embedding_model,
            models_dir=settings.models_dir,
            detection_size=settings.detection_size,
            detection_confidence=settings.detection_confidence,
            min_face_size=settings.min_face_size,
            providers=providers,
        )

    def _try_build_hailo(self):
        """Attempt to load the Hailo backend; returns None (and logs) on failure."""
        settings = self.settings
        try:
            from app.pipeline.hailo_models import HailoFaceModels
            from app.pipeline.hailo_runtime import (
                hailo_device_present,
                hailo_import_error,
            )

            import_error = hailo_import_error()
            if import_error is not None:
                # Surface the real reason (missing package vs missing/mismatched
                # native libhailort.so) so the Settings page is actionable.
                raise RuntimeError(f"{import_error} — see docs/DEPLOYMENT.md")
            if not hailo_device_present():
                raise RuntimeError(
                    "/dev/hailo0 not found — load the hailo_pci driver on the host and "
                    "map the device into the container"
                )

            detection_hef = settings.hailo_detection_hef_path
            if not detection_hef.exists():
                raise RuntimeError(f"Detection HEF not found at {detection_hef}")

            recognition_hef = settings.hailo_recognition_hef_path
            if recognition_hef is not None and not recognition_hef.exists():
                logger.warning(
                    "Recognition HEF %s missing; using CPU for embeddings", recognition_hef
                )
                recognition_hef = None

            models = HailoFaceModels(
                detection_hef=detection_hef,
                detection_confidence=settings.detection_confidence,
                min_face_size=settings.min_face_size,
                models_dir=settings.models_dir,
                model_pack=settings.embedding_model,
                recognition_hef=recognition_hef,
            )
            self.hailo_active = True
            self.backend_error = None
            logger.info("Hailo-8 acceleration active")
            return models
        except Exception as error:  # noqa: BLE001 - must degrade, never crash
            self.backend_error = str(error)
            logger.warning("Hailo backend unavailable (%s); falling back to CPU", error)
            return None

    # -- inference settings ------------------------------------------------------

    def inference_info(self) -> dict[str, object]:
        """Current + requested inference backend state for the Settings page."""
        requested = str(
            self.runtime_settings.get("inference_backend", self.settings.inference_backend)
        )
        from app.pipeline.hailo_runtime import (
            hailo_device_present,
            hailo_runtime_installed,
        )

        # What actually loaded may differ from what was requested (fallback).
        if self.hailo_active:
            running = "hailo"
        elif self.npu_active:
            running = "npu"
        else:
            running = "cpu"

        return {
            "inference_backend": requested,
            "running_backend": running,
            "npu_active": self.npu_active,
            "npu_runtime_available": npu_runtime_available(),
            "hailo_active": self.hailo_active,
            "hailo_runtime_available": hailo_runtime_installed(),
            "hailo_device_present": hailo_device_present(),
            "backend_error": self.backend_error,
            "active_providers": self.models.active_providers,
            "requires_restart": requested != self.inference_backend,
            "model_pack": self.settings.embedding_model,
            "detection_size": self.settings.detection_size,
        }

    def set_inference_backend(self, backend: str) -> None:
        """Persist the backend choice; applied on the next backend restart."""
        if backend not in ("cpu", "npu", "hailo"):
            raise ValueError("inference_backend must be 'cpu', 'npu' or 'hailo'")
        self.runtime_settings.set("inference_backend", backend)

    # -- capture zone (per camera) ---------------------------------------------

    def _zone_file(self, camera_id: int):  # noqa: ANN202 (Path; kept terse)
        return self.settings.database_dir / f"zone-{camera_id}.json"

    def _load_zone_points(self, camera_id: int) -> list[tuple[float, float]]:
        """Saved per-camera zone if present, else the CAPTURE_ZONE env default."""
        path = self._zone_file(camera_id)
        # Migrate the pre-multicamera single zone.json onto the first camera.
        legacy = self.settings.database_dir / "zone.json"
        if not path.exists() and legacy.exists():
            path = legacy
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return CaptureZone.validate_points(
                    [(float(p[0]), float(p[1])) for p in data.get("points", [])]
                )
            except (ValueError, KeyError, IndexError, json.JSONDecodeError):
                logger.exception("Invalid zone file %s; falling back to env", path)
        return CaptureZone.parse(self.settings.capture_zone)

    def get_capture_zone(self, camera_id: int | None) -> CaptureZone | None:
        """The zone for a camera (first camera when id omitted)."""
        if camera_id is None:
            return next(iter(self.capture_zones.values()), None)
        return self.capture_zones.get(camera_id)

    def set_capture_zone(self, points: list[tuple[float, float]], camera_id: int) -> None:
        """Apply and persist a camera's capture zone (empty list disables it)."""
        zone = self.capture_zones.get(camera_id)
        if zone is None:
            raise ValueError(f"Unknown camera id {camera_id}")
        validated = CaptureZone.validate_points(points)
        zone.set_points(validated)
        self._zone_file(camera_id).write_text(json.dumps({"points": validated}))
        logger.info("Camera %d capture zone updated: %d points", camera_id, len(validated))

    # -- read views for the API -----------------------------------------------

    def queue_sizes(self) -> dict[str, int]:
        """Current depth of each inter-stage queue (frames summed per camera)."""
        return {
            "frames": sum(p._frame_queue.qsize() for p in self.camera_pipelines.values()),
            "embeddings": self.embed_queue.qsize(),
            "persistence": self.persist_queue.qsize(),
        }

    def get_camera_pipeline(self, camera_id: int | None) -> CameraPipeline | None:
        """A specific camera pipeline, or the first one when id is omitted."""
        if camera_id is not None:
            return self.camera_pipelines.get(camera_id)
        return next(iter(self.camera_pipelines.values()), None)

    def camera_statuses(self) -> list[dict[str, object]]:
        """Per-camera realtime status (one entry per configured camera)."""
        return [p.live_status() for p in self.camera_pipelines.values()]

    def live_status(self, camera_id: int | None = None) -> dict[str, object]:
        """Realtime status for one camera (first camera by default)."""
        pipe = self.get_camera_pipeline(camera_id)
        if pipe is None:
            return {
                "camera_id": 0, "camera_name": "—", "camera_connected": False,
                "fps": 0.0, "faces_in_frame": 0, "visible_faces": 0,
                "tracked_faces": 0, "frame_width": 0, "frame_height": 0,
            }
        return pipe.live_status()

    def running_backend(self) -> str:
        """Which inference backend actually loaded: 'cpu' | 'npu' | 'hailo'."""
        if self.hailo_active:
            return "hailo"
        if self.npu_active:
            return "npu"
        return "cpu"

    def backend_label(self) -> str:
        """Human-friendly name of the active processing hardware."""
        return {
            "hailo": "Hailo-8",
            "npu": "NPU",
            "cpu": "CPU",
        }[self.running_backend()]

    def statistics(self) -> dict[str, object]:
        """Aggregate stats across all cameras for the dashboard broadcast."""
        system = self.health_monitor.system_metrics()
        counts = self.repository.counts_summary()
        snaps = [p.stats.snapshot() for p in self.camera_pipelines.values()]
        cams = [p.camera.state.snapshot() for p in self.camera_pipelines.values()]

        def _sum(key: str) -> float:
            return round(sum(s[key] for s in snaps), 2) if snaps else 0.0

        def _max(values) -> float:  # noqa: ANN001
            return round(max(values), 2) if values else 0.0

        return {
            "faces_total": counts["total"],
            "faces_today": counts["today"],
            "faces_last_hour": counts["last_hour"],
            "faces_in_frame": int(_sum("faces_in_frame")),
            "current_tracks": int(_sum("tracked_faces")),
            "fps": _max([c["fps"] for c in cams]),
            "processing_fps": _sum("processing_fps"),
            "detection_latency_ms": _max([s["detection_latency_ms"] for s in snaps]),
            "embedding_latency_ms": _max([s["embedding_latency_ms"] for s in snaps]),
            "faces_saved_session": int(_sum("faces_saved_session")),
            "faces_rejected_session": int(_sum("faces_rejected_session")),
            "uptime_seconds": max((s["uptime_seconds"] for s in snaps), default=0.0),
            "camera_count": len(self.camera_pipelines),
            "cameras": self.camera_statuses(),
            "inference_backend": self.running_backend(),
            "inference_label": self.backend_label(),
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

        cams = [p.camera.state.snapshot() for p in self.camera_pipelines.values()]
        # Healthy when the DB is fine and at least one camera is connected.
        any_connected = any(c["connected"] for c in cams)
        max_fps = round(max((c["fps"] for c in cams), default=0.0), 2)
        system = self.health_monitor.system_metrics()
        healthy = database_ok and any_connected
        return {
            "status": "healthy" if healthy else "degraded",
            "camera_connected": any_connected,
            "fps": max_fps,
            "database_ok": database_ok,
            "faiss_ok": True,
            "faiss_vectors": self.vector_store.count,
            "embedding_model_loaded": self.models is not None,
            "queues": self.queue_sizes(),
            "cpu_percent": system["cpu_percent"],
            "ram_percent": system["ram_percent"],
            "disk_percent": system["disk_percent"],
            "temperature_c": system["temperature_c"],
            "uptime_seconds": max(
                (p.stats.snapshot()["uptime_seconds"] for p in self.camera_pipelines.values()),
                default=0.0,
            ),
        }
