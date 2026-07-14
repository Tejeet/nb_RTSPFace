# API Reference

Base URL: `http://<host>:8000` (direct) or via the dashboard origin (nginx proxies
`/api` and `/ws`). Interactive Swagger UI at `/docs`.

## Faces

### `GET /api/faces`
Paginated list, newest first.

| Query param | Default | Notes |
| --- | --- | --- |
| `limit` | 50 | 1–500 |
| `offset` | 0 | |
| `since` | — | ISO datetime filter |
| `min_quality` | — | 0–1 |

```json
{
  "items": [
    {
      "id": 42, "uuid": "9b2f…", "camera_id": 1, "track_id": 7,
      "captured_at": "2026-07-13T09:14:02.113000+00:00",
      "quality_score": 0.81, "detection_confidence": 0.93,
      "is_possible_duplicate": 0,
      "image_url": "/api/faces/42/image",
      "thumbnail_url": "/api/faces/42/thumbnail"
    }
  ],
  "total": 1312, "limit": 50, "offset": 0
}
```

### `GET /api/recent?limit=24`
Shorthand for the newest captures (dashboard cards).

### `GET /api/faces/{id}`
Full detail: everything above plus `bbox {x,y,w,h}`, image dimensions, file size,
`embedding_model`, `embedding_path`, `camera_name`, and `duplicates`
(`[{face_id, similarity, thumbnail_url}]`).

### `GET /api/faces/{id}/image` · `GET /api/faces/{id}/thumbnail` · `GET /api/faces/{id}/frame`
The stored face JPEG / 96 px thumbnail / full camera frame at capture time
(404 when `SAVE_FULL_FRAME` was off for that capture).

## Capture zone

### `GET /api/zone`
Current region of interest: `{ "points": [[x, y], …], "enabled": bool }`
(normalized 0–1 coordinates; empty = whole frame).

### `PUT /api/zone`
Replace the zone: body `{ "points": [[0.2, 0.3], [0.8, 0.3], [0.8, 0.9]] }`
(≥3 points, each in 0–1). Applies immediately, persists across restarts,
and overrides the `CAPTURE_ZONE` env default.

### `DELETE /api/zone`
Disable the zone (capture anywhere in the frame).

## Settings

### `GET /api/settings/inference`
Inference backend state:
```json
{
  "inference_backend": "npu", "running_backend": "cpu",
  "npu_active": false, "npu_runtime_available": false,
  "active_providers": ["CPUExecutionProvider"],
  "requires_restart": true,
  "model_pack": "buffalo_l", "detection_size": 640
}
```

### `PUT /api/settings/inference`
Body `{ "inference_backend": "cpu" | "npu" }`. Persists in the data volume;
takes effect when the backend container restarts (`requires_restart` tells
the UI to prompt).

### `DELETE /api/faces/{id}`
Removes the database row, FAISS vector, image, thumbnail and embedding file.

## Search

### `POST /api/search?top_k=10`
`multipart/form-data` with a `file` image field (max 10 MB). The largest detected face
in the upload is embedded and searched against FAISS.

```bash
curl -F "file=@person.jpg" "http://pi:8000/api/search?top_k=10"
```

```json
{
  "query_faces_detected": 1,
  "matches": [
    { "face": { "id": 42, "…": "…" }, "similarity": 0.9714 }
  ]
}
```

`query_faces_detected: 0` means no face was found in the uploaded image.

## System

### `GET /api/statistics`
```json
{
  "faces_total": 1312, "faces_today": 214, "faces_last_hour": 12,
  "current_tracks": 2, "fps": 14.8, "processing_fps": 7.1,
  "detection_latency_ms": 96.4, "embedding_latency_ms": 178.2,
  "cpu_percent": 61.0, "ram_percent": 48.2, "ram_used_mb": 1890.1,
  "disk_percent": 12.4, "disk_free_gb": 201.33, "temperature_c": 58.3,
  "uptime_seconds": 86400.2,
  "queues": { "frames": 1, "embeddings": 0, "persistence": 0 }
}
```

### `GET /api/health`
Deep health check (also used by the Docker healthcheck). `status` is `healthy` or
`degraded`; includes camera state, database/FAISS status, vector count, queue depths
and system metrics.

### `GET /api/live-status`
Camera connectivity, FPS, visible/tracked face counts, frame dimensions.

### `GET /api/stream/live`
`multipart/x-mixed-replace` MJPEG stream with bounding boxes, track IDs, FPS and face
count burned in. Use directly as an `<img src>`.

## WebSocket

### `WS /ws/events`
Server pushes JSON messages `{"type": …, "data": …}`:

| Type | When | Payload |
| --- | --- | --- |
| `face_captured` | every stored face | face summary incl. `thumbnail_url` |
| `stats` | every `STATS_INTERVAL` s | same shape as `/api/statistics` |
| `live_status` | every `STATS_INTERVAL` s | same shape as `/api/live-status` |

A `stats` + `live_status` snapshot is sent immediately on connect. No client → server
messages are required.
