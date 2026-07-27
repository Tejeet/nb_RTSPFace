"""Face listing, detail, images, deletion and bulk-purge endpoints."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.deps import face_bbox, face_to_summary, get_pipeline
from app.logging_setup import get_logger
from app.pipeline.orchestrator import Pipeline
from app.schemas import (
    DuplicateMatch,
    FaceDetail,
    FaceListResponse,
    FaceSummary,
    MessageResponse,
    PurgeRequest,
    PurgeResponse,
)

logger = get_logger("api.faces")

router = APIRouter(prefix="/api", tags=["faces"])


@router.get("/faces", response_model=FaceListResponse)
def list_faces(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    since: datetime | None = None,
    min_quality: float | None = Query(default=None, ge=0.0, le=1.0),
    pipeline: Pipeline = Depends(get_pipeline),
) -> FaceListResponse:
    """Paginated list of captured faces, newest first."""
    faces, total = pipeline.repository.list_faces(
        limit=limit, offset=offset, since=since, min_quality=min_quality
    )
    return FaceListResponse(
        items=[face_to_summary(f) for f in faces], total=total, limit=limit, offset=offset
    )


@router.get("/recent", response_model=list[FaceSummary])
def recent_faces(
    limit: int = Query(default=24, ge=1, le=100),
    pipeline: Pipeline = Depends(get_pipeline),
) -> list[FaceSummary]:
    """Most recent captures (convenience endpoint for the dashboard)."""
    faces, _ = pipeline.repository.list_faces(limit=limit, offset=0)
    return [face_to_summary(f) for f in faces]


@router.post("/faces/purge", response_model=PurgeResponse)
def purge_faces(body: PurgeRequest, pipeline: Pipeline = Depends(get_pipeline)) -> PurgeResponse:
    """Bulk-delete captured history by scope. Enrolled persons are kept."""
    now = datetime.now(UTC)
    windows = {
        "all": (None, None),
        "last_hour": (now - timedelta(hours=1), None),
        "today": (now.replace(hour=0, minute=0, second=0, microsecond=0), None),
        "older_than_week": (None, now - timedelta(days=7)),
    }
    if body.scope not in windows:
        raise HTTPException(status_code=422, detail=f"Unknown scope '{body.scope}'")
    since, until = windows[body.scope]

    removed = pipeline.repository.purge_faces(since=since, until=until)

    # Remove FAISS vectors: a full wipe resets the index; a partial purge
    # removes the affected ids one by one.
    if body.scope == "all":
        pipeline.vector_store.reset()
    else:
        for item in removed:
            pipeline.vector_store.remove(int(item["id"]))

    for item in removed:
        for key in ("image_path", "thumbnail_path", "embedding_path", "frame_path"):
            path_str = item.get(key)
            if path_str:
                Path(str(path_str)).unlink(missing_ok=True)

    logger.info("Purged %d faces (scope=%s)", len(removed), body.scope)
    return PurgeResponse(
        deleted=len(removed),
        scope=body.scope,
        message=f"Deleted {len(removed)} capture(s)",
    )


@router.get("/faces/{face_id}", response_model=FaceDetail)
def get_face(face_id: int, pipeline: Pipeline = Depends(get_pipeline)) -> FaceDetail:
    """Full detail for one captured face, including duplicate matches."""
    face = pipeline.repository.get_face(face_id)
    if face is None:
        raise HTTPException(status_code=404, detail="Face not found")

    links = pipeline.repository.get_duplicate_links(face_id)
    duplicates = [
        DuplicateMatch(
            face_id=(link.matched_face_id if link.face_id == face_id else link.face_id),
            similarity=link.similarity,
            thumbnail_url=(
                f"/api/faces/"
                f"{link.matched_face_id if link.face_id == face_id else link.face_id}/thumbnail"
            ),
        )
        for link in links
    ]

    summary = face_to_summary(face)
    return FaceDetail(
        **summary.model_dump(),
        bbox=face_bbox(face),
        image_width=face.image_width,
        image_height=face.image_height,
        file_size_bytes=face.file_size_bytes,
        embedding_model=face.embedding_model,
        embedding_path=face.embedding_path,
        frame_url=f"/api/faces/{face.id}/frame" if face.frame_path else None,
        camera_name=pipeline.settings.camera_name,
        duplicates=duplicates,
    )


@router.get("/faces/{face_id}/image")
def get_face_image(face_id: int, pipeline: Pipeline = Depends(get_pipeline)) -> FileResponse:
    """The stored face JPEG."""
    return _serve_image(pipeline, face_id, thumbnail=False)


@router.get("/faces/{face_id}/thumbnail")
def get_face_thumbnail(face_id: int, pipeline: Pipeline = Depends(get_pipeline)) -> FileResponse:
    """The small thumbnail JPEG."""
    return _serve_image(pipeline, face_id, thumbnail=True)


@router.get("/faces/{face_id}/frame")
def get_face_frame(face_id: int, pipeline: Pipeline = Depends(get_pipeline)) -> FileResponse:
    """The full camera frame stored at the moment of capture."""
    face = pipeline.repository.get_face(face_id)
    if face is None:
        raise HTTPException(status_code=404, detail="Face not found")
    if not face.frame_path or not Path(face.frame_path).exists():
        raise HTTPException(status_code=404, detail="Full frame not stored for this face")
    return FileResponse(face.frame_path, media_type="image/jpeg")


@router.delete("/faces/{face_id}", response_model=MessageResponse)
def delete_face(face_id: int, pipeline: Pipeline = Depends(get_pipeline)) -> MessageResponse:
    """Delete a face: database row, FAISS vector, and files on disk."""
    face = pipeline.repository.delete_face(face_id)
    if face is None:
        raise HTTPException(status_code=404, detail="Face not found")

    pipeline.vector_store.remove(face_id)
    for path_str in (face.image_path, face.thumbnail_path, face.embedding_path, face.frame_path):
        if path_str:
            Path(path_str).unlink(missing_ok=True)
    logger.info("Face deleted: id=%d uuid=%s", face_id, face.uuid)
    return MessageResponse(message=f"Face {face_id} deleted")


def _serve_image(pipeline: Pipeline, face_id: int, thumbnail: bool) -> FileResponse:
    face = pipeline.repository.get_face(face_id)
    if face is None:
        raise HTTPException(status_code=404, detail="Face not found")
    path_str = face.thumbnail_path if thumbnail else face.image_path
    if not path_str or not Path(path_str).exists():
        raise HTTPException(status_code=404, detail="Image file missing")
    return FileResponse(path_str, media_type="image/jpeg")
