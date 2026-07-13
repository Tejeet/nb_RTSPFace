"""FastAPI application entry point.

Startup order matters: logging → storage layout → pipeline (models, DB,
FAISS, worker threads) → event-loop binding for the WebSocket bus.
Shutdown drains the workers and flushes FAISS to disk.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import faces, search, stream, system, ws
from app.config import get_settings
from app.logging_setup import get_logger, setup_logging
from app.pipeline.orchestrator import Pipeline

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build and start the pipeline; tear it down on exit."""
    settings = get_settings()
    settings.ensure_directories()
    setup_logging(settings.log_level, settings.logs_dir, settings.log_retention_days)
    logger.info("Edge Face Capture starting (v%s)", __version__)

    pipeline = Pipeline(settings)
    pipeline.event_bus.bind_loop(asyncio.get_running_loop())
    pipeline.start()
    app.state.pipeline = pipeline

    try:
        yield
    finally:
        pipeline.stop()
        logger.info("Edge Face Capture stopped")


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title="Edge Face Capture & Recognition System",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # LAN-only edge deployment; tighten when auth lands
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(faces.router)
    app.include_router(search.router)
    app.include_router(system.router)
    app.include_router(stream.router)
    app.include_router(ws.router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
