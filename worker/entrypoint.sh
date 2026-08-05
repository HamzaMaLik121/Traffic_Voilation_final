#!/bin/bash
# ═════════════════════════════════════════════════════════════════════
#  entrypoint.sh — Worker Service Startup Script
#
#  Runs BEFORE the main application CMD on every container start.
#  Ensures model files are available in /app/models/ before the
#  detection pipeline starts.
#  Default CMD: python live_test.py
#  Can also be used with: python setup_lanes.py, python diagnostic.py, etc.
#
#  ── MODEL LOADING STRATEGY ──────────────────────────────────────────
#
#  OPTION A — LOCAL / DOCKER COMPOSE (Volume Mount):
#    • docker-compose.yml mounts ./ml/:/app/models:ro
#    • Models are already in /app/models/ when the container starts
#    • The script detects the non-empty directory and SKIPS S3 download
#    • Fastest path — models are local files, no network needed
#
#  OPTION B — EKS / KUBERNETES (S3 Pull):
#    • No volume mount available (or models PV empty)
#    • /app/models/ is empty on container start
#    • You MUST set the MODEL_BUCKET env var (e.g., "my-bucket")
#    • The script pulls ALL .pt files from s3://MODEL_BUCKET/models/
#    • Requires AWS CLI installed + IAM role / credentials configured
#    • Slower — depends on S3 transfer speed
#
#  OPTION C — MANUAL COPY (Development / Debug):
#    • Copy .pt / .onnx files directly into /app/models/ in a custom image
#    • Or run: docker exec -it traffic-worker bash
#    • Then manual download / copy into /app/models/
#
#  ── REQUIRED MODEL FILES ───────────────────────────────────────────
#  The worker expects these model weights:
#    /app/models/vehicle_detector/weights/best.pt
#    /app/models/helmet_detector/weights/best.pt
#    /app/models/traffic_light_detector/weights/best.pt
#    /app/models/lpr_detector/weights/best.pt
#    /app/models/lane_detector/weights/yolop-640-640.onnx
#
#  ── ENVIRONMENT VARIABLES ──────────────────────────────────────────
#  MODEL_BUCKET       — S3 bucket name for model pull (EKS only)
#  AWS_DEFAULT_REGION — AWS region (default: us-east-1)
# ═════════════════════════════════════════════════════════════════════

set -e  # Exit immediately if any command fails

echo "========================================"
echo " Traffic Violation Detection — Starting"
echo "========================================"

# ── Required model files ────────────────────────────────────────────
# If any of these is missing we run the S3 pull, regardless of whether
# /app/models/ is empty — guards against partial/failed syncs.
REQUIRED_MODELS=(
    /app/models/vehicle_detector/weights/best.pt
    /app/models/helmet_detector/weights/best.pt
    /app/models/traffic_light_detector/weights/best.pt
    /app/models/lpr_detector/weights/best.pt
    /app/models/lane_detector/weights/yolop-640-640.onnx
)

# ── Retry wrapper for aws s3 sync ───────────────────────────────────
# The Debian-packaged aws-cli v2.23.x has an intermittent segfault in the
# S3 transfer path; a few retries make container startup deterministic.
s3_sync_retry() {
    local src="$1" dst="$2" extra="${3:-}" attempt
    for attempt in 1 2 3 4 5; do
        if aws s3 sync "$src" "$dst" $extra \
            --region ${AWS_DEFAULT_REGION:-us-east-1} \
            --only-show-errors; then
            return 0
        fi
        echo "[s3] attempt $attempt/5 failed — retrying in 5s..."
        sleep 5
    done
    echo "[s3] ERROR: sync failed after 5 attempts: $src → $dst"
    return 1
}

# ── Check if required models are present ────────────────────────────
# If all required weights exist (from a previous pull or volume mount),
# skip the S3 download. Otherwise pull them from S3.
models_missing=false
for m in "${REQUIRED_MODELS[@]}"; do
    [ -f "$m" ] || models_missing=true
done

if [ "$models_missing" = true ]; then
    echo "[models] Required models missing — checking S3 pull..."

    # ── Try S3 pull (Docker Compose without volume mount / EKS / cloud) ──
    if [ -n "$MODEL_BUCKET" ]; then
        echo "[models] MODEL_BUCKET=$MODEL_BUCKET — pulling from S3..."
        echo "[models] Syncing s3://${MODEL_BUCKET}/models/ → /app/models/"

        # Detector weights are stored in S3 under models/ml/<detector>/weights/*
        # but config.py expects /app/models/<detector>/weights/* — two syncs
        # map the S3 layout onto the runtime layout.
        s3_sync_retry "s3://${MODEL_BUCKET}/models/" "/app/models/" "--exclude ml/*"
        s3_sync_retry "s3://${MODEL_BUCKET}/models/ml/" "/app/models/"

        # Input videos also live in S3 (data/videos/). Fetch them if the
        # container has none (i.e. no ./data volume mount).
        mkdir -p /app/data/videos
        if [ -z "$(ls -A /app/data/videos 2>/dev/null)" ]; then
            echo "[videos] /app/data/videos is empty — pulling videos from S3..."
            s3_sync_retry "s3://${MODEL_BUCKET}/data/videos/" "/app/data/videos/"
            echo "[videos] Video sync complete:"
            ls -la /app/data/videos
        else
            echo "[videos] Videos already present — skipping S3 download"
        fi

        echo "[models] S3 sync complete"
        echo "[models] Contents:"
        find /app/models -name "*.pt" -o -name "*.onnx" | sort
    else
        # ── No volume AND no S3 bucket — warn but don't crash ───────
        # live_test.py will handle the missing models with a descriptive error
        echo "[models] WARNING: MODEL_BUCKET is not set and models are missing"
        echo "[models]"
        echo "[models] LOCAL (Docker Compose):"
        echo "[models]   Ensure ./ml/ folder exists and docker-compose.yml mounts it:"
        echo "[models]     volumes:"
        echo "[models]       - ./ml/:/app/models:ro"
        echo "[models]"
        echo "[models] EKS / Kubernetes:"
        echo "[models]   Set the MODEL_BUCKET environment variable in your deployment:"
        echo "[models]     env:"
        echo "[models]       - name: MODEL_BUCKET"
        echo "[models]         value: \"your-s3-bucket-name\""
        echo "[models]   Also ensure the worker has an IAM role that can read from S3."
        echo "[models]"
        echo "[models] Continuing — live_test.py will report missing model files"
    fi

else
    # ── Required models found (volume mount or previous pull) ───────
    echo "[models] All required models present:"
    find /app/models -name "*.pt" -o -name "*.onnx" | sort
    echo "[models] Skipping S3 download"
fi

echo "========================================"
echo "[app] Starting: $@"
echo "========================================"

# Hand off control to the CMD (default: python live_test.py)
# The 'exec' replaces this shell process with the application so that
# signals (SIGTERM, SIGINT) are handled correctly by the app, not the shell.
exec "$@"
