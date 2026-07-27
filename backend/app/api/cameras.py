"""Camera management — add / list / delete RTSP streams.

Cameras are stored in the database and each runs its own capture pipeline.
Adding or removing a camera takes effect on the next backend restart
(consistent with the inference-backend and zone settings).
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_pipeline
from app.logging_setup import get_logger
from app.pipeline.orchestrator import Pipeline
from app.schemas import (
    CameraCreate,
    CameraListResponse,
    CameraSummary,
    MessageResponse,
)

logger = get_logger("api.cameras")

router = APIRouter(prefix="/api", tags=["cameras"])


def _to_summary(pipeline: Pipeline, camera) -> CameraSummary:  # noqa: ANN001
    """Serialize a camera, marking whether it is currently running/connected."""
    pipe = pipeline.camera_pipelines.get(camera.id)
    connected = bool(pipe.camera.state.snapshot()["connected"]) if pipe else False
    return CameraSummary(
        id=camera.id,
        name=camera.name,
        rtsp_url=camera.rtsp_url,
        created_at=camera.created_at,
        running=pipe is not None,
        connected=connected,
        stream_url=f"/api/stream/live?camera_id={camera.id}",
    )


@router.get("/cameras", response_model=CameraListResponse)
def list_cameras(pipeline: Pipeline = Depends(get_pipeline)) -> CameraListResponse:
    """All configured cameras."""
    cameras = pipeline.repository.list_cameras()
    return CameraListResponse(
        items=[_to_summary(pipeline, c) for c in cameras], total=len(cameras)
    )


@router.post("/cameras", response_model=CameraSummary)
def add_camera(
    body: CameraCreate, pipeline: Pipeline = Depends(get_pipeline)
) -> CameraSummary:
    """Add a camera. Takes effect after the backend restarts."""
    name = body.name.strip()
    rtsp_url = body.rtsp_url.strip()
    if not name or not rtsp_url:
        raise HTTPException(status_code=422, detail="Name and RTSP URL are required")
    if not rtsp_url.lower().startswith("rtsp://"):
        raise HTTPException(status_code=422, detail="RTSP URL must start with rtsp://")
    try:
        camera = pipeline.repository.add_camera(name, rtsp_url)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    logger.info("Camera added: id=%d name=%s (restart to start streaming)", camera.id, name)
    return _to_summary(pipeline, camera)


@router.delete("/cameras/{camera_id}", response_model=MessageResponse)
def delete_camera(camera_id: int, pipeline: Pipeline = Depends(get_pipeline)) -> MessageResponse:
    """Delete a camera. Its captured faces are kept; takes effect after restart."""
    if pipeline.repository.count_cameras() <= 1:
        raise HTTPException(status_code=409, detail="Cannot delete the only camera")
    camera = pipeline.repository.delete_camera(camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    logger.info("Camera deleted: id=%d name=%s (restart to stop streaming)", camera_id, camera.name)
    return MessageResponse(message=f"Camera '{camera.name}' removed (restart to apply)")
