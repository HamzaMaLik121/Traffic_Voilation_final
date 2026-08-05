# ═════════════════════════════════════════════════════════════════════
#  Dockerfile — Worker Service
#  What it does: Runs the CV/ML detection pipeline (YOLOv8 + EasyOCR)
#  Start command: python live_test.py
#  ═════════════════════════════════════════════════════════════════════
#  How models reach this container:
#    OPTION A (Local / Docker Compose):
#      Volume mount ./ml:/app/models in docker-compose.yml
#      → Models come from your local ml/ folder
#    OPTION B (EC2 / EKS with S3):
#      Set MODEL_BUCKET env var → entrypoint.sh pulls from S3
#      Container has AWS CLI installed for this
#    OPTION C (Manual copy):
#      Copy .pt files into /app/models/ yourself
# ═════════════════════════════════════════════════════════════════════

FROM python:3.12-slim

LABEL maintainer="Hamza"
LABEL project="traffic-violation-detection"
LABEL service="worker"

# ── System dependencies ─────────────────────────────────────────────
# C++ libraries needed by OpenCV, PyTorch, GStreamer, FFmpeg, and EasyOCR
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libgomp1 \
        libgstreamer1.0-0 \
        libgstreamer-plugins-base1.0-0 \
        ffmpeg \
        tesseract-ocr \
        tesseract-ocr-eng \
        wget \
        curl \
        unzip \
        awscli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python packages ─────────────────────────────────────────────────
COPY requirements-worker.txt .

# Install CPU-only PyTorch first (saves ~2GB vs CUDA version)
# Then install all other packages from requirements file
# (opencv and torch are installed separately to avoid version conflicts)
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        torch==2.6.0 \
        torchvision==0.21.0 \
        --index-url https://download.pytorch.org/whl/cpu \
    && grep -vE "^(opencv|torch|torchvision)" requirements-worker.txt \
        > /tmp/requirements_filtered.txt \
    && pip install --no-cache-dir -r /tmp/requirements_filtered.txt \
    && pip install --no-cache-dir \
        opencv-python==4.10.0.84 \
        opencv-contrib-python==4.10.0.84 \
    && rm -rf /tmp/requirements_filtered.txt

# ── Copy application source code into the image ─────────────────────
COPY config/        ./config/
COPY app/           ./app/
COPY live_test.py   .
COPY setup_lanes.py .
COPY entrypoint.sh  .

RUN chmod +x entrypoint.sh

# Create runtime directories (mounted via volumes at runtime)
# /app/data/videos is populated from S3 by entrypoint.sh when no volume
# mount is used (model weights + videos now come from S3, not git/local).
RUN mkdir -p /app/models /app/database /app/data/videos /app/outputs/evidence /app/outputs/violations

# ── Pre-download EasyOCR models ─────────────────────────────────────
# Without this, every first container start downloads ~100MB from the
# internet (craft_mlt_25k.pth + english_g2.pth), causing 2-5 minute delay.
# By doing it here, models are baked into the image.
RUN python3 -c "import easyocr; reader = easyocr.Reader(['en'], gpu=False); print('EasyOCR models pre-downloaded')"

# ── Pre-create Ultralytics settings ─────────────────────────────────
# First import of ultralytics creates a settings file with a warning.
# We pre-create it to avoid that message and keep logs clean.
RUN mkdir -p /root/.config/Ultralytics && cat > /root/.config/Ultralytics/settings.yaml << 'EOF'
settings_version: 0.0.4
datasets_dir: /app/datasets
weights_dir: /app/models
run_dir: /app/runs
uuid: prebaked-docker
sync: false
api_key: ""
openai_api_key: ""
clearml: false
comet: false
dvc: false
hub: false
mlflow: false
neptune: false
raytune: false
tensorboard: false
wandb: false
pip_install: false
EOF

# ── Environment variables ───────────────────────────────────────────
ENV QT_QPA_PLATFORM=offscreen
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV LOOP_VIDEO=1
ENV HEADLESS=1
ENV MODEL_BUCKET=""
ENV AWS_DEFAULT_REGION="us-east-1"

# ── Health check ────────────────────────────────────────────────────
# Checks if database file exists (created by worker on first violation)
# start-period=60s gives time for model loading + first detection
HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=60s \
    CMD test -f /app/database/violations.db || exit 1

ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "live_test.py"]
