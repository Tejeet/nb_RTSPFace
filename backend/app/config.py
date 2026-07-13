"""Application configuration.

Every tunable lives here and is sourced from environment variables /
a .env file via pydantic-settings. Nothing else in the codebase reads
os.environ directly, and no paths or thresholds are hardcoded elsewhere.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central, validated application settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # -- Camera --------------------------------------------------------
    rtsp_url: str = Field(alias="RTSP_URL")
    camera_name: str = Field(default="camera-1", alias="CAMERA_NAME")
    camera_reconnect_min_delay: float = Field(default=1.0, alias="CAMERA_RECONNECT_MIN_DELAY")
    camera_reconnect_max_delay: float = Field(default=30.0, alias="CAMERA_RECONNECT_MAX_DELAY")

    # -- Detection -----------------------------------------------------
    detection_confidence: float = Field(default=0.50, ge=0.0, le=1.0, alias="DETECTION_CONFIDENCE")
    detection_size: int = Field(default=640, alias="DETECTION_SIZE")
    detect_every_n_frames: int = Field(default=2, ge=1, alias="DETECT_EVERY_N_FRAMES")
    min_face_size: int = Field(default=40, ge=8, alias="MIN_FACE_SIZE")

    # -- Tracking ------------------------------------------------------
    track_match_iou: float = Field(default=0.30, alias="TRACK_MATCH_IOU")
    track_min_hits: int = Field(default=3, ge=1, alias="TRACK_MIN_HITS")
    track_max_lost_frames: int = Field(default=30, ge=1, alias="TRACK_MAX_LOST_FRAMES")
    track_low_score_threshold: float = Field(default=0.30, alias="TRACK_LOW_SCORE_THRESHOLD")

    # -- Capture / saving ----------------------------------------------
    save_interval_seconds: float = Field(default=10.0, gt=0, alias="SAVE_INTERVAL_SECONDS")
    face_crop_padding: float = Field(default=0.20, ge=0.0, le=1.0, alias="FACE_CROP_PADDING")
    face_crop_size: int = Field(default=224, alias="FACE_CROP_SIZE")
    jpeg_quality: int = Field(default=90, ge=10, le=100, alias="JPEG_QUALITY")

    # -- Quality gate ----------------------------------------------------
    quality_min_score: float = Field(default=0.45, ge=0.0, le=1.0, alias="QUALITY_MIN_SCORE")
    quality_blur_threshold: float = Field(default=45.0, alias="QUALITY_BLUR_THRESHOLD")
    quality_brightness_min: int = Field(default=40, alias="QUALITY_BRIGHTNESS_MIN")
    quality_brightness_max: int = Field(default=215, alias="QUALITY_BRIGHTNESS_MAX")

    # -- Embeddings / vector search ---------------------------------------
    embedding_model: str = Field(default="buffalo_l", alias="EMBEDDING_MODEL")
    duplicate_threshold: float = Field(default=0.92, ge=0.0, le=1.0, alias="DUPLICATE_THRESHOLD")
    faiss_save_interval: float = Field(default=60.0, gt=0, alias="FAISS_SAVE_INTERVAL")

    # -- Storage ------------------------------------------------------------
    storage_root: Path = Field(default=Path("/app/storage"), alias="STORAGE_ROOT")

    # -- Queues -------------------------------------------------------------
    frame_queue_size: int = Field(default=4, ge=1, alias="FRAME_QUEUE_SIZE")
    embed_queue_size: int = Field(default=32, ge=1, alias="EMBED_QUEUE_SIZE")
    persist_queue_size: int = Field(default=64, ge=1, alias="PERSIST_QUEUE_SIZE")

    # -- Live view -------------------------------------------------------------
    live_stream_fps: float = Field(default=8.0, gt=0, alias="LIVE_STREAM_FPS")
    live_stream_width: int = Field(default=960, alias="LIVE_STREAM_WIDTH")

    # -- API / server ------------------------------------------------------------
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    stats_interval: float = Field(default=2.0, gt=0, alias="STATS_INTERVAL")

    # -- Logging -----------------------------------------------------------------
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_retention_days: int = Field(default=14, ge=1, alias="LOG_RETENTION_DAYS")

    # -- Derived paths (all persistent data lives under storage_root) -------------
    @property
    def faces_dir(self) -> Path:
        return self.storage_root / "faces"

    @property
    def embeddings_dir(self) -> Path:
        return self.storage_root / "embeddings"

    @property
    def database_dir(self) -> Path:
        return self.storage_root / "database"

    @property
    def logs_dir(self) -> Path:
        return self.storage_root / "logs"

    @property
    def thumbnails_dir(self) -> Path:
        return self.storage_root / "thumbnails"

    @property
    def cache_dir(self) -> Path:
        return self.storage_root / "cache"

    @property
    def models_dir(self) -> Path:
        return self.storage_root / "models"

    @property
    def sqlite_path(self) -> Path:
        return self.database_dir / "faces.sqlite3"

    @property
    def faiss_index_path(self) -> Path:
        return self.database_dir / "faces.faiss"

    def ensure_directories(self) -> None:
        """Create the full on-disk storage layout if missing."""
        for path in (
            self.faces_dir,
            self.embeddings_dir,
            self.database_dir,
            self.logs_dir,
            self.thumbnails_dir,
            self.cache_dir,
            self.models_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()  # type: ignore[call-arg]
