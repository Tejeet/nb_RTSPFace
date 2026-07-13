# Architecture

## Design goals

1. **Never block the camera.** Frame ingest is isolated behind a bounded queue with
   drop-oldest semantics; every downstream stage can stall without affecting capture.
2. **Bounded memory, forever.** Every queue has a fixed capacity; full frames never
   travel past the detection stage (only small crops do); the system is built to run
   for weeks on 4 GB RAM.
3. **Swappable compute.** Detection and embedding sit behind narrow interfaces
   (`FaceModels.detect / align / embed_aligned`), so a Hailo/Coral/AI-HAT backend can
   replace ONNX Runtime without touching the pipeline.
4. **One composition root.** `Pipeline` (orchestrator.py) constructs and wires every
   component; nothing reaches for globals or environment variables directly.

## Thread & queue model

```
┌────────────────┐   frame_queue    ┌──────────────────────────┐
│  CameraReader   │ ───(size 4,)──▶ │     DetectionWorker      │
│  RTSP + retry   │   drop oldest   │  SCRFD every Nth frame   │
└────────────────┘                  │  ByteTracker (IDs)       │
                                    │  capture policy (10 s)    │
                                    │  quality gate + crop      │
                                    │  live overlay → JPEG buf  │
                                    └──────────┬───────────────┘
                                               │ embed_queue (size 32)
                                               ▼
                                    ┌──────────────────────────┐
                                    │     EmbeddingWorker      │
                                    │  ArcFace on aligned 112² │
                                    └──────────┬───────────────┘
                                               │ persist_queue (size 64)
                                               ▼
                                    ┌──────────────────────────┐
                                    │      StorageWorker       │
                                    │ JPEG + thumbnail + .npy  │
                                    │ SQLite row (SQLAlchemy)  │
                                    │ FAISS dup-check + insert │
                                    │ WebSocket event publish  │
                                    └──────────────────────────┘

┌────────────────┐
│ HealthMonitor  │  samples psutil + pipeline metrics every 2 s,
└────────────────┘  broadcasts "stats" / "live_status" events

FastAPI event loop: REST, MJPEG stream (reads live JPEG buffer),
WebSocket fan-out (EventBus bridges threads → asyncio queues)
```

### Why detection and tracking share one thread

Tracking is stateful and strictly frame-ordered; splitting it from detection would
require re-serializing frames and buys nothing (the tracker costs microseconds next to
the detector's tens of milliseconds). Everything after tracking is stateless per capture
and parallelizes naturally.

### Memory discipline

- `frame_queue` holds at most 4 raw frames. The camera thread drops the **oldest**
  frame when full, so latency stays low under load.
- The detection worker copies only the padded face crop (~150 KB) and the aligned
  112×112 crop (~37 KB) into the capture job — full frames never enter later queues.
- If `embed_queue` is full the capture is dropped and the track's save timer is reset,
  so the face is retried on a later frame instead of queuing unboundedly.

## Capture policy

A track becomes eligible for capture when it is **confirmed** (≥ `TRACK_MIN_HITS`
consecutive matches). It is saved immediately on first eligibility, then re-saved every
`SAVE_INTERVAL_SECONDS` while it remains visible. Quality rejections do **not** consume
the interval — the next frame retries — so a person who is briefly blurred still gets
captured as soon as a sharp frame arrives. When a person leaves and returns they get a
new Track ID and are captured again.

## Quality gate

Rejections (in check order): too small → clipped by frame edge → too dark → too bright
→ blurry (variance of Laplacian). Accepted faces get a composite score:

```
score = 0.5·sharpness + 0.25·exposure-centering + 0.25·size    ∈ [0, 1]
```

Faces scoring below `QUALITY_MIN_SCORE` are rejected even if no single check failed.

## Tracking (ByteTrack-style)

Two-stage association per frame, following the ByteTrack insight that low-confidence
detections should rescue existing tracks but never create new ones:

1. High-confidence detections (≥ `DETECTION_CONFIDENCE`) match against all tracks
   (Hungarian assignment on IoU with constant-velocity prediction).
2. Remaining low-confidence detections (≥ `TRACK_LOW_SCORE_THRESHOLD`) match against
   still-unmatched tracks.
3. Unmatched high-confidence detections spawn tentative tracks; tentative tracks are
   confirmed after `TRACK_MIN_HITS` hits and dropped after 2 missed frames; confirmed
   tracks survive `TRACK_MAX_LOST_FRAMES` of occlusion.

A Kalman filter was deliberately traded for constant-velocity prediction: CCTV faces
move slowly relative to frame rate, and the Pi CPU budget is better spent on detection.
The tracker is a drop-in module — full ByteTrack or DeepSORT can replace it behind the
same `update(detections) -> tracks` contract.

## Vector store

`IndexIDMap(IndexFlatIP)` over L2-normalized vectors, so inner product equals cosine
similarity and each vector is keyed by its SQLite face id — the two stores stay in sync,
including deletes. Flat search is exact and fast far beyond this device's realistic
corpus (1 M vectors ≈ 2 GB; migrate to IVF/HNSW long before that). The index is flushed
to disk at most every `FAISS_SAVE_INTERVAL` seconds and always on shutdown, via atomic
temp-file replace.

Duplicate detection runs **before** insertion (so a face never matches itself): the top-3
neighbours above `DUPLICATE_THRESHOLD` are recorded in `duplicate_links` and the face is
flagged `is_possible_duplicate` — nothing is deleted.

## Storage layout

```
storage/
  faces/2026/07/13/14/30/face_<uuid>.jpg     # crops, date-partitioned to the minute
  thumbnails/2026/07/13/14/30/face_<uuid>.jpg
  embeddings/2026/07/13/<uuid>.npy           # 512-d float32
  database/faces.sqlite3                     # WAL mode
  database/faces.faiss
  logs/app.log[.YYYY-MM-DD]                  # JSON lines, daily rotation
  models/models/buffalo_l/                   # InsightFace ONNX pack
  cache/
```

## Database schema

- **cameras** — id, name, rtsp_url
- **faces** — uuid, camera_id, track_id, captured_at, image/thumbnail/embedding paths,
  detection_confidence, quality_score, bbox (x,y,w,h), image size, file size,
  embedding_model, is_possible_duplicate. Indexed on captured_at, (camera_id, captured_at),
  (camera_id, track_id).
- **duplicate_links** — face_id ↔ matched_face_id with similarity.

Only portable column types are used; moving to PostgreSQL is a connection-string change.

## Realtime layer

Pipeline threads publish events through `EventBus`, which hops them onto the FastAPI
event loop (`call_soon_threadsafe`) into per-client bounded asyncio queues — a slow
browser drops events instead of backpressuring the pipeline. Event types:

- `face_captured` — after every successful persist
- `stats` / `live_status` — every `STATS_INTERVAL` seconds from the health monitor

The live view is MJPEG: the detection worker keeps one annotated JPEG in a rate-capped
buffer; `/api/stream/live` multiparts it out. This costs one encode per displayed frame
regardless of client count and adds near-zero latency.

## Scalability roadmap (already accommodated)

| Future feature | How the current design supports it |
| --- | --- |
| Multiple cameras | Cameras are DB rows; run one CameraReader + DetectionWorker pair per camera feeding the shared embed/persist queues (jobs already carry camera identity) |
| Recognition / enrollment | Add a `persons` table + FK on faces; embeddings and FAISS search already exist |
| MQTT / Telegram alerts | Subscribe a new consumer to `EventBus` |
| AI accelerators | Implement `FaceModels` against Hailo/Coral runtimes; same interface |
| Clustering / re-ID | Embeddings are already stored both as .npy files and in FAISS |
| Cloud sync | StorageWorker is the single choke point where every artifact lands |
| PostgreSQL | SQLAlchemy + repository pattern isolate all SQL |
| AuthN/AuthZ | FastAPI dependency injection: add an auth dependency per router |
