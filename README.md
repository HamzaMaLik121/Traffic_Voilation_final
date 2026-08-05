# AI-Based Traffic Violation Detection System

> **Final Year Project** — BSCS 2024/25
> Department of Computer Science

An intelligent, real-time traffic violation detection system using computer vision and deep learning. Detects **5 violation types** simultaneously from CCTV footage, stores evidence in a SQLite database, and provides a live monitoring web dashboard.

Built with a **3-service microservices architecture** using Docker Compose and Kubernetes.

---

## Architecture Overview

```
 ┌──────────────┐     shared volume      ┌──────────────┐     shared volume
 │   WORKER     │  ────────────────────►  │     API      │  ────────────────────►
 │  port: none  │      db_data           │   port:5000  │    evidence_data
 │  (internal)  │                        │  (internal)  │
 │              │                        │      │       │
 │  YOLOv8 +    │    ┌──────────────┐    │  host port   │
 │  EasyOCR     │    │  SQLite DB   │    │  5001:5000  │
 │  process     │    │  violations  │    │      │       │
 │  video loop  │    └──────────────┘    │  REST API   │
 │              │                        └──────┬───────┘
 │  evidence ───┤                               │
 │  images  ◄───┤                          HTTP /api/*
 └──────────────┘                               │
                                                │
                                         ┌──────┴───────┐
                                         │  DASHBOARD   │
                                         │   port:8501  │  host port 8502
                                         │  (internal)  │ ──────────────►
                                         │              │  Browser access
                                         │  Streamlit   │
                                         │  Web UI      │
                                         │              │
                                         │  reads evid. │
                                         │  from volume ◄── evidence_data
                                         └──────────────┘
```

### Data Flow

1. **Worker** reads video files from the mounted `./data/` folder (or webcam)
2. **Worker** runs YOLOv8 detection + EasyOCR on every 3rd frame
3. **Worker** writes violations to the shared SQLite database (`db_data` volume)
4. **Worker** saves evidence JPGs + `latest_frame.jpg` to the shared outputs volume (`evidence_data`)
5. **API** reads from the shared database (read-only) and serves evidence images + MJPEG stream
6. **Dashboard** fetches violation data from the API via HTTP and displays evidence images from the shared volume

### Service Dependency Chain

```
worker ──(writes to)──► db_data ◄──(reads from, ro)── api ◄──(HTTP calls)── dashboard
worker ──(writes to)──► evidence_data ◄──(reads from)── api (MJPEG live feed)
worker ──(writes to)──► evidence_data ◄──(reads from)── dashboard (evidence viewer)
```

### Networking

- All 3 services are on the default Docker Compose bridge network
- Services resolve each other by container name: `traffic-worker`, `traffic-api`, `traffic-dashboard`
- Only **api** (host port 5001 → container 5000) and **dashboard** (host port 8502 → container 8501) are exposed — worker is internal-only
- The dashboard calls the API at `http://api:5000` (Docker DNS resolution)
- The browser accesses the dashboard at `http://localhost:8502`

### Service Images

| Service | Role | Tech Stack | Image Size |
|---------|------|------------|-----------|
| **Worker** | CV/ML detection pipeline — processes video, detects violations | PyTorch, YOLOv8, EasyOCR, OpenCV | ~2.5 GB |
| **API** | Flask REST API — serves violation data and live feed | Flask, SQLite | ~130 MB |
| **Dashboard** | Streamlit web UI — live monitoring, charts, evidence viewer | Streamlit, Pandas, Plotly | ~200 MB |

---

## Violations Detected

| # | Violation | Method | Accuracy |
|---|-----------|--------|----------|
| 1 | **No Helmet** | YOLOv8 helmet detector + IoU matching with riders | 72.4% mAP50 |
| 2 | **Red Light** | YOLOv8 traffic light state classifier + vehicle position | 94.1% mAP50 |
| 3 | **Over Speed** | Centroid tracking + pixel-to-meter calibration | Speed limit configurable |
| 4 | **Lane Violation** | OpenCV HoughLinesP lane detection (no ML model) | — |
| 5 | **Illegal U-Turn** | Heading reversal analysis (≥150° turn) | — |

**Performance:** 36–98 FPS on Intel CPU (no GPU required) via frame-skip optimisation.

**License Plate Recognition:** YOLOv8 plate detector + EasyOCR — 97.5% detection, 85.3% OCR character accuracy.

---

## Quick Start (Docker Compose)

### Prerequisites
- Docker Engine 24+ with Docker Compose plugin
- At least 4 GB RAM allocated to Docker
- ~3 GB free disk space for images + models

### Step 1 — Prepare model weights

Place trained YOLOv8 model weights in the `ml/` directory:

```
ml/
├── vehicle_detector/weights/best.pt       # Vehicle detection
├── helmet_detector/weights/best.pt        # Helmet detection
├── traffic_light_detector/weights/best.pt # Traffic light recognition
├── lpr_detector/weights/best.pt           # License plate detection
└── lane_detector/weights/yolop-640-640.onnx  # Lane detection (optional)
```

> **Note:** A fallback `yolov8n.pt` is included in the worker image for COCO-based vehicle detection. Trained models give better accuracy.

### Step 2 — Add test video

Place an `.mp4` or `.avi` file in `data/videos/`:

```bash
mkdir -p data/videos
cp /path/to/your/test_video.mp4 data/videos/
```

### Step 3 — Build and start

```bash
# Build all three images
docker compose build

# Start all services
docker compose up -d

# Watch worker logs
docker compose logs -f worker
```

### Step 4 — Access the dashboard

Open **http://localhost:8502** in your browser.

| URL | What you get |
|-----|-------------|
| http://localhost:8502 | Streamlit Dashboard (violation records, charts, evidence) |
| http://localhost:5001/health | API health check |
| http://localhost:5001/statistics | API — violation statistics (JSON) |
| http://localhost:5001/violations | API — violation records (JSON) |
| http://localhost:5001/live | Live MJPEG detection feed |

---

## Project Structure

```
traffic_Devops/
├── docker-compose.yml              # Orchestrates all 3 services
│
├── worker/                         # ML Detection Pipeline
│   ├── Dockerfile                  # Worker container (~2.5 GB)
│   ├── entrypoint.sh               # Model loading (local / S3)
│   ├── requirements-worker.txt     # Python deps (PyTorch, YOLO, EasyOCR)
│   ├── live_test.py                # Main pipeline entry point
│   ├── setup_lanes.py              # Interactive lane boundary drawing
│   ├── diagnostic.py               # Model diagnostic test script
│   ├── config/
│   │   ├── config.py               # All settings (thresholds, paths)
│   │   └── lane_config.json        # Lane boundary coordinates
│   ├── app/
│   │   ├── db/database.py          # SQLite violation database
│   │   ├── detection/              # Detection modules (5 violation types)
│   │   │   ├── vehicle_detector.py
│   │   │   ├── helmet_detector.py
│   │   │   ├── traffic_light_detector.py
│   │   │   ├── speed_estimator.py
│   │   │   ├── lane_detector.py
│   │   │   ├── poly_lane_detector.py
│   │   │   ├── manual_lane_detector.py
│   │   │   ├── yolop_lane_detector.py
│   │   │   ├── uturn_detector.py
│   │   │   └── lpr_detector.py
│   │   ├── lpr/plate_recognizer.py # License plate OCR
│   │   └── violation_processor.py  # Orchestrates all detectors
│   └── tools/
│       └── calibrate_speed.py      # Speed calibration tool
│
├── api/                            # Flask REST API
│   ├── Dockerfile                  # API container (~130 MB)
│   ├── requirements-api.txt        # Python deps (Flask only)
│   ├── main.py                     # API entry point
│   ├── config/config.py            # API configuration
│   └── app/
│       ├── routes.py               # REST endpoints + MJPEG stream
│       └── db/database.py          # Read-only DB access
│
├── dashboard/                      # Streamlit Web UI
│   ├── Dockerfile                  # Dashboard container (~200 MB)
│   ├── requirements-dashboard.txt  # Python deps (Streamlit, Pandas, Plotly)
│   ├── .streamlit/config.toml      # Streamlit theme/settings
│   └── app/dashboard.py            # Dashboard pages (3 pages)
│
├── ml/                             # Trained model weights (mounted into worker)
│   ├── vehicle_detector/weights/
│   ├── helmet_detector/weights/
│   ├── traffic_light_detector/weights/
│   ├── lpr_detector/weights/
│   └── lane_detector/weights/
│
├── data/                           # Video data + training datasets
│   ├── videos/                     # Place .mp4 files here
│   ├── raw/                        # Raw datasets (gitignored)
│   └── processed/                  # Processed datasets (gitignored)
│
├── tests/                          # System tests
│   └── run_system_tests.py         # 10-case formal test runner
│
├── src/                            # Training scripts (legacy / optional)
│   └── training/
│       └── train_models.py         # Model training pipeline
│
├── kubernetes/                     # Kubernetes deployment manifests
│   ├── namespace.yml
│   ├── pv-pvc.yml                  # Persistent volumes for DB + evidence
│   ├── worker/deployment.yml
│   ├── api/deployment.yml
│   ├── api/service.yml
│   ├── dashboard/deployment.yml
│   └── dashboard/service.yml
│
└── security/                       # Security scan reports (Trivy)
    ├── trivy-backend.txt
    └── trivy-dashboard.txt
```

---

## Running Services Individually

### Worker (Detection Pipeline)

```bash
# Build and run worker alone
docker compose build worker
docker compose up worker
```

### API (REST API)

```bash
# Build and run API alone (no worker needed)
docker compose build api
docker compose up api
# Test: curl http://localhost:5001/health
```

### Dashboard (Streamlit UI)

```bash
# Build and run dashboard (requires API)
docker compose build dashboard
docker compose up dashboard
# Open: http://localhost:8502
```

---

## Configuration

All configuration is done via **environment variables** in `docker-compose.yml`.

| Variable | Default | Service | Description |
|----------|---------|---------|-------------|
| `LOOP_VIDEO` | `1` | Worker | Loop video when it ends (`0` = process once) |
| `HEADLESS` | `1` | Worker | Disable `cv2.imshow()` GUI |
| `MODEL_DIR` | `/app/models` | Worker | Path to model weights |
| `CONFIDENCE_THRESHOLD` | `0.25` | Worker | YOLO detection confidence threshold |
| `SPEED_LIMIT_KMH` | `60` | Worker | Speed limit for over-speed violations |
| `PIXEL_TO_METER_RATIO` | `0.011640` | Worker | Camera calibration ratio |
| `API_HOST` | `0.0.0.0` | API | Flask bind address |
| `API_PORT` | `5000` | API | Flask listen port |
| `STREAM_URL` | `http://localhost:5001` | Dashboard | API URL (browser-accessible) |
| `API_URL` | `http://api:5000` | Dashboard | API URL (internal Docker DNS) |

### Speed Calibration

For accurate speed readings, calibrate the pixel-to-meter ratio for your camera:

```bash
# Run inside the worker container
docker compose exec worker python tools/calibrate_speed.py

# Or specify a video:
docker compose exec worker python tools/calibrate_speed.py /app/data/videos/your_video.mp4
```

**Instructions:**
1. A video frame opens
2. Click 2 points on the road that span a known real-world distance (e.g., lane width 3.5 m)
3. Enter the real distance in metres when prompted
4. Update the `PIXEL_TO_METER_RATIO` in `docker-compose.yml` under worker → environment

---

## Kubernetes Deployment

```bash
# 1. Apply namespace and persistent volumes
kubectl apply -f kubernetes/namespace.yml
kubectl apply -f kubernetes/pv-pvc.yml

# 2. Prepare model weights on each node
#    Copy .pt files to /mnt/models/ on the node(s)

# 3. Deploy services
kubectl apply -f kubernetes/worker/deployment.yml
kubectl apply -f kubernetes/api/deployment.yml
kubectl apply -f kubernetes/api/service.yml
kubectl apply -f kubernetes/dashboard/deployment.yml
kubectl apply -f kubernetes/dashboard/service.yml
```

### Kubernetes Architecture

| Component | Type | Replicas | Port |
|-----------|------|----------|------|
| Worker | Deployment | 1 | Internal only |
| API | Deployment + Service (ClusterIP) | 2 | 5000 |
| Dashboard | Deployment + Service (LoadBalancer) | 2 | 8501 |
| Database | PersistentVolumeClaim (hostPath) | — | — |
| Evidence | PersistentVolumeClaim (hostPath) | — | — |
| Models | PersistentVolumeClaim (hostPath) | — | — |

---

## Running Formal Tests

```bash
# After the worker has processed some video and generated violations:
docker compose exec worker python tests/run_system_tests.py

# Or run locally (if DB already exists):
python tests/run_system_tests.py
```

Tests 10 cases:

| TC | Test | Target |
|----|------|--------|
| 1 | Vehicle Detection | ≥100 violations implies detection works |
| 2 | Traffic Light Recognition | Module runs without error |
| 3 | No-Helmet Detection | Evidence images saved |
| 4 | License Plate Recognition | Plate text in DB records |
| 5 | Over-Speed Detection | Speed violations flagged |
| 6 | Lane Violation Detection | Module runs without error |
| 7 | Illegal U-Turn Detection | U-turn evidence saved |
| 8 | Real-Time Performance | ≥10 FPS on CPU |
| 9 | Database Persistence | Records survive restart |
| 10 | Evidence Saving | JPG files saved per violation |

---

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Object Detection | YOLOv8n (Ultralytics) |
| Computer Vision | OpenCV 4.10 |
| OCR | EasyOCR + Tesseract (fallback) |
| Deep Learning | PyTorch 2.6 (CPU) |
| Database | SQLite (via Python sqlite3) |
| REST API | Flask 3.0 |
| Web Dashboard | Streamlit 1.59 |
| Containerisation | Docker + Compose |
| Orchestration | Kubernetes (EKS) |
| Language | Python 3.12 |

---

## Development

### Building Images Individually

```bash
# Worker
docker build -t traffic-worker:latest worker/

# API
docker build -t traffic-api:latest api/

# Dashboard
docker build -t traffic-dashboard:latest dashboard/
```

### Testing Changes Locally

```bash
# Rebuild and restart a specific service after code changes
docker compose build worker && docker compose up -d worker
docker compose logs -f worker
```

### Security Scanning

```bash
# Using Trivy
trivy image traffic-worker:latest --severity HIGH,CRITICAL
trivy image traffic-api:latest --severity HIGH,CRITICAL
trivy image traffic-dashboard:latest --severity HIGH,CRITICAL
```

---

## Team

| Member | Role |
|--------|------|
| Muhammad Jawad | Violation Detection Pipeline, Speed Calibration, Lane & U-Turn Detection |
| Hamza Ali | License Plate Recognition, Database Design, API & Kubernetes |
| Irum Saba | Backend Integration, GUI/Dashboard |

---

## Test Results (Latest Run)

Results below are from the most recent system test run. Run `python tests/run_system_tests.py` after processing video to generate fresh results.

| TC | Test | Result |
|----|------|--------|
| 1 | Vehicle Detection | [PASS] — 99.5% mAP50 |
| 2 | Traffic Light Recognition | [PASS] — 94.1% mAP50 |
| 3 | Helmet Violation Detection | [PASS] — 72.4% mAP50 |
| 4 | License Plate Recognition | [PASS] — 97.5% mAP50, 85.3% OCR |
| 5 | Over-Speed Detection | [PASS] — Events detected |
| 6 | Lane Violation Detection | [PASS] — Module operational |
| 7 | U-Turn Detection | [PASS] — Events detected |
| 8 | Real-Time Performance | [PASS] — 36–98 FPS on CPU |
| 9 | Database Persistence | [PASS] — Records persisted |
| 10 | Evidence Image Saving | [PASS] — JPG files saved |

**10 / 10 tests passed.**

---

## License

MIT License — See LICENSE file for details.
