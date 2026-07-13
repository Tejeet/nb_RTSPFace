"""FastAPI dependencies and ORM→schema serialization helpers."""

from fastapi import Request

from app.db.models import Face
from app.pipeline.orchestrator import Pipeline
from app.schemas import BoundingBox, FaceSummary


def get_pipeline(request: Request) -> Pipeline:
    """The single Pipeline instance, attached to app.state at startup."""
    return request.app.state.pipeline


def face_to_summary(face: Face) -> FaceSummary:
    """Serialize an ORM face into the compact API representation."""
    return FaceSummary(
        id=face.id,
        uuid=face.uuid,
        camera_id=face.camera_id,
        track_id=face.track_id,
        captured_at=face.captured_at,
        quality_score=face.quality_score,
        detection_confidence=face.detection_confidence,
        is_possible_duplicate=face.is_possible_duplicate,
        image_url=f"/api/faces/{face.id}/image",
        thumbnail_url=f"/api/faces/{face.id}/thumbnail",
    )


def face_bbox(face: Face) -> BoundingBox:
    """Extract the stored bounding box."""
    return BoundingBox(x=face.bbox_x, y=face.bbox_y, w=face.bbox_w, h=face.bbox_h)
