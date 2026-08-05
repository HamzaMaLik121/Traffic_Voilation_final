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

# ── Check if models are already present ─────────────────────────────
# If /app/models/ has files (from Docker volume mount or pre-baked image),
# skip the S3 download. An empty directory means no volume mount.
if [ -z "$(ls -A /app/models 2>/dev/null)" ]; then
    echo "[models] /app/models/ is empty — no volume mount detected"

    # ── Try S3 pull (Docker Compose without volume mount / EKS / cloud) ──
    if [ -n "$MODEL_BUCKET" ]; then
        echo "[models] MODEL_BUCKET=$MODEL_BUCKET — pulling from S3..."
        echo "[models] Syncing s3://${MODEL_BUCKET}/models/ → /app/models/"

        # Detector weights are stored in S3 under models/ml/<detector>/weights/*
        # but config.py expects /app/models/<detector>/weights/* — two syncs
        # map the S3 layout onto the runtime layout.
        aws s3 sync s3://${MODEL_BUCKET}/models/ /app/models/ \
            --exclude 'ml/*' \
            --region ${AWS_DEFAULT_REGION:-us-east-1} \
            --only-show-errors
        aws s3 sync s3://${MODEL_BUCKET}/models/ml/ /app/models/ \
            --region ${AWS_DEFAULT_REGION:-us-east-1} \
            --only-show-errors

        # Input videos also live in S3 (data/videos/). Fetch them if the
        # container has none (i.e. no ./data volume mount).
        mkdir -p /app/data/videos
        if [ -z "$(ls -A /app/data/videos 2>/dev/null)" ]; then
            echo "[videos] /app/data/videos is empty — pulling videos from S3..."
            aws s3 sync s3://${MODEL_BUCKET}/data/videos/ /app/data/videos/ \
                --region ${AWS_DEFAULT_REGION:-us-east-1} \
                --only-show-errors
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
        echo "[models] WARNING: MODEL_BUCKET is not set and /app/models/ is empty"
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
    # ── Models found via volume mount (Docker Compose / local) ───────
    echo "[models] Models found via volume mount:"
    find /app/models -name "*.pt" -o -name "*.onnx" | sort
    echo "[models] Skipping S3 download (already present)"
fi

echo "========================================"
echo "[app] Starting: $@"
echo "========================================"

# Hand off control to the CMD (default: python live_test.py)
# The 'exec' replaces this shell process with the application so that
# signals (SIGTERM, SIGINT) are handled correctly by the app, not the shell.
exec "$@"
