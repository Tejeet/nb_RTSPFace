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

## Offline / air-gapped installs

Two options:

1. **Pre-seed the volume.** On a connected machine run the stack once (or download
   `buffalo_l.zip` from the InsightFace release page), then copy
   `models/models/buffalo_l/*.onnx` into the volume at the same path on the target.
2. **Bake into the image.** Add to `backend/Dockerfile` before the CMD (grows the image
   ~300 MB but makes containers disposable):
   ```dockerfile
   RUN python -c "from insightface.app import FaceAnalysis; \
       FaceAnalysis(name='buffalo_l', root='/app/storage/models', \
       allowed_modules=['detection','recognition'])"
   ```

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
