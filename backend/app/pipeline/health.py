"""System health monitor.

A background thread that samples CPU/RAM/disk/temperature, combines them
with pipeline metrics, and broadcasts a stats event over the WebSocket
bus on a fixed interval. The same snapshot backs /api/statistics and
/api/health.
"""

import threading
from pathlib import Path
from typing import Any

import psutil

from app.logging_setup import get_logger

logger = get_logger("pipeline.health")

THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")


def read_temperature_c() -> float | None:
    """CPU temperature in Celsius (Raspberry Pi thermal zone), if available."""
    try:
        if THERMAL_ZONE.exists():
            return round(int(THERMAL_ZONE.read_text().strip()) / 1000.0, 1)
        temps = psutil.sensors_temperatures()
        for entries in temps.values():
            if entries:
                return round(entries[0].current, 1)
    except (OSError, ValueError, AttributeError):
        pass
    return None


class HealthMonitor(threading.Thread):
    """Periodically samples system metrics and broadcasts them."""

    def __init__(self, pipeline: Any, storage_root: Path, interval: float) -> None:
        super().__init__(name="health-monitor", daemon=True)
        self._pipeline = pipeline
        self._storage_root = storage_root
        self._interval = interval
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def system_metrics(self) -> dict[str, Any]:
        """Sample host-level metrics (cheap; safe to call from API handlers)."""
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(self._storage_root))
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": memory.percent,
            "ram_used_mb": round(memory.used / (1024**2), 1),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024**3), 2),
            "temperature_c": read_temperature_c(),
        }

    def run(self) -> None:
        psutil.cpu_percent(interval=None)  # prime the sampler
        while not self._stop_event.wait(self._interval):
            try:
                stats = self._pipeline.statistics()
                self._pipeline.event_bus.publish("stats", stats)
                self._pipeline.event_bus.publish("live_status", self._pipeline.live_status())
            except Exception:
                logger.exception("Health broadcast failed")
        logger.info("Health monitor stopped")
