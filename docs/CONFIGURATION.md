# Configuration Guide

All configuration comes from environment variables (or a `.env` file), validated at
startup by `app/config.py`. Nothing is hardcoded.

## Camera

| Variable | Default | Description |
| --- | --- | --- |
| `RTSP_URL` | — (required) | Full RTSP URL. URL-encode special characters in credentials (`@` → `%40`) |
| `RTSP_TRANSPORT` | `tcp` | RTP transport. Keep `tcp` in Docker: UDP return traffic cannot reach a bridge-networked container (streams that play in VLC fail with `udp`) |
| `CAMERA_NAME` | `camera-1` | Display name; also the camera row key in the DB |
| `CAMERA_RECONNECT_MIN_DELAY` | `1.0` | First retry delay (s); doubles each failure |
| `CAMERA_RECONNECT_MAX_DELAY` | `30.0` | Retry delay ceiling (s); retries forever |

## Detection

| Variable | Default | Description |
| --- | --- | --- |
| `DETECTION_CONFIDENCE` | `0.50` | SCRFD score threshold; also the tracker's "high" band |
| `DETECTION_SIZE` | `640` | Detector input (square). Biggest single performance lever |
| `DETECT_EVERY_N_FRAMES` | `2` | Frame skip; tracking still bridges skipped frames |
| `MIN_FACE_SIZE` | `40` | Minimum face side in pixels |

## Tracking

| Variable | Default | Description |
| --- | --- | --- |
| `TRACK_MATCH_IOU` | `0.30` | Minimum IoU to associate a detection with a track |
| `TRACK_MIN_HITS` | `3` | Consecutive matches before a track is confirmed (and capturable) |
| `TRACK_MAX_LOST_FRAMES` | `30` | Occlusion tolerance before a track is dropped |
| `TRACK_LOW_SCORE_THRESHOLD` | `0.30` | Floor of the low-confidence rescue band |

## Capture & quality

| Variable | Default | Description |
| --- | --- | --- |
| `CAPTURE_ZONE` | *(empty)* | Optional polygon restricting where faces are captured: `x1,y1;x2,y2;…` in normalized 0–1 coordinates (origin top-left), ≥3 points. Empty = whole frame. Detection/tracking still run frame-wide; the zone is drawn on the live view and out-of-zone faces show grey boxes. A zone drawn in the dashboard (persisted as `database/zone.json`) overrides this value |
| `SAVE_FULL_FRAME` | `true` | Also store the full camera frame per capture under `frames/` (~200–500 KB each; disable to save disk) |
| `SAVE_INTERVAL_SECONDS` | `10` | Min seconds between saves of the same track |
| `FACE_CROP_PADDING` | `0.20` | Context padding around the box (fraction; 0.15–0.25 typical) |
| `FACE_CROP_SIZE` | `224` | Saved image size (160 or 224 recommended) |
| `JPEG_QUALITY` | `90` | 10–100 |
| `QUALITY_MIN_SCORE` | `0.45` | Composite score floor for acceptance |
| `QUALITY_BLUR_THRESHOLD` | `45.0` | Variance-of-Laplacian floor (higher = stricter) |
| `QUALITY_BRIGHTNESS_MIN/MAX` | `40` / `215` | Mean-gray acceptance band |

## Inference hardware

| Variable | Default | Description |
| --- | --- | --- |
| `INFERENCE_BACKEND` | `cpu` | `cpu`, `npu` or `hailo`. `npu` selects an ONNX Runtime NPU execution provider (VSINPU on Radxa Cubie A7Z, RKNPU on Rockchip); `hailo` runs SCRFD on a Hailo-8 PCIe accelerator via HailoRT. Any backend that cannot initialise falls back to CPU with the reason logged and shown on the Settings page. The dashboard overrides this (persisted as `database/settings.json`); changes apply on backend restart |
| `HAILO_DETECTION_HEF` | `scrfd_10g.hef` | Detection model for `hailo` mode; bare names resolve under `storage/models/hailo/`, absolute paths are used as-is |
| `HAILO_RECOGNITION_HEF` | *(empty)* | Optional ArcFace HEF. Empty keeps embeddings on the CPU — recommended, since detection and recognition otherwise contend for the single accelerator |

## Embeddings & search

| Variable | Default | Description |
| --- | --- | --- |
| `EMBEDDING_MODEL` | `buffalo_l` | InsightFace pack (`buffalo_s` for a faster, lighter option) |
| `DUPLICATE_THRESHOLD` | `0.92` | Cosine similarity that flags a possible duplicate |
| `FAISS_SAVE_INTERVAL` | `60` | Max seconds between index flushes to disk |

## Storage, queues, server

| Variable | Default | Description |
| --- | --- | --- |
| `STORAGE_ROOT` | `/app/storage` | Root of all persistent data (volume mount) |
| `FRAME_QUEUE_SIZE` | `4` | Raw frame buffer (drop-oldest) |
| `EMBED_QUEUE_SIZE` / `PERSIST_QUEUE_SIZE` | `32` / `64` | Capture pipeline buffers |
| `LIVE_STREAM_FPS` | `8` | MJPEG output cap |
| `LIVE_STREAM_WIDTH` | `960` | MJPEG downscale width |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | Bind address |
| `STATS_INTERVAL` | `2.0` | WebSocket stats cadence (s) |
| `LOG_LEVEL` | `INFO` | `DEBUG` logs every detection/rejection |
| `LOG_RETENTION_DAYS` | `14` | Daily rotated JSON log files kept |
| `DASHBOARD_PORT` / `BACKEND_PORT` | `8080` / `8000` | Host port mappings (compose only) |

## Performance tuning

The CM5 CPU budget is dominated by SCRFD detection. Approximate single-frame detection
cost by input size (4×A76 @ 2.4 GHz, 3 OMP threads):

| `DETECTION_SIZE` | ~latency | Effective FPS at skip=1 / 2 / 3 |
| --- | --- | --- |
| 640 | ~130 ms | 7 / 14* / 20* |
| 480 | ~75 ms | 13 / 25* / — |
| 320 | ~35 ms | 25+ | 

\* effective coverage FPS — tracking bridges skipped frames, so IDs stay stable.

Recommendations:

- **Default (640 / skip 2)** for small or distant faces (entrance cameras).
- **480 / skip 2** when faces are large in frame (doorway, kiosk) — hits the 10–15 FPS
  target with headroom.
- Embedding (~180 ms) runs only on saved captures, a few times per person per minute —
  it never affects frame rate.
- `OMP_NUM_THREADS=3` (set in the Dockerfile) leaves one core for the camera thread,
  API and OS; raising it to 4 usually *hurts* under sustained load.
- Use the sub-stream (e.g. `/Streaming/Channels/602`) if the main stream is 4K —
  decoding cost matters too.
