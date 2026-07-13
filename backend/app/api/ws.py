"""WebSocket endpoint broadcasting pipeline events to the dashboard.

Event types: face_captured, stats, live_status.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.logging_setup import get_logger

logger = get_logger("api.ws")

router = APIRouter()


@router.websocket("/ws/events")
async def events_websocket(websocket: WebSocket) -> None:
    """Push pipeline events to a connected dashboard client."""
    pipeline = websocket.app.state.pipeline
    await websocket.accept()
    queue = pipeline.event_bus.subscribe()
    logger.info("WebSocket client connected")

    # Send an initial snapshot so the UI renders immediately.
    await websocket.send_json({"type": "stats", "data": pipeline.statistics()})
    await websocket.send_json({"type": "live_status", "data": pipeline.live_status()})

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception:
        logger.exception("WebSocket send failed")
    finally:
        pipeline.event_bus.unsubscribe(queue)
