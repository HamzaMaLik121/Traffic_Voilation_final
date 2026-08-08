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

> **Zero manual steps.** Model weights and test videos are NOT stored in Git —
> they are pulled automatically from S3 on first boot. Just clone, configure AWS,
> and run `docker compose up`. That's it.

### Prerequisites
- Docker Engine 24+ with Docker Compose plugin
- At least 4 GB RAM allocated to Docker
- ~3 GB free disk space for images + models
- AWS CLI configured with credentials that can read the S3 bucket
  (`traffic-violation-project-data-models`)

### Step 1 — Configure AWS (one-time)

```bash
aws configure
# AWS Access Key ID:     <your key>
# AWS Secret Access Key: <your secret>
# Default region name:   us-east-1
```

> The worker mounts `~/.aws` into the container and uses it to sync models +
> videos from S3 automatically. (On EKS/Kubernetes, replace with an IAM role.)

### Step 2 — Clone + start

```bash
git clone <this-repo-url>
cd Traffic_voilation_detection_system

# Option A: one command (build + start)
docker compose up -d --build

# Option B: use the Makefile (same thing)
make up-build
```

What happens automatically on first boot:

1. `worker` starts → **pulls all model weights from S3** into `/app/models`
   (vehicle, helmet, traffic-light, LPR, lane + `yolov8n.pt` backbone)
2. `worker` **pulls the test video** from S3 into `/app/data/videos`
3. `worker` becomes **healthy** only after models are on disk and the shared
   database exists (`worker/healthcheck.sh`)
4. `api` starts **only after worker is healthy** (`depends_on: service_healthy`)
5. `dashboard` starts **only after api + worker are healthy**

So the dashboard and API never start before the model data has been pulled.

```bash
# Watch the worker pull models from S3 and start
 docker compose logs -f worker
```

### One-click reset (`make clean` / `make reset`)

Everything (containers, named volumes, images, build cache) can be wiped with
one command — the next `docker compose up` then re-pulls everything from S3
automatically:

```bash
make clean   # wipe containers + volumes + images + build cache
make up      # rebuild + start — auto-pulls models/videos from S3 again

# Or the full cycle in one go:
make reset   # clean + up-build
```

### Manual `docker build` (no compose) — still fully automatic

You can also build and run the worker image by hand. The S3 pull happens in
`entrypoint.sh` at container start, so nothing is downloaded manually:

```bash
# Build
 docker build -t traffic-worker:latest worker/

# Run — models + videos are auto-pulled from S3 on start.
# Mount your AWS credentials (or export AWS_ACCESS_KEY_ID etc.) so the
# container can authenticate.
 docker run -d --name traffic-worker \
   -v ~/.aws:/root/.aws:ro \
   -v traffic_db:/app/database -v traffic_out:/app/outputs \
   traffic-worker:latest

# MODEL_BUCKET defaults to traffic-violation-project-data-models in the image.
```

> The image's default `MODEL_BUCKET` means a bare `docker run traffic-worker`
> will attempt the S3 pull; only AWS credentials are still required (from
> `~/.aws` or `AWS_*` env vars).

> **First boot takes a few minutes** — the worker downloads ~350MB of models
> (+ the test video) from S3 before `api` and `dashboard` are allowed to start.
> You'll see `Container traffic-worker Waiting` while this happens. That's by
> design — nothing starts before the model data is on disk.

> **Stuck on `Waiting`?** Check the worker logs. If it's crash-looping with an
> AWS error, your credentials are wrong/expired — re-run `aws configure`.
> If it's stuck on `[s3] ERROR`, check that your IAM user can `s3:GetObject`
> on the `traffic-violation-project-data-models` bucket.

> **`dependency failed to start: container traffic-worker is unhealthy`?**
> You are running an **old copy of the code** (this error comes from the
> pre-fix compose file that had a too-short healthcheck window). Make sure
> you are on the latest `master` (`git pull origin master` or re-clone), then
> wipe the old state and rebuild:
>
> ```bash
> git pull origin master
> docker rm -f traffic-worker traffic-api traffic-dashboard  # clear old containers
> docker compose up -d --build   # or: make reset
> ```
>
> The first boot legitimately takes a few minutes while the worker downloads
> models from S3 — `Container traffic-worker Waiting` during that time is
> normal and by design (api/dashboard wait until the worker is fully ready).

### Step 3 — Access the dashboard

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
├── ml/                             # Model metadata only (weights live in S3)
│   ├── vehicle_detector/           #   weights are auto-pulled from S3
│   ├── helmet_detector/            #   bucket: traffic-violation-project-data-models
│   ├── traffic_light_detector/
│   ├── lpr_detector/
│   └── lane_detector/
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
| `MODEL_BUCKET` | `traffic-violation-project-data-models` | Worker | S3 bucket with `models/` + `data/videos/` — auto-pulled on boot |
| `AWS_DEFAULT_REGION` | `us-east-1` | Worker | Region for the S3 bucket |

## Makefile Commands

| Command | What it does |
|---------|--------------|
| `make up` | Start services (`docker compose up -d`) — auto-pulls models from S3 |
| `make up-build` | Force-rebuild images then start |
| `make build` | Build the 3 images |
| `make clean` | **One-click wipe** — containers, volumes, images, build cache |
| `make reset` | `clean` + `up-build` — full wipe, rebuild, start |
| `make logs` / `make logs-worker` | Follow logs |
| `make ps` | Show container status |
| `make stop` / `make down` | Stop / stop + remove containers |
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
| Orchestration | Docker Compose |
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
