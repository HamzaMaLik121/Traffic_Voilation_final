#!/bin/bash
# ═════════════════════════════════════════════════════════════════════
#  healthcheck.sh — Worker Service Readiness Check
#
#  The worker is considered HEALTHY only when BOTH of these are true:
#
#    1. All required model weights are on disk
#       (entrypoint.sh pulled them from S3 and wrote .models_ready)
#    2. The shared SQLite database exists
#       (live_test.py creates /app/database/violations.db once the
#        detection pipeline has started successfully)
#
#  Why BOTH? The api and dashboard services use
#  `depends_on: worker: condition: service_healthy`, so this healthcheck
#  is the gate that guarantees:
#     • Models are pulled from S3 FIRST (api/dashboard never start before)
#     • The worker app is actually up and writing to the shared DB
#
#  NOTE: start_period in the compose file / Dockerfile must be generous
#  enough to cover the S3 download (hundreds of MB) on first boot.
#  NOTE: REQUIRED_MODELS below must stay in sync with worker/entrypoint.sh.
#  NOTE: This asserts assets are present + the DB was created — it does not
#        probe the live app process. A crashed PID 1 is handled by the
#        container restart policy instead.
# ═════════════════════════════════════════════════════════════════════

REQUIRED_MODELS=(
    /app/models/vehicle_detector/weights/best.pt
    /app/models/helmet_detector/weights/best.pt
    /app/models/traffic_light_detector/weights/best.pt
    /app/models/lpr_detector/weights/best.pt
    /app/models/lane_detector/weights/yolop-640-640.onnx
    /app/models/yolov8n.pt
)

# 1) All required model weights must exist
for m in "${REQUIRED_MODELS[@]}"; do
    if [ ! -f "$m" ]; then
        echo "worker not ready: missing model $m" >&2
        exit 1
    fi
done

# 2) The worker app must have started and created the shared DB
if [ ! -f /app/database/violations.db ]; then
    echo "worker not ready: /app/database/violations.db does not exist yet" >&2
    exit 1
fi

# Also require the S3-sync completion marker (written by entrypoint.sh)
if [ ! -f /app/models/.models_ready ]; then
    echo "worker not ready: model sync marker missing" >&2
    exit 1
fi

echo "worker healthy: models present, DB ready"
exit 0
