"""ByteTrack-style multi-face tracker.

Implements the core ByteTrack idea — two-stage association where
high-confidence detections are matched first and low-confidence ones are
used to keep existing tracks alive — with IoU cost and Hungarian matching.
A lightweight constant-velocity prediction replaces the Kalman filter,
which is sufficient for CCTV face motion and cheap on a Pi CPU.

Swappable later for DeepSORT or full ByteTrack without touching callers:
the only contract is `update(detections) -> list[Track]`.
"""

import time
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from scipy.optimize import linear_sum_assignment

from app.pipeline.detector import Detection


class TrackState(Enum):
    """Lifecycle of a track."""

    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    LOST = "lost"


@dataclass
class Track:
    """One tracked face identity."""

    track_id: int
    bbox: tuple[int, int, int, int]
    score: float
    kps: np.ndarray
    state: TrackState = TrackState.TENTATIVE
    hits: int = 1
    frames_since_update: int = 0
    created_at: float = field(default_factory=time.time)
    last_saved_at: float = 0.0  # managed by the capture policy
    velocity: tuple[float, float] = (0.0, 0.0)

    def predict_bbox(self) -> tuple[int, int, int, int]:
        """Constant-velocity position estimate for matching."""
        x, y, w, h = self.bbox
        steps = self.frames_since_update + 1
        return (int(x + self.velocity[0] * steps), int(y + self.velocity[1] * steps), w, h)

    def apply(self, det: Detection) -> None:
        """Update the track with a matched detection."""
        old_x, old_y = self.bbox[0], self.bbox[1]
        self.velocity = (
            0.5 * self.velocity[0] + 0.5 * (det.bbox[0] - old_x),
            0.5 * self.velocity[1] + 0.5 * (det.bbox[1] - old_y),
        )
        self.bbox = det.bbox
        self.score = det.score
        self.kps = det.kps
        self.hits += 1
        self.frames_since_update = 0


def iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """Intersection-over-union of two (x, y, w, h) boxes."""
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


class ByteTracker:
    """Two-stage IoU tracker assigning stable Track IDs to faces."""

    def __init__(
        self,
        match_iou: float,
        min_hits: int,
        max_lost_frames: int,
        low_score_threshold: float,
        high_score_threshold: float,
    ) -> None:
        self._match_iou = match_iou
        self._min_hits = min_hits
        self._max_lost = max_lost_frames
        self._low_thresh = low_score_threshold
        self._high_thresh = high_score_threshold
        self._tracks: list[Track] = []
        self._next_id = 1

    @property
    def active_tracks(self) -> list[Track]:
        """Tracks currently confirmed and recently seen."""
        return [
            t
            for t in self._tracks
            if t.state == TrackState.CONFIRMED and t.frames_since_update == 0
        ]

    @property
    def tracked_count(self) -> int:
        """Number of confirmed (visible or briefly occluded) tracks."""
        return sum(1 for t in self._tracks if t.state == TrackState.CONFIRMED)

    def update(self, detections: list[Detection]) -> list[Track]:
        """Advance the tracker one frame; returns confirmed, visible tracks."""
        for track in self._tracks:
            track.frames_since_update += 1

        high = [d for d in detections if d.score >= self._high_thresh]
        low = [d for d in detections if self._low_thresh <= d.score < self._high_thresh]

        # Stage 1: match high-confidence detections against all tracks.
        unmatched_tracks, unmatched_high = self._associate(self._tracks, high)

        # Stage 2: low-confidence detections rescue still-unmatched tracks.
        unmatched_tracks, _ = self._associate(unmatched_tracks, low)

        # New tracks from unmatched high-confidence detections only.
        for det in unmatched_high:
            self._tracks.append(
                Track(track_id=self._next_id, bbox=det.bbox, score=det.score, kps=det.kps)
            )
            self._next_id += 1

        # Lifecycle transitions and pruning.
        alive: list[Track] = []
        for track in self._tracks:
            if track.frames_since_update == 0 and track.hits >= self._min_hits:
                track.state = TrackState.CONFIRMED
            if track.frames_since_update > self._max_lost:
                track.state = TrackState.LOST
            elif track.state == TrackState.TENTATIVE and track.frames_since_update > 3:
                track.state = TrackState.LOST  # tentative tracks die fast, but
                # tolerate brief detection flicker on small/side faces
            if track.state != TrackState.LOST:
                alive.append(track)
        self._tracks = alive

        return self.active_tracks

    def _associate(
        self, tracks: list[Track], detections: list[Detection]
    ) -> tuple[list[Track], list[Detection]]:
        """Hungarian IoU matching; applies matches, returns leftovers."""
        candidates = [t for t in tracks if t.frames_since_update > 0]
        if not candidates or not detections:
            return candidates, list(detections)

        cost = np.ones((len(candidates), len(detections)), dtype=np.float64)
        for i, track in enumerate(candidates):
            predicted = track.predict_bbox()
            for j, det in enumerate(detections):
                cost[i, j] = 1.0 - iou(predicted, det.bbox)

        rows, cols = linear_sum_assignment(cost)
        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        for i, j in zip(rows, cols, strict=True):
            if cost[i, j] <= 1.0 - self._match_iou:
                candidates[i].apply(detections[j])
                matched_tracks.add(i)
                matched_dets.add(j)

        leftover_tracks = [t for i, t in enumerate(candidates) if i not in matched_tracks]
        leftover_dets = [d for j, d in enumerate(detections) if j not in matched_dets]
        return leftover_tracks, leftover_dets
