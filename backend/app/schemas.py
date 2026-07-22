"""Pydantic schemas for the REST API and WebSocket payloads."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BoundingBox(BaseModel):
    """Axis-aligned box in original frame pixel coordinates."""

    x: int
    y: int
    w: int
    h: int


class FaceSummary(BaseModel):
    """Compact face representation used in lists and live events."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: str
    camera_id: int
    track_id: int
    captured_at: datetime
    quality_score: float
    detection_confidence: float
    is_possible_duplicate: int
    image_url: str
    thumbnail_url: str


class FaceDetail(FaceSummary):
    """Full face record for the detail page."""

    bbox: BoundingBox
    image_width: int
    image_height: int
    file_size_bytes: int
    embedding_model: str | None
    embedding_path: str | None
    frame_url: str | None
    camera_name: str
    duplicates: list["DuplicateMatch"]


class DuplicateMatch(BaseModel):
    """A stored near-duplicate relationship."""

    face_id: int
    similarity: float
    thumbnail_url: str


class FaceListResponse(BaseModel):
    """Paginated face list."""

    items: list[FaceSummary]
    total: int
    limit: int
    offset: int


class SearchMatch(BaseModel):
    """One similarity-search result."""

    face: FaceSummary
    similarity: float


class SearchResponse(BaseModel):
    """Result of an uploaded-image similarity search."""

    query_faces_detected: int
    matches: list[SearchMatch]


class LiveStatus(BaseModel):
    """Realtime pipeline status for the live view overlay."""

    camera_connected: bool
    camera_name: str
    fps: float
    visible_faces: int
    tracked_faces: int
    frame_width: int
    frame_height: int


class QueueSizes(BaseModel):
    """Current depth of each inter-worker queue."""

    frames: int
    embeddings: int
    persistence: int


class SystemStats(BaseModel):
    """Aggregate statistics for the dashboard."""

    faces_total: int
    faces_today: int
    faces_last_hour: int
    current_tracks: int
    fps: float
    detection_latency_ms: float
    embedding_latency_ms: float
    cpu_percent: float
    ram_percent: float
    ram_used_mb: float
    disk_percent: float
    disk_free_gb: float
    temperature_c: float | None
    npu_percent: float | None = None  # only on boards exposing an NPU load node
    accelerator_temperature_c: float | None = None  # Hailo-8 chip temperature
    uptime_seconds: float
    queues: QueueSizes


class HealthStatus(BaseModel):
    """Deep health check for /api/health and monitoring."""

    status: str
    camera_connected: bool
    fps: float
    database_ok: bool
    faiss_ok: bool
    faiss_vectors: int
    embedding_model_loaded: bool
    queues: QueueSizes
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    temperature_c: float | None
    uptime_seconds: float


class InferenceInfo(BaseModel):
    """Inference backend state shown on the Settings page."""

    inference_backend: str  # requested/persisted: "cpu" | "npu" | "hailo"
    running_backend: str  # what actually loaded (may differ after a fallback)
    npu_active: bool
    npu_runtime_available: bool
    hailo_active: bool = False
    hailo_runtime_available: bool = False
    hailo_device_present: bool = False
    backend_error: str | None = None  # why the requested backend fell back
    active_providers: list[str]
    requires_restart: bool
    model_pack: str
    detection_size: int


class InferenceUpdate(BaseModel):
    """Settings page payload."""

    inference_backend: str


class ZoneConfig(BaseModel):
    """Capture zone polygon in normalized (0..1) coordinates."""

    points: list[tuple[float, float]]
    enabled: bool = False


class MessageResponse(BaseModel):
    """Generic acknowledgement."""

    message: str
