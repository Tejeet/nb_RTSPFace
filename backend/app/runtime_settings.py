"""Runtime-editable settings persisted in the data volume.

A tiny JSON-file store for the handful of options the dashboard can change
(currently the inference backend). Environment variables provide the
defaults; values saved here override them on the next startup, surviving
container rebuilds because they live under STORAGE_ROOT.
"""

import json
import threading
from pathlib import Path

from app.logging_setup import get_logger

logger = get_logger("runtime_settings")


class RuntimeSettings:
    """Thread-safe JSON-backed key/value store for dashboard-editable settings."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, object] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                logger.exception("Could not read %s; using defaults", path)

    def get(self, key: str, default: object = None) -> object:
        """Read a value (falling back to the given default)."""
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: object) -> None:
        """Write a value and persist the file atomically."""
        with self._lock:
            self._data[key] = value
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2))
            tmp.replace(self._path)
        logger.info("Runtime setting saved: %s=%s", key, value)
