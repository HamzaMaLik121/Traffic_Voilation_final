"""
Configuration settings for Traffic Violation Detection System — Worker Service

All paths are now environment-variable-driven so they work correctly
inside Docker containers regardless of the folder structure.
"""

import os
from pathlib import Path

# Base paths — driven by env vars with sensible Docker defaults
MODEL_DIR = Path(os.getenv("MODEL_DIR", "/app/models"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/app/outputs"))
DATABASE_DIR = Path(os.getenv("DATABASE_DIR", "/app/database"))
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/app/config"))

# Model settings
VEHICLE_MODEL = os.getenv("VEHICLE_MODEL", str(MODEL_DIR / "vehicle_detector" / "weights" / "best.pt"))
HELMET_MODEL = os.getenv("HELMET_MODEL", str(MODEL_DIR / "helmet_detector" / "weights" / "best.pt"))
TRAFFIC_LIGHT_MODEL = os.getenv("TRAFFIC_LIGHT_MODEL", str(MODEL_DIR / "traffic_light_detector" / "weights" / "best.pt"))
LPR_MODEL = os.getenv("LPR_MODEL", str(MODEL_DIR / "lpr_detector" / "weights" / "best.pt"))
LANE_MODEL = os.getenv("LANE_MODEL", str(MODEL_DIR / "lane_detector" / "weights" / "yolop-640-640.onnx"))

# Fallback to bundled yolov8n.pt for vehicle detection backbone
# COCO-pretrained yolov8n.pt — tries multiple locations so it works
# in Docker (/app/yolov8n.pt), with volume mount (/app/models/yolov8n.pt),
# and in local runs (./yolov8n.pt). The first path found wins.
_FALLBACK_CANDIDATES = [
    "/app/yolov8n.pt",                 # Docker (baked into image via COPY)
    str(MODEL_DIR / "yolov8n.pt"),      # Volume mount (user places in ./ml/)
    "yolov8n.pt",                       # Local run (project root)
]
_DEFAULT_FALLBACK = next(
    (p for p in _FALLBACK_CANDIDATES if os.path.exists(p)),
    _FALLBACK_CANDIDATES[0]  # Docker path as ultimate fallback
)
FALLBACK_VEHICLE_MODEL = os.getenv("FALLBACK_VEHICLE_MODEL", _DEFAULT_FALLBACK)

YOLO_MODEL = VEHICLE_MODEL
CONFIDENCE_THRESHOLD = 0.25
IOU_THRESHOLD = 0.45
HELMET_CONFIDENCE_THRESHOLD = 0.20

# Detection settings
DETECT_VEHICLES = True
DETECT_HELMETS = True
DETECT_TRAFFIC_LIGHTS = True
DETECT_LANES = True

# Violation types
VIOLATIONS = {
    "NO_HELMET": "No Helmet Violation",
    "RED_LIGHT": "Red Light Violation",
    "OVER_SPEED": "Over Speeding",
    "LANE_VIOLATION": "Lane Violation",
    "ILLEGAL_UTURN": "Illegal U-Turn"
}

# Speed detection settings
SPEED_LIMIT_KMH = 60
SPEED_DETECTION_THRESHOLD = 25
FRAME_RATE = 30
PIXEL_TO_METER_RATIO = float(os.getenv("PIXEL_TO_METER_RATIO", "0.011640"))

# License Plate Recognition
LPR_ENABLED = True
OCR_ENGINE = "easyocr"
LPR_CONFIDENCE_THRESHOLD = 0.6

# Database settings
DATABASE_NAME = "violations.db"
DATABASE_PATH = DATABASE_DIR / DATABASE_NAME

# Video processing
VIDEO_EXTENSIONS = ['.mp4', '.avi', '.mov', '.mkv']
FRAME_SKIP = 2
MAX_FRAME_WIDTH = 1280
MAX_FRAME_HEIGHT = 720

# Output settings
SAVE_EVIDENCE = True
EVIDENCE_FORMAT = "jpg"
SAVE_ANNOTATED_VIDEO = True

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
