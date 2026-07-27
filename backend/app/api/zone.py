"""Capture zone (region of interest) endpoints, per camera.

The dashboard draws the polygon on a camera's live view and stores it here;
the zone takes effect immediately (no restart) and persists across restarts.
Each camera has its own zone (pass ?camera_id=…; omitted = first camera).
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_pipeline
from app.logging_setup import get_logger
from app.pipeline.orchestrator import Pipeline
from app.schemas import MessageResponse, ZoneConfig

logger = get_logger("api.zone")

router = APIRouter(prefix="/api", tags=["zone"])


def _resolve_camera_id(pipeline: Pipeline, camera_id: int | None) -> int:
    """Fall back to the first camera when no id is given; 404 if none exist."""
    zone = pipeline.get_capture_zone(camera_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="No such camera")
    if camera_id is not None:
        return camera_id
    return next(iter(pipeline.capture_zones.keys()))


@router.get("/zone", response_model=ZoneConfig)
def get_zone(
    camera_id: int | None = None, pipeline: Pipeline = Depends(get_pipeline)
) -> ZoneConfig:
    """Current capture zone for a camera (empty points = whole frame)."""
    zone = pipeline.get_capture_zone(camera_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="No such camera")
    points = zone.get_points()
    return ZoneConfig(points=points, enabled=len(points) >= 3)


@router.put("/zone", response_model=ZoneConfig)
def set_zone(
    config: ZoneConfig,
    camera_id: int | None = None,
    pipeline: Pipeline = Depends(get_pipeline),
) -> ZoneConfig:
    """Replace a camera's capture zone; applies immediately and persists."""
    cam_id = _resolve_camera_id(pipeline, camera_id)
    try:
        pipeline.set_capture_zone(list(config.points), cam_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    points = pipeline.get_capture_zone(cam_id).get_points()
    return ZoneConfig(points=points, enabled=len(points) >= 3)


@router.delete("/zone", response_model=MessageResponse)
def clear_zone(
    camera_id: int | None = None, pipeline: Pipeline = Depends(get_pipeline)
) -> MessageResponse:
    """Disable a camera's capture zone (capture anywhere in the frame)."""
    cam_id = _resolve_camera_id(pipeline, camera_id)
    pipeline.set_capture_zone([], cam_id)
    return MessageResponse(message="Capture zone cleared")
