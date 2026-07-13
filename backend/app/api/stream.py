"""Low-latency MJPEG stream of the annotated live view."""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_pipeline
from app.pipeline.orchestrator import Pipeline

router = APIRouter(prefix="/api", tags=["stream"])

BOUNDARY = "frame"


async def _mjpeg_generator(pipeline: Pipeline) -> AsyncIterator[bytes]:
    interval = 1.0 / pipeline.settings.live_stream_fps
    last_frame: bytes | None = None
    while True:
        frame = pipeline.live_buffer.latest()
        if frame is not None and frame is not last_frame:
            last_frame = frame
            yield (
                f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                f"Content-Length: {len(frame)}\r\n\r\n"
            ).encode() + frame + b"\r\n"
        await asyncio.sleep(interval)


@router.get("/stream/live")
def live_stream(pipeline: Pipeline = Depends(get_pipeline)) -> StreamingResponse:
    """Multipart MJPEG stream with detection overlays."""
    return StreamingResponse(
        _mjpeg_generator(pipeline),
        media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
        headers={"Cache-Control": "no-store"},
    )
