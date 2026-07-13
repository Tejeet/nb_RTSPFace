"""Repository: all database reads/writes go through this module.

Keeps SQL concerns out of the pipeline and API layers, and gives a single
seam for a future PostgreSQL migration.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import Camera, DuplicateLink, Face
from app.db.session import DatabaseManager


class FaceRepository:
    """CRUD and query operations for faces, cameras and duplicate links."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # -- Cameras ---------------------------------------------------------

    def upsert_camera(self, name: str, rtsp_url: str) -> int:
        """Create or update a camera row; return its id."""
        with self._db.session() as session:
            camera = session.scalar(select(Camera).where(Camera.name == name))
            if camera is None:
                camera = Camera(name=name, rtsp_url=rtsp_url)
                session.add(camera)
                session.flush()
            elif camera.rtsp_url != rtsp_url:
                camera.rtsp_url = rtsp_url
            return camera.id

    # -- Faces ---------------------------------------------------------------

    def insert_face(self, face: Face) -> Face:
        """Persist a new face row and return it with its id populated."""
        with self._db.session() as session:
            session.add(face)
            session.flush()
            session.refresh(face)
            return face

    def get_face(self, face_id: int) -> Face | None:
        """Fetch one face by primary key."""
        with self._db.session() as session:
            return session.get(Face, face_id)

    def get_faces_by_ids(self, ids: list[int]) -> list[Face]:
        """Fetch faces preserving the order of the given id list."""
        if not ids:
            return []
        with self._db.session() as session:
            rows = session.scalars(select(Face).where(Face.id.in_(ids))).all()
        by_id = {row.id: row for row in rows}
        return [by_id[i] for i in ids if i in by_id]

    def list_faces(
        self,
        limit: int = 50,
        offset: int = 0,
        since: datetime | None = None,
        camera_id: int | None = None,
        min_quality: float | None = None,
    ) -> tuple[list[Face], int]:
        """List faces newest-first with optional filters; returns (rows, total)."""
        with self._db.session() as session:
            query = select(Face)
            if since is not None:
                query = query.where(Face.captured_at >= since)
            if camera_id is not None:
                query = query.where(Face.camera_id == camera_id)
            if min_quality is not None:
                query = query.where(Face.quality_score >= min_quality)
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            rows = session.scalars(
                query.order_by(Face.captured_at.desc()).limit(limit).offset(offset)
            ).all()
            return list(rows), total

    def delete_face(self, face_id: int) -> Face | None:
        """Delete a face row (and its duplicate links); returns the deleted row."""
        with self._db.session() as session:
            face = session.get(Face, face_id)
            if face is None:
                return None
            for link in session.scalars(
                select(DuplicateLink).where(
                    (DuplicateLink.face_id == face_id)
                    | (DuplicateLink.matched_face_id == face_id)
                )
            ):
                session.delete(link)
            session.delete(face)
            return face

    # -- Duplicates ----------------------------------------------------------

    def insert_duplicate_link(self, face_id: int, matched_face_id: int, similarity: float) -> None:
        """Record a possible-duplicate relationship for later review."""
        with self._db.session() as session:
            session.add(
                DuplicateLink(
                    face_id=face_id, matched_face_id=matched_face_id, similarity=similarity
                )
            )

    def get_duplicate_links(self, face_id: int) -> list[DuplicateLink]:
        """All duplicate links that involve the given face."""
        with self._db.session() as session:
            return list(
                session.scalars(
                    select(DuplicateLink).where(
                        (DuplicateLink.face_id == face_id)
                        | (DuplicateLink.matched_face_id == face_id)
                    )
                ).all()
            )

    # -- Statistics ---------------------------------------------------------

    def count_faces_since(self, since: datetime) -> int:
        """Number of faces captured at/after the given time."""
        with self._db.session() as session:
            return (
                session.scalar(select(func.count(Face.id)).where(Face.captured_at >= since)) or 0
            )

    def count_faces_total(self) -> int:
        """Total number of faces stored."""
        with self._db.session() as session:
            return session.scalar(select(func.count(Face.id))) or 0

    def counts_summary(self) -> dict[str, int]:
        """Convenience: total / today / last hour counts in one call."""
        now = datetime.now(UTC)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "total": self.count_faces_total(),
            "today": self.count_faces_since(today),
            "last_hour": self.count_faces_since(now - timedelta(hours=1)),
        }
