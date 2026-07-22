# Edge Face Capture backend — Raspberry Pi CM5 (linux/arm64) & x86_64
FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=3

# ffmpeg: RTSP demux/decode for OpenCV; libgl/glib: OpenCV runtime;
# build-essential + g++: insightface builds a small Cython extension.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        build-essential \
        g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y build-essential g++ \
    && apt-get autoremove -y

# Optional HailoRT for the Hailo-8 PCIe accelerator. The wheel is not publicly
# redistributable, so drop it into backend/vendor/ yourself (Hailo Developer
# Zone → HailoRT → Python package matching the host driver AND cp312). The
# build works with an empty vendor/ — Hailo mode then reports "HailoRT missing"
# and the app runs on CPU.
COPY vendor/ ./vendor/
RUN if ls vendor/hailort*.whl >/dev/null 2>&1; then \
        echo "Installing HailoRT from vendor/" && \
        pip install --no-cache-dir vendor/hailort*.whl; \
    else \
        echo "No HailoRT wheel in vendor/ — Hailo backend will be unavailable"; \
    fi

COPY app ./app
COPY pyproject.toml .

# All persistent data (faces, embeddings, db, logs, models) lives here.
VOLUME ["/app/storage"]

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
