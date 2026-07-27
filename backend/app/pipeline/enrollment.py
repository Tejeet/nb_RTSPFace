"""Enrolled-person recognition.

Owns a FAISS index of enrolled-person embeddings (separate from the capture
index) and answers "who is this face?" for every capture. Enrollment adds a
person's embedding; recognition returns the best match above the configured
cosine-similarity threshold.

Thread-safety: the underlying VectorStore is locked, so enrollment (API
thread) and recognition (storage worker) can run concurrently.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.logging_setup import get_logger
from app.pipeline.vector_store import VectorStore

logger = get_logger("pipeline.enrollment")


@dataclass
class RecognitionResult:
    """A matched enrolled person."""

    person_id: int
    similarity: float


class PersonManager:
    """Enrolled-person embeddings + recognition search."""

    def __init__(self, index_path: Path, dim: int, threshold: float, save_interval: float) -> None:
        self._threshold = threshold
        self._store = VectorStore(
            index_path=index_path, dim=dim, save_interval=save_interval
        )

    @property
    def count(self) -> int:
        """Number of enrolled persons in the index."""
        return self._store.count

    def enroll(self, person_id: int, embedding: np.ndarray) -> None:
        """Add (or re-add) a person's embedding under their database id."""
        self._store.remove(person_id)  # idempotent: replace on re-enroll
        self._store.add(person_id, embedding)
        logger.info("Enrolled person id=%d (index now %d)", person_id, self._store.count)

    def remove(self, person_id: int) -> None:
        """Drop a person's embedding from the index."""
        self._store.remove(person_id)

    def recognize(self, embedding: np.ndarray) -> RecognitionResult | None:
        """Return the best enrolled match above threshold, or None (unknown)."""
        matches = self._store.search(embedding, top_k=1)
        if not matches:
            return None
        person_id, similarity = matches[0]
        if similarity < self._threshold:
            return None
        return RecognitionResult(person_id=person_id, similarity=round(similarity, 4))

    def save(self) -> None:
        """Flush the enrolled-person index to disk."""
        self._store.save()
