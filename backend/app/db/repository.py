"""Repository: all database reads/writes go through this module.

Keeps SQL concerns out of the pipeline and API layers, and gives a single
seam for a future PostgreSQL migration.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import Camera, DuplicateLink, Face, Person
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

    def add_camera(self, name: str, rtsp_url: str, camera_id: int | None = None) -> Camera:
        """Create a camera. Optional camera_id sets a custom id (else auto).

        Raises ValueError if the name or the requested id is already taken.
        """
        with self._db.session() as session:
            if session.scalar(select(Camera).where(Camera.name == name)) is not None:
                raise ValueError(f"A camera named '{name}' already exists")
            if camera_id is not None:
                if session.get(Camera, camera_id) is not None:
                    raise ValueError(f"Camera id {camera_id} is already in use")
                camera = Camera(id=camera_id, name=name, rtsp_url=rtsp_url)
            else:
                camera = Camera(name=name, rtsp_url=rtsp_url)
            session.add(camera)
            session.flush()
            session.refresh(camera)
            return camera

    def list_cameras(self) -> list[Camera]:
        """All configured cameras, oldest first (stable ordering)."""
        with self._db.session() as session:
            return list(session.scalars(select(Camera).order_by(Camera.id)).all())

    def get_camera(self, camera_id: int) -> Camera | None:
        """Fetch one camera by id."""
        with self._db.session() as session:
            return session.get(Camera, camera_id)

    def delete_camera(self, camera_id: int) -> Camera | None:
        """Delete a camera row (its captured faces are kept)."""
        with self._db.session() as session:
            camera = session.get(Camera, camera_id)
            if camera is None:
                return None
            session.delete(camera)
            return camera

    def count_cameras(self) -> int:
        """Number of configured cameras."""
        with self._db.session() as session:
            return session.scalar(select(func.count(Camera.id))) or 0

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

    # -- Persons (enrollment) ------------------------------------------------

    def insert_person(self, person: Person) -> Person:
        """Persist a new enrolled person and return it with its id."""
        with self._db.session() as session:
            session.add(person)
            session.flush()
            session.refresh(person)
            return person

    def get_person(self, person_id: int) -> Person | None:
        """Fetch one person by primary key."""
        with self._db.session() as session:
            return session.get(Person, person_id)

    def get_person_by_employee_id(self, employee_id: str) -> Person | None:
        """Fetch a person by their (unique) employee id."""
        with self._db.session() as session:
            return session.scalar(select(Person).where(Person.employee_id == employee_id))

    def list_persons(self) -> list[Person]:
        """All enrolled persons, newest first."""
        with self._db.session() as session:
            return list(session.scalars(select(Person).order_by(Person.created_at.desc())).all())

    def delete_person(self, person_id: int) -> Person | None:
        """Delete an enrolled person; clears the label from their tagged faces."""
        with self._db.session() as session:
            person = session.get(Person, person_id)
            if person is None:
                return None
            for face in session.scalars(select(Face).where(Face.person_id == person_id)):
                face.person_id = None
                face.person_name = None
                face.recognition_similarity = None
            session.delete(person)
            return person

    # -- Bulk purge ----------------------------------------------------------

    def purge_faces(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        camera_id: int | None = None,
    ) -> list[dict[str, object]]:
        """Delete captured faces matching the filters (all None = every face).

        Returns the file paths of every deleted face so the caller can remove
        the images and FAISS vectors. Enrolled persons are untouched.
        """
        with self._db.session() as session:
            query = select(Face)
            if since is not None:
                query = query.where(Face.captured_at >= since)
            if until is not None:
                query = query.where(Face.captured_at < until)
            if camera_id is not None:
                query = query.where(Face.camera_id == camera_id)
            faces = list(session.scalars(query).all())
            if not faces:
                return []

            face_ids = [f.id for f in faces]
            removed = [
                {
                    "id": f.id,
                    "image_path": f.image_path,
                    "thumbnail_path": f.thumbnail_path,
                    "embedding_path": f.embedding_path,
                    "frame_path": f.frame_path,
                }
                for f in faces
            ]

            for link in session.scalars(
                select(DuplicateLink).where(
                    DuplicateLink.face_id.in_(face_ids)
                    | DuplicateLink.matched_face_id.in_(face_ids)
                )
            ):
                session.delete(link)
            for face in faces:
                session.delete(face)
            return removed

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
