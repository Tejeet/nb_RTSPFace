"""Persistent FAISS vector store with cosine similarity search.

Vectors are L2-normalized before insertion, so inner product == cosine
similarity. IndexIDMap binds each vector to its SQLite face id, keeping
the two stores in sync. All operations are guarded by a lock because the
index is shared between the pipeline thread and API request handlers.
"""

import threading
import time
from pathlib import Path

import faiss
import numpy as np

from app.logging_setup import get_logger

logger = get_logger("pipeline.vector_store")


class VectorStore:
    """Thread-safe FAISS index keyed by face database ids."""

    def __init__(self, index_path: Path, dim: int, save_interval: float) -> None:
        self._index_path = index_path
        self._dim = dim
        self._save_interval = save_interval
        self._lock = threading.Lock()
        self._dirty = False
        self._last_save = time.monotonic()
        self._index = self._load_or_create()

    def _load_or_create(self) -> faiss.IndexIDMap:
        if self._index_path.exists():
            try:
                index = faiss.read_index(str(self._index_path))
                logger.info("FAISS index loaded: %d vectors", index.ntotal)
                return index
            except Exception:
                logger.exception("Failed to read FAISS index; starting fresh")
        index = faiss.IndexIDMap(faiss.IndexFlatIP(self._dim))
        logger.info("Created new FAISS index (dim=%d)", self._dim)
        return index

    @property
    def count(self) -> int:
        """Number of vectors currently indexed."""
        with self._lock:
            return int(self._index.ntotal)

    def add(self, face_id: int, embedding: np.ndarray) -> None:
        """Insert one normalized embedding under the given face id."""
        vector = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
        ids = np.asarray([face_id], dtype=np.int64)
        with self._lock:
            self._index.add_with_ids(vector, ids)
            self._dirty = True
        self._maybe_save()

    def remove(self, face_id: int) -> None:
        """Remove a face's vector (used when a face is deleted)."""
        selector = faiss.IDSelectorArray(np.asarray([face_id], dtype=np.int64))
        with self._lock:
            self._index.remove_ids(selector)
            self._dirty = True

    def search(self, embedding: np.ndarray, top_k: int = 10) -> list[tuple[int, float]]:
        """Return [(face_id, cosine_similarity)] for the top_k nearest vectors."""
        vector = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
        with self._lock:
            if self._index.ntotal == 0:
                return []
            similarities, ids = self._index.search(vector, min(top_k, self._index.ntotal))
        return [
            (int(face_id), float(sim))
            for face_id, sim in zip(ids[0], similarities[0], strict=True)
            if face_id != -1
        ]

    def _maybe_save(self) -> None:
        if time.monotonic() - self._last_save >= self._save_interval:
            self.save()

    def save(self) -> None:
        """Flush the index to disk (atomic replace)."""
        with self._lock:
            if not self._dirty:
                return
            tmp_path = self._index_path.with_suffix(".tmp")
            faiss.write_index(self._index, str(tmp_path))
            tmp_path.replace(self._index_path)
            self._dirty = False
            self._last_save = time.monotonic()
        logger.debug("FAISS index saved (%d vectors)", self.count)
