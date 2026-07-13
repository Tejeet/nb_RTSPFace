"""SQLAlchemy ORM models.

SQLite today; the models use only portable column types so a future
migration to PostgreSQL is a connection-string change plus Alembic run.
"""

from datetime import UTC, datetime

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Timezone-aware UTC now (SQLite stores it as ISO text)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Camera(Base):
    """A configured video source."""

    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    rtsp_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    faces: Mapped[list["Face"]] = relationship(back_populates="camera")


class Face(Base):
    """One captured face image plus its embedding metadata."""

    __tablename__ = "faces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), nullable=False)
    track_id: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False, index=True)

    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    detection_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)

    # Bounding box in original frame coordinates.
    bbox_x: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_y: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_w: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_h: Mapped[int] = mapped_column(Integer, nullable=False)

    image_width: Mapped[int] = mapped_column(Integer, nullable=False)
    image_height: Mapped[int] = mapped_column(Integer, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    embedding_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_possible_duplicate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    camera: Mapped[Camera] = relationship(back_populates="faces")

    __table_args__ = (
        Index("ix_faces_camera_captured", "camera_id", "captured_at"),
        Index("ix_faces_track", "camera_id", "track_id"),
    )


class DuplicateLink(Base):
    """Records that a new face closely matched an existing one (kept, not deleted)."""

    __tablename__ = "duplicate_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    face_id: Mapped[int] = mapped_column(ForeignKey("faces.id"), nullable=False, index=True)
    matched_face_id: Mapped[int] = mapped_column(ForeignKey("faces.id"), nullable=False, index=True)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
