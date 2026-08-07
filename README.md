# AI-Based Traffic Violation Detection System

> **Final Year Project** — BSCS 2024/25
> Department of Computer Science

An intelligent, real-time traffic violation detection system using computer vision and deep learning. Detects **5 violation types** simultaneously from CCTV footage, stores evidence in a SQLite database, and provides a live monitoring web dashboard.

Built with a **3-service microservices architecture** using Docker Compose.

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

1. **Worker** pulls model weights and test videos from **S3** on startup (see Quick Start below)
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

### Startup Order (Compose `depends_on`)

`docker compose up` starts services in dependency order:

1. **worker** starts first — `entrypoint.sh` verifies AWS credentials, syncs
   models + videos from S3, then writes a readiness marker
   (`/app/database/.worker-configured`) only after all required models are
   verified present. The worker is marked **healthy** only once that marker
   exists AND the app has created the SQLite database.
2. **api** starts only after the worker is **healthy** (`service_healthy`).
3. **dashboard** starts only after **both** the worker and the api are healthy.

> On the very first run the S3 sync (models + ~300 MB video) can take
> **10–20 minutes** — the API and dashboard will stay down until the worker
> finishes. Watch progress with `docker compose logs -f worker`.

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
- AWS CLI configured on the host (`aws configure`) with credentials that can read the project S3 bucket
- At least 4 GB RAM allocated to Docker
- ~3 GB free disk space for images + models

### Step 1 — Clone the repository

```bash
git clone https://github.com/HamzaMaLik121/Traffic_voilation_detection_system.git
cd Traffic_voilation_detection_system
```

### Step 2 — Configure AWS credentials

Model weights and test videos are **not** stored in the repo (they're gitignored).
The worker pulls them automatically from S3 on container startup.

```bash
# The project S3 bucket is: traffic-violation-project-data-models
aws configure
# Enter your AWS Access Key ID, Secret Access Key, and region (us-east-1)
```

> Your AWS credentials are mounted read-only into the worker container
> (`~/.aws` → `/root/.aws`). Only the worker needs S3 access — the API and
> dashboard never touch S3.

### Step 3 — Build and start

```bash
docker compose up --build
```

That's it — the worker's `entrypoint.sh` will:

1. Verify your AWS credentials (`aws sts get-caller-identity`)
2. Sync model weights from `s3://traffic-violation-project-data-models/models/` into `/app/models/`
3. Sync test videos from `s3://traffic-violation-project-data-models/data/videos/` into `/app/data/videos/`
4. Fail fast with a clear error if credentials are missing or the sync fails

On first run the worker's S3 sync can take **10–20 minutes**. Because the
API and dashboard declare `depends_on: worker: condition: service_healthy`,
they will **not** start until the worker has finished configuring — so
`docker compose up` may appear to sit at the worker step for a while. That's
by design. Watch progress with:

```bash
docker compose logs -f worker
```

### Step 4 — Access the dashboard

Open **http://localhost:8502** in your browser.

| URL | What you get |
|-----|-------------|
| http://localhost:8502 | Streamlit Dashboard (violation records, charts, evidence) |
| http://localhost:5001/health | API health check |
| http://localhost:5001/docs/ | Swagger / OpenAPI interactive docs |
| http://localhost:5001/statistics | API — violation statistics (JSON) |
| http://localhost:5001/violations | API — violation records (JSON) |
| http://localhost:5001/live | Live MJPEG detection feed |

---

## Project Structure

```
Traffic_voilation_detection_system/
├── docker-compose.yml              # Orchestrates all 3 services
│
├── worker/                         # ML Detection Pipeline
│   ├── Dockerfile                  # Worker container (~2.5 GB)
│   ├── entrypoint.sh               # S3 model/video sync + app start (fail-fast)
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
│   ├── requirements-api.txt        # Python deps (Flask + flasgger)
│   ├── main.py                     # API entry point
│   ├── config/config.py            # API configuration
│   ├── tests/                      # API unit tests (pytest)
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
├── ml/                             # Model metadata (args.yaml, results.csv)
│   └── <detector>/                 # Weights are pulled from S3, not committed
│
├── data/                           # Video data (gitignored, pulled from S3)
│   └── videos/                     # test_video.mp4 synced at startup
│
├── tests/                          # System tests
│   └── run_system_tests.py         # 10-case formal test runner
│
└── src/                            # Training scripts (legacy / optional)
    └── training/
        └── train_models.py         # Model training pipeline
```

---

## Running Services Individually

### Worker (Detection Pipeline)

```bash
docker compose build worker
docker compose up worker
```

### API (REST API)

```bash
docker compose build api
docker compose up api
# Test: curl http://localhost:5001/health
```

### Dashboard (Streamlit UI)

```bash
docker compose build dashboard
docker compose up dashboard
# Open: http://localhost:8502
```

---

## Configuration

All configuration is done via **environment variables** in `docker-compose.yml`.

| Variable | Default | Service | Description |
|----------|---------|-------------|---------|
| `MODEL_BUCKET` | `traffic-violation-project-data-models` | Worker | S3 bucket with `models/` and `data/videos/` |
| `AWS_DEFAULT_REGION` | `us-east-1` | Worker | AWS region for S3 sync |
| `AWS_EC2_METADATA_DISABLED` | `true` | Worker | Fail fast on missing creds (no IMDS lookup) |
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

## Running Formal Tests

After the worker has processed some video and generated violations, run the
10-case suite against the live database + evidence volumes (any Python image
works — the runner is stdlib-only):

```bash
docker run --rm \
  -v "$PWD:/repo" -w /repo \
  -v traffic_voilation_detection_system_db_data:/app/database \
  -v traffic_voilation_detection_system_evidence_data:/app/outputs \
  traffic-api:latest python tests/run_system_tests.py
```

> The volume names follow `<compose-project>_db_data` and
> `<compose-project>_evidence_data` — check `docker volume ls` if you cloned
> into a differently-named directory.

Results are saved to `tests/test_results.json` (gitignored).

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
| Model/Data Storage | AWS S3 |
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
| Hamza Ali | License Plate Recognition, Database Design, API |
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
