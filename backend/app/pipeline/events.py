"""Event bus bridging pipeline threads to asyncio WebSocket clients.

Pipeline threads call `publish()` (thread-safe); each connected WebSocket
holds a bounded asyncio.Queue that the API layer drains. Slow clients drop
events rather than backing up the pipeline.
"""

import asyncio
import threading
from typing import Any

from app.logging_setup import get_logger

logger = get_logger("pipeline.events")


class EventBus:
    """Fan-out of pipeline events to WebSocket subscribers."""

    def __init__(self, queue_size: int = 64) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once at startup with the FastAPI event loop."""
        self._loop = loop

    def subscribe(self) -> "asyncio.Queue[dict[str, Any]]":
        """Register a new WebSocket client queue."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[dict[str, Any]]") -> None:
        """Remove a disconnected client's queue."""
        with self._lock:
            self._subscribers.discard(queue)

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Thread-safe publish; safe to call from any pipeline worker."""
        if self._loop is None or self._loop.is_closed():
            return
        event = {"type": event_type, "data": data}
        with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            self._loop.call_soon_threadsafe(self._offer, queue, event)

    @staticmethod
    def _offer(queue: "asyncio.Queue[dict[str, Any]]", event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # slow client: drop rather than block
