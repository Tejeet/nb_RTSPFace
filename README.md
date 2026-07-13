# Edge Face Capture & Recognition System

A production-grade, fully offline **edge face capture engine** for the Raspberry Pi
Compute Module 5. It continuously watches an RTSP CCTV stream, detects and tracks every
visible face, stores the best-quality crops, generates 512-d face embeddings, maintains a
persistent FAISS vector index, and serves a real-time web dashboard — all on the Pi CPU,
with no cloud dependency.

> This is **not** an attendance system. Known and unknown faces are captured equally.
> Identity management, enrollment and recognition are future phases the architecture is
> already shaped for.

## Features

- **RTSP ingest** with automatic, infinite reconnection (dedicated thread)
- **SCRFD face detection** (InsightFace `buffalo_l` pack, ONNX Runtime, CPU)
- **ByteTrack-style tracking** — stable Track IDs, two-stage association
- **Smart capture policy** — one image per track per configurable interval (default 10 s)
- **Quality gate** — rejects blurry, dark, bright, tiny or edge-clipped faces; every
  stored face carries a composite quality score
- **ArcFace embeddings** — 512-d normalized vectors per stored face
- **FAISS vector search** — cosine similarity, persisted to disk, duplicate flagging
- **SQLite metadata** via SQLAlchemy (PostgreSQL-ready)
- **Dashboard** — live MJPEG view with overlays, recent captures, face detail,
  image-upload similarity search, real-time statistics (WebSocket)
- **Fully Dockerized** — two containers, health checks, restart policies, one volume;
  deploys straight from Dockge

## Quick start

```bash
cp .env.example .env        # edit RTSP_URL if needed
docker compose up -d
```

Open the dashboard at `http://<pi-address>:8080`.
API docs (Swagger UI) at `http://<pi-address>:8000/docs`.

On the **very first start** the backend downloads the InsightFace `buffalo_l` model pack
(~300 MB) into the persistent `efc-storage` volume; after that the system runs fully
offline. For air-gapped installs, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#offline--air-gapped-installs).

## Architecture at a glance

```
RTSP Camera ──▶ CameraReader ──▶ frame queue ──▶ DetectionWorker
   (thread)      reconnects        (bounded)      SCRFD detect
                 forever                          ByteTrack IDs
                                                  quality gate + crop
                                                       │ embed queue
                                                       ▼
                                                EmbeddingWorker
                                                  ArcFace 512-d
                                                       │ persist queue
                                                       ▼
                                                 StorageWorker
                                            JPEG + .npy + SQLite + FAISS
                                                       │
                                                       ▼
                                     WebSocket events ──▶ React dashboard
```

Every stage runs in its own thread and communicates through **bounded queues** with
drop-oldest semantics, so a slow stage can never block the camera or grow memory.
Full details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository layout

```
backend/            FastAPI app + face pipeline (Python 3.12)
  app/pipeline/     camera, detector, tracker, quality, cropper, embeddings,
                    FAISS store, workers, orchestrator, health
  app/db/           SQLAlchemy models, session, repository
  app/api/          REST routers, WebSocket, MJPEG stream
frontend/           React + Vite dashboard, served by nginx
docs/               architecture, API, deployment, configuration, development
docker-compose.yml  two services + one persistent volume
.env.example        every tunable, documented
```

## Documentation

| Document | Contents |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline design, threading model, data flow, scalability roadmap |
| [docs/API.md](docs/API.md) | REST endpoints, WebSocket events, examples |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Pi setup, Dockge, volumes, offline installs, troubleshooting |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every environment variable, tuning guidance for the CM5 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Local dev, code style, adding features |

## Performance (Raspberry Pi CM5, CPU only)

With defaults (`DETECTION_SIZE=640`, `DETECT_EVERY_N_FRAMES=2`) the pipeline processes
roughly 5–8 detection FPS while the camera thread ingests the full stream rate; lowering
`DETECTION_SIZE` to 480 or raising the frame skip reaches 10–15 effective FPS. Embeddings
run only for saved captures (a few per person per minute), so they never affect the frame
rate. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md#performance-tuning) for the tuning matrix.

## License

Proprietary — internal project.
