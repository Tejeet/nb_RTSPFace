"""Low-latency MJPEG stream of the annotated live view."""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_pipeline
from app.pipeline.orchestrator import Pipeline

router = APIRouter(prefix="/api", tags=["stream"])

BOUNDARY = "frame"


async def _mjpeg_generator(pipeline: Pipeline, camera_id: int | None) -> AsyncIterator[bytes]:
    interval = 1.0 / pipeline.settings.live_stream_fps
    pipe = pipeline.get_camera_pipeline(camera_id)
    if pipe is None:
        return
    last_frame: bytes | None = None
    while True:
        frame = pipe.live_buffer.latest()
        if frame is not None and frame is not last_frame:
            last_frame = frame
            yield (
                f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                f"Content-Length: {len(frame)}\r\n\r\n"
            ).encode() + frame + b"\r\n"
        await asyncio.sleep(interval)


@router.get("/stream/live")
def live_stream(
    camera_id: int | None = None, pipeline: Pipeline = Depends(get_pipeline)
) -> StreamingResponse:
    """Multipart MJPEG stream with overlays (first camera when id omitted)."""
    return StreamingResponse(
        _mjpeg_generator(pipeline, camera_id),
        media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
        headers={"Cache-Control": "no-store"},
    )
