# Deployment Guide

## Target hardware

Raspberry Pi Compute Module 5, 4 GB RAM, 256 GB NVMe SSD, Raspberry Pi OS 64-bit
(Bookworm), Docker Engine + Compose plugin. No AI accelerator required.

## One-time host preparation

```bash
# Docker (if not installed)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # re-login afterwards

# Confirm the SSD is the Docker data root (recommended):
docker info | grep "Docker Root Dir"
```

## Deploy with Docker Compose

```bash
git clone <repo> && cd nb_RTSPFace
cp .env.example .env
nano .env                      # set RTSP_URL, ports if needed
docker compose up -d
```

- Dashboard: `http://<pi>:8080` (change with `DASHBOARD_PORT`)
- API / Swagger: `http://<pi>:8000/docs` (change with `BACKEND_PORT`)

First build on the Pi takes several minutes (insightface compiles a small extension).
On **first start** the backend downloads the `buffalo_l` model pack (~300 MB) into the
`efc-storage` volume; watch progress with `docker logs -f efc-backend`. Every later
start is fully offline.

## Deploy with Dockge

1. In Dockge, create a new stack named `edge-face-capture`.
2. Paste the contents of `docker-compose.yml`, or point Dockge at this directory.
3. Add the variables from `.env.example` in Dockge's `.env` editor.
4. Deploy. Both services carry `restart: unless-stopped` and health checks, so Dockge
   shows live health and the stack survives reboots and crashes unattended.

## Persistent data

Everything lives in the single named volume `efc-storage`
(faces, thumbnails, embeddings, SQLite DB, FAISS index, logs, models). To bind-mount a
host path on the NVMe instead, replace in `docker-compose.yml`:

```yaml
    volumes:
      - /mnt/nvme/efc-storage:/app/storage
```

### Backup

```bash
docker run --rm -v efc-storage:/data -v $PWD:/backup alpine \
  tar czf /backup/efc-storage-$(date +%F).tar.gz -C /data .
```

## Updating a deployment

Run `./bitBucketUpdate.sh` on the device. It pulls origin/master (hard reset — never
edit tracked files on the device), regenerates `.env` from `.env.example`, downloads
the InsightFace models into `./models/` if missing, then gets the images:

1. **Pull first**: every push to master triggers GitHub Actions
   (`.github/workflows/docker-build.yml`) to build linux/arm64 images and publish
   them to GHCR tagged with the commit SHA. The script pulls the images matching
   the exact commit it just checked out.
2. **Build as fallback**: if no prebuilt image exists yet (CI still running, or
   GHCR unreachable), it builds locally on the device.

Finally it restarts the stack and removes all older images of both repos.

**One-time GHCR setup**: after the first successful workflow run, open
github.com → your profile → Packages → `nb_rtspface-backend` / `-frontend` →
Package settings → Change visibility → **Public**, so the devices can pull without
credentials. (Alternative: keep them private and `docker login ghcr.io` on each
device with a token that has `read:packages`.)

Tip: CI builds ARM images under QEMU emulation — the first backend build takes
~30 min, but the pip layer is cached, so later pushes that only change code build
in 2–3 minutes. Wait for the green check on GitHub before running the update
script if you want to avoid the local-build fallback.

## Models / offline installs

The host `./models/` directory is bind-mounted over the container's models path, so
the backend **never downloads models at startup** — `bitBucketUpdate.sh` fetches
`buffalo_l.zip` (~300 MB) once and reuses it forever. For air-gapped devices, copy
the `models/` folder from a connected machine into the repo root before deploying;
the expected layout is `models/models/buffalo_l/*.onnx`.

## NPU acceleration (Radxa Cubie A7Z and similar)

The pipeline runs all inference through ONNX Runtime, so hardware acceleration is a
matter of which **execution providers** the installed onnxruntime build ships:

- **Radxa Cubie A7Z** (Allwinner A733, ~3 TOPS NPU — VeriSilicon core): needs an
  onnxruntime build with the **VSINPU** execution provider (built with TIM-VX and the
  board's NPU userspace driver from Radxa's OS image).
- **Rockchip boards** (RK3588 etc.): the **RKNPU** execution provider.

Setup on the A7Z:

1. Start from Radxa's OS image with the NPU driver enabled (check
   `/dev/galcore` exists).
2. Replace the stock `onnxruntime` wheel in `backend/requirements.txt` with the
   vendor/self-built wheel that lists `VSINPUExecutionProvider` in
   `onnxruntime.get_available_providers()`, and mount the NPU device into the
   container by adding to the backend service in `docker-compose.yml`:
   ```yaml
       devices:
         - /dev/galcore:/dev/galcore
   ```
3. Rebuild (`docker compose up -d --build backend`), open **Dashboard → Settings**,
   select **NPU**, save, and restart the backend.

The Settings page shows whether an NPU runtime was detected and which providers are
actually active. Selecting NPU without the runtime is safe — the app logs a warning
and runs on CPU, so the same image and configuration work across the Pi CM5 (CPU)
and the A7Z (NPU).

Not every ONNX operator runs on NPUs; ONNX Runtime automatically keeps unsupported
layers on CPU, so expect a speedup on SCRFD/ArcFace convolutions rather than a strict
"everything on NPU" execution.

## Operations

```bash
docker compose logs -f backend      # structured logs (also in volume: logs/app.log)
docker compose ps                   # health status
docker compose pull && docker compose up -d --build   # upgrade
curl -s http://localhost:8000/api/health | python3 -m json.tool
```

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Camera offline but stream plays in VLC | Ensure `RTSP_TRANSPORT=tcp` (default). VLC silently falls back to TCP; OpenCV defaults to UDP, whose return packets can't reach a bridge-networked container |
| Camera offline in dashboard | Check `docker logs efc-backend` for "Camera connection failed"; verify the URL-encoded password (`@` → `%40`) and that the container can reach the camera: `docker exec efc-backend python -c "import socket; socket.create_connection(('192.168.6.61', 554), 5); print('reachable')"` |
| Slow / low FPS | Lower `DETECTION_SIZE` to 480, raise `DETECT_EVERY_N_FRAMES`; check `temperature_c` for thermal throttling (add a heatsink/fan above ~80 °C) |
| High RAM | Confirm queue sizes are default; RAM should plateau ~1.5–2 GB with models loaded |
| First start very slow | Model download in progress — see backend logs |
| Dashboard loads, no live image | The MJPEG stream needs the camera connected; check `/api/live-status` |
| Restart everything cleanly | `docker compose restart backend` — FAISS is flushed on shutdown and the DB uses WAL, so restarts are safe |
