# Developer Notes

## Local development (without Docker)

Backend (Python 3.12):

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export STORAGE_ROOT=$PWD/../storage RTSP_URL="rtsp://…"
python -m uvicorn app.main:app --reload --port 8000
```

Frontend (Node 20):

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, proxies /api + /ws to :8000
```

Any RTSP source works for development — e.g. loop a video file with mediamtx/ffmpeg:

```bash
ffmpeg -re -stream_loop -1 -i sample.mp4 -c copy -f rtsp rtsp://localhost:8554/test
```

## Code style

- Python 3.12, type hints everywhere, Pydantic v2 for all API/config models.
- Formatting **Black**, linting **Ruff** (both configured in `backend/pyproject.toml`):
  ```bash
  cd backend && black app && ruff check app --fix
  ```
- Files stay under ~500 lines; split modules rather than growing them.
- No globals: `Pipeline` is the composition root; API handlers get it via FastAPI
  dependency injection (`app.state.pipeline` → `get_pipeline`).
- Logging via `logging_setup.get_logger("<area>.<module>")`; JSON file logs rotate daily.

## Project map

| Module | Responsibility |
| --- | --- |
| `app/config.py` | All settings (pydantic-settings), storage layout |
| `app/pipeline/camera.py` | RTSP thread, infinite reconnect, drop-oldest queue |
| `app/pipeline/detector.py` | InsightFace models: SCRFD detect, align, ArcFace embed |
| `app/pipeline/tracker.py` | ByteTrack-style two-stage IoU tracker |
| `app/pipeline/quality.py` | Blur/exposure/size gate + composite score |
| `app/pipeline/cropper.py` | Padded crop, resize, date-partitioned JPEG + thumbnail |
| `app/pipeline/vector_store.py` | Persistent FAISS (cosine), thread-safe |
| `app/pipeline/workers.py` | Detection / Embedding / Storage worker threads |
| `app/pipeline/orchestrator.py` | Composition root, lifecycle, stats/health views |
| `app/pipeline/events.py` | Thread → asyncio WebSocket event bridge |
| `app/db/` | SQLAlchemy models, WAL SQLite session, repository |
| `app/api/` | REST routers, WebSocket, MJPEG stream |

## Extension recipes

**Second camera.** Add a `cameras` config list; in `Pipeline`, instantiate one
`CameraReader` + `DetectionWorker` (+ tracker/live buffer) per camera, all feeding the
shared `embed_queue`. `CaptureJob` already flows camera identity via the storage worker.

**Hardware acceleration.** Write a `HailoFaceModels` implementing
`detect(frame) -> list[Detection]`, `align`, `embed_aligned`; select the implementation
in `Pipeline.__init__` from a new env var. Nothing else changes.

**MQTT / Telegram.** Add a worker thread that subscribes to `EventBus` (give it a
thread-side subscribe method mirroring the asyncio one, or publish into a
`queue.Queue`) and forwards `face_captured` events.

**Person identity (recognition phase).** New `persons` table + nullable
`faces.person_id`; on each capture, FAISS-search enrolled centroids and assign above a
threshold. The search endpoint shows the pattern end-to-end.

**PostgreSQL.** Introduce Alembic, change the connection string in
`db/session.py`, drop the SQLite pragmas. The repository API is unchanged.

## Testing notes

There is no test suite yet (greenfield). Highest-value first targets:

1. `tracker.py` — pure logic, deterministic; feed synthetic detection sequences.
2. `quality.py` — synthetic images (blurred/dark/small) against the gate.
3. `repository.py` — in-memory SQLite.
4. API contract tests with `TestClient` and a stubbed `Pipeline` on `app.state`.
