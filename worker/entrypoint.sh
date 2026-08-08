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
#  ── MODEL LOADING STRATEGY (fully automated, zero manual steps) ─────
#
#  The heavy assets (trained weights, videos) are NOT stored in Git.
#  They live in S3 (bucket: traffic-violation-project-data-models).
#  This script pulls them automatically on first container start:
#
#    1. Verify AWS credentials are configured (aws configure)
#    2. Sync s3://$MODEL_BUCKET/models/  → /app/models/   (detector weights)
#    3. Sync s3://$MODEL_BUCKET/data/videos/ → /app/data/videos/ (input video)
#    4. Verify every required weight file exists — fail loudly if not
#    5. Write /app/models/.models_ready marker (used by the healthcheck)
#    6. exec the application CMD
#
#  ── REQUIRED MODEL FILES ───────────────────────────────────────────
#  The worker expects these model weights:
#    /app/models/vehicle_detector/weights/best.pt
#    /app/models/helmet_detector/weights/best.pt
#    /app/models/traffic_light_detector/weights/best.pt
#    /app/models/lpr_detector/weights/best.pt
#    /app/models/lane_detector/weights/yolop-640-640.onnx
#    /app/models/yolov8n.pt  (COCO backbone — primary vehicle detector)
#
#  ── ENVIRONMENT VARIABLES ──────────────────────────────────────────
#  MODEL_BUCKET       — S3 bucket name for model pull (required)
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
    /app/models/yolov8n.pt
)

# ── Retry wrapper for aws s3 sync ───────────────────────────────────
# NOTE: REQUIRED_MODELS below must stay in sync with worker/healthcheck.sh.
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

    # ── Try S3 pull (Docker Compose / EC2 / EKS with IAM role) ──
    if [ -n "$MODEL_BUCKET" ]; then
        # ── AWS credential check ──────────────────────────────────
        # Only needed when we actually pull from S3 (models cached in
        # the model_data volume skip this entirely). Give a clear,
        # actionable error instead of a cryptic S3 permission failure
        # 3 minutes later.
        if aws sts get-caller-identity >/dev/null 2>&1; then
            echo "[aws] Credentials OK."
        else
            echo "[aws] ERROR: AWS credentials not found or invalid."
            echo "[aws]"
            echo "[aws] Run 'aws configure' on the host machine, then start again:"
            echo "[aws]   aws configure          # AWS Access Key, Secret Key, region us-east-1"
            echo "[aws]   docker compose up"
            echo "[aws]"
            echo "[aws] The worker pulls models + videos from S3 automatically."
            exit 1
        fi

        echo "[models] MODEL_BUCKET=$MODEL_BUCKET — pulling from S3..."
        echo "[models] Syncing s3://${MODEL_BUCKET}/models/ → /app/models/"

        # Detector weights are stored in S3 under models/ml/<detector>/weights/*
        # but config.py expects /app/models/<detector>/weights/* — two syncs
        # map the S3 layout onto the runtime layout.
        #   sync 1: models/*  (yolov8n.pt, worker/) → /app/models/   [ml/ excluded]
        #   sync 2: models/ml/<detector>/...       → /app/models/<detector>/...
        s3_sync_retry "s3://${MODEL_BUCKET}/models/" "/app/models/" "--exclude ml/*"
        s3_sync_retry "s3://${MODEL_BUCKET}/models/ml/" "/app/models/"

        # Input videos also live in S3 (data/videos/). Fetch them if the
        # container has none (i.e. no ./data volume mount).
        mkdir -p /app/data/videos
        if [ -z "$(ls -A /app/data/videos 2>/dev/null)" ]; then
            echo "[videos] /app/data/videos is empty — pulling videos from S3..."
            if s3_sync_retry "s3://${MODEL_BUCKET}/data/videos/" "/app/data/videos/"; then
                echo "[videos] Video sync complete:"
                ls -la /app/data/videos
            else
                echo "[videos] WARNING: video sync failed — worker will wait for a video source."
                echo "[videos]          (You can mount one at /app/data/videos/ and restart.)"
            fi
        else
            echo "[videos] Videos already present — skipping S3 download"
        fi

        # ── Verify every required file survived the sync ─────────────
        # Fail loudly (and let restart: on-failure retry) instead of
        # silently starting with a broken detector pipeline.
        missing=()
        for m in "${REQUIRED_MODELS[@]}"; do
            [ -f "$m" ] || missing+=("$m")
        done

        if [ ${#missing[@]} -gt 0 ]; then
            echo "[models] ERROR: The following required model files are STILL missing after the S3 sync:"
            printf '  - %s\n' "${missing[@]}"
            echo "[models]"
            echo "[models] Check that s3://${MODEL_BUCKET}/models/ contains:"
            echo "[models]   ml/<detector>/weights/*.pt  and  yolov8n.pt"
            echo "[models] and that your AWS user has s3:GetObject / s3:ListBucket on this bucket."
            exit 1
        fi

        # Readiness marker — consumed by the healthcheck so api/dashboard
        # only start once the models are actually on disk.
        touch /app/models/.models_ready
        echo "[models] S3 sync complete — all required models present."
        echo "[models] Contents:"
        find /app/models \( -name "*.pt" -o -name "*.onnx" \) | sort
    else
        # ── No volume AND no S3 bucket — cannot run ─────────────────
        echo "[models] ERROR: MODEL_BUCKET is not set and models are missing."
        echo "[models] Set MODEL_BUCKET in docker-compose.yml (e.g. traffic-violation-project-data-models)"
        echo "[models] or mount a volume containing the weights at /app/models."
        exit 1
    fi

else
    # ── Required models found (volume mount or previous pull) ───────
    # No AWS needed — models are already cached (model_data volume).
    touch /app/models/.models_ready
    echo "[models] All required models present:"
    find /app/models \( -name "*.pt" -o -name "*.onnx" \) | sort
    echo "[models] Skipping S3 download"
fi

echo "========================================"
echo "[app] Starting: $@"
echo "========================================"

# Hand off control to the CMD (default: python live_test.py)
# The 'exec' replaces this shell process with the application so that
# signals (SIGTERM, SIGINT) are handled correctly by the app, not the shell.
exec "$@"
