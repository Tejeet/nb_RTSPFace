"""System endpoints: statistics, health, live status."""

from fastapi import APIRouter, Depends

from app.api.deps import get_pipeline
from app.pipeline.orchestrator import Pipeline
from app.schemas import HealthStatus, LiveStatus, SystemStats

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/statistics", response_model=SystemStats)
def get_statistics(pipeline: Pipeline = Depends(get_pipeline)) -> SystemStats:
    """Aggregate dashboard statistics."""
    return SystemStats(**pipeline.statistics())


@router.get("/health", response_model=HealthStatus)
def get_health(pipeline: Pipeline = Depends(get_pipeline)) -> HealthStatus:
    """Deep health check (also used by the container healthcheck)."""
    return HealthStatus(**pipeline.health())


@router.get("/live-status", response_model=LiveStatus)
def get_live_status(pipeline: Pipeline = Depends(get_pipeline)) -> LiveStatus:
    """Realtime camera / tracking status for the live view."""
    return LiveStatus(**pipeline.live_status())
