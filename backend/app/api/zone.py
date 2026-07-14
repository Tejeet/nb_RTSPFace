"""Capture zone (region of interest) endpoints.

The dashboard draws the polygon on the live view and stores it here; the
zone takes effect immediately (no restart) and persists across restarts.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_pipeline
from app.logging_setup import get_logger
from app.pipeline.orchestrator import Pipeline
from app.schemas import MessageResponse, ZoneConfig

logger = get_logger("api.zone")

router = APIRouter(prefix="/api", tags=["zone"])


@router.get("/zone", response_model=ZoneConfig)
def get_zone(pipeline: Pipeline = Depends(get_pipeline)) -> ZoneConfig:
    """Current capture zone (empty points = whole frame)."""
    points = pipeline.capture_zone.get_points()
    return ZoneConfig(points=points, enabled=len(points) >= 3)


@router.put("/zone", response_model=ZoneConfig)
def set_zone(config: ZoneConfig, pipeline: Pipeline = Depends(get_pipeline)) -> ZoneConfig:
    """Replace the capture zone; applies immediately and persists."""
    try:
        pipeline.set_capture_zone(list(config.points))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    points = pipeline.capture_zone.get_points()
    return ZoneConfig(points=points, enabled=len(points) >= 3)


@router.delete("/zone", response_model=MessageResponse)
def clear_zone(pipeline: Pipeline = Depends(get_pipeline)) -> MessageResponse:
    """Disable the capture zone (capture anywhere in the frame)."""
    pipeline.set_capture_zone([])
    return MessageResponse(message="Capture zone cleared")
