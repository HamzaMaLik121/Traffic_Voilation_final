# PROMPT — Paste this whole thing into DeepSeek

You are restructuring an existing production ML project called **Traffic Violation Detection System** from a monolithic layout into a proper 3-service production architecture (worker / api / dashboard). This is a real project with real working code — do not invent, simplify, or drop any functionality. Every file that exists in the CURRENT STRUCTURE must end up somewhere in the TARGET STRUCTURE, fully working.

## Step 1 — Read everything first

Before writing anything, read every file in the current project (I will provide them, or you should ask me to paste any file you need before proceeding). Do not guess the contents of a file you haven't seen. If a file is referenced (imported, in a Dockerfile COPY, in docker-compose volumes, in a K8s manifest) but you don't have its content, STOP and ask me to paste it.

## Step 2 — Understand the current architecture

Current setup: two Docker services sharing a SQLite database file via a Docker volume.
- `backend` container runs `live_test.py` in an infinite loop — reads video, runs YOLOv8 + EasyOCR + custom detectors, writes violations directly to SQLite via a `ViolationDatabase` class.
- `dashboard` container runs Streamlit, and currently **imports `ViolationDatabase` directly** (`from src.backend.database import ViolationDatabase`) to read the same SQLite file from a shared volume. This is NOT a real API — it's a direct Python import across what should be a service boundary.
- `config.py` uses `BASE_DIR = Path(__file__).parent.parent` — a hardcoded relative path assumption that breaks once files move to separate folders/containers.

## Step 3 — Target architecture (what you're converting TO)

Split into **three independently deployable services**:

1. **`worker/`** — same detection loop as today (`live_test.py`), still writes to SQLite. No HTTP server. No changes to detection logic itself — only import paths change.
2. **`api/`** — NEW Flask REST API. Wraps the existing `ViolationDatabase` read methods (`get_violations`, `get_violation_by_id`, `get_statistics`) as HTTP endpoints:
   - `GET /violations` (supports the same filters the method already supports: violation_type, license_plate, start_date, end_date, limit)
   - `GET /violations/<id>`
   - `GET /statistics` (supports start_date, end_date)
   - Lightweight — only `flask`, `sqlalchemy` (or raw `sqlite3`) — NOT torch/opencv/ultralytics/easyocr.
3. **`dashboard/`** — Streamlit UI, rewritten to call the API over HTTP (`requests.get(f"{API_URL}/violations", params=...)`) instead of importing `ViolationDatabase` directly. Every one of the ~6 call sites in `dashboard.py` that currently calls `db.get_violations(...)`, `db.get_statistics(...)`, `db.get_violation_by_id(...)` must be converted to an HTTP call to the new API. Add `API_URL` as an environment variable, default `http://api:5000` for docker-compose and `http://tvs-api-svc:80` for Kubernetes.

Models (`ml/`) and training/dataset code (`src/training/`, `src/data_preparation/`, `data/`) are **not needed by any of the three runtime services** — the models are already trained. `data/` should not be copied into any Docker build context and should not be mounted as a volume in docker-compose or Kubernetes. Only `ml/` (trained weights), the database, and `outputs/` (evidence images) need volumes/PVCs.

## Step 4 — Critical: fix every path reference

Because files are moving directories, you must trace and fix **every place a path is hardcoded or assumed**, including but not limited to:
- `config.py` in both `worker/` and `api/` — `BASE_DIR` must become environment-variable-driven (e.g. `DATABASE_PATH = os.getenv("DATABASE_PATH", "/app/database/violations.db")`), not computed via `Path(__file__).parent.parent`, since that assumes a specific folder depth that will now differ between services.
- Every `sys.path.append(...)` / `sys.path.insert(...)` call in `live_test.py`, `violation_processor.py`, `database.py`, `dashboard.py` — these currently walk up parent directories assuming the OLD folder depth. Recalculate for the NEW folder depth in each service.
- All three Dockerfiles (`worker/Dockerfile`, `api/Dockerfile`, `dashboard/Dockerfile`) — `COPY` paths, `WORKDIR`, `CMD`/`ENTRYPOINT` paths must match the new folder layout exactly.
- `docker-compose.yml` — each service's `build.context` must point at its own subfolder (e.g. `context: ./worker`, `context: ./api`, `context: ./dashboard`), NOT the repo root, since each Dockerfile's `COPY` paths are now relative to its own service folder. Add the new `api` service (with `depends_on` ordering: dashboard depends on api being healthy, api depends on nothing since it just reads whatever DB exists).
- Kubernetes manifests — `kubernetes/worker/deployment.yml`, `kubernetes/api/deployment.yml` + `service.yml` (ClusterIP), `kubernetes/dashboard/deployment.yml` + `service.yml` (LoadBalancer). Remove the `models`/`data` hostPath volumes from any service that doesn't need them per Step 3. Add `API_URL` env var to the dashboard deployment pointing at the new `tvs-api-svc`.
- `entrypoint.sh` — still lives in `worker/`, still handles the local-volume-vs-S3-pull logic for models, but check every path it references against the new `worker/` folder layout.
- Any `import` statement anywhere that references the old `src.backend.*`, `src.detection.*`, `src.gui.*`, `src.lpr.*` module paths needs updating to the new `app.*` module paths inside whichever service it now lives in.

## Step 4b — `data/` folder: NEVER copied into any image, ever

This is a hard rule, not a suggestion — `data/` is training-dataset content and the models are already trained. None of the three services (`worker`, `api`, `dashboard`) read from `data/` for anything except one optional fallback in `live_test.py` that looks for a local `test_video.mp4` if no other video source is given.

- **No Dockerfile** (`worker/Dockerfile`, `api/Dockerfile`, `dashboard/Dockerfile`) may contain `COPY data/` or `COPY . .` without an accompanying `.dockerignore` that excludes `data/`.
- Each service folder (`worker/`, `api/`, `dashboard/`) must have its own `.dockerignore` including at minimum: `data/`, `venv/`, `__pycache__/`, `*.pyc`, `.git/`.
- `docker-compose.yml` MAY optionally mount `./data:/app/data:ro` under the `worker` service ONLY, purely as a local-dev convenience for the test-video fallback — never under `api` or `dashboard`, and never as a build-time `COPY`.
- Kubernetes manifests must NOT include a `data` PVC or hostPath volume for `worker`, `api`, or `dashboard` — production video input is a live camera/RTSP stream, not a mounted dataset folder. If you add one out of habit, remove it and flag that you did so.
- Also drop `COPY main.py .` from the new `worker/Dockerfile` — `main.py` is legacy/dead code with a `ViolationProcessor` call signature that no longer matches what `live_test.py` actually uses. Don't ship it in the image. Flag this removal explicitly in your output.

## Step 5 — Output format

For each file you produce, output the full file content, not a diff, with the file's NEW path as a header. Do not skip files because they "didn't change much" — I need the complete, final version of every file so I can copy-paste it directly. Flag clearly (in bold, at the top of your response) any file where you had to guess at content you weren't given, so I can double check it.

---

## CURRENT STRUCTURE

```
traffic_Devops/
├── config/
│   ├── config.py
│   └── lane_config.json
├── data/                          # NOT needed at runtime — training data only, models already trained
│   ├── processed/
│   └── raw/
├── database/
│   └── violations.db
├── kubernetes/
│   ├── backend-deployment.yml
│   ├── backend-service.yml
│   ├── dashboard-deployment.yml
│   ├── dashboard-service.yml
│   ├── namespace.yml
│   └── pv-pvc.yml
├── models/
│   ├── helmet_detector/  (args.yaml, results.csv, weights/{best.onnx,best.pt,last.pt})
│   ├── lane_detector/    (weights/yolop-640-640.onnx)
│   ├── lpr_detector/     (args.yaml, results.csv, weights/{best.onnx,best.pt,last.pt})
│   ├── traffic_light_detector/ (args.yaml, results.csv, weights/{best.onnx,best.pt,last.pt})
│   └── vehicle_detector/ (args.yaml, results.csv, weights/{best.onnx,best.pt,last.pt})
├── outputs/
│   ├── evidence/
│   └── violations/
├── owasp-reports/
├── src/
│   ├── __init__.py
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── database.py
│   │   └── violation_processor.py
│   ├── data_preparation/
│   │   ├── __init__.py
│   │   └── preprocess_data.py
│   ├── detection/
│   │   ├── __init__.py
│   │   ├── helmet_detector.py
│   │   ├── lane_detector.py
│   │   ├── lpr_detector.py
│   │   ├── manual_lane_detector.py
│   │   ├── poly_lane_detector.py
│   │   ├── speed_estimator.py
│   │   ├── traffic_light_detector.py
│   │   ├── uturn_detector.py
│   │   ├── vehicle_detector.py
│   │   └── yolop_lane_detector.py
│   ├── gui/
│   │   ├── __init__.py
│   │   └── dashboard.py
│   ├── lpr/
│   │   ├── __init__.py
│   │   └── plate_recognizer.py
│   └── training/
│       ├── __init__.py
│       ├── train_models.py
│       └── verify_performance.py
├── tests/
│   ├── generate_test_report.py
│   ├── run_system_tests.py
│   ├── TEST_REPORT.csv
│   └── test_results.json
├── tools/
│   └── calibrate_speed.py
├── debug_lanes.py
├── diagnostic.py
├── docker-compose.yml
├── Dockerfile.backend
├── Dockerfile.dashboard
├── entrypoint.sh
├── live_test.py
├── main.py
├── README.md
├── requirements.txt
├── setup_lanes.py
├── test_lanes.py
├── trivy-backend.txt
├── trivy-dashboard.txt
└── yolov8n.pt
```

## TARGET STRUCTURE

```
traffic_Devops/
├── worker/
│   ├── app/
│   │   ├── detection/
│   │   │   ├── __init__.py
│   │   │   ├── helmet_detector.py
│   │   │   ├── lane_detector.py
│   │   │   ├── lpr_detector.py
│   │   │   ├── manual_lane_detector.py
│   │   │   ├── poly_lane_detector.py
│   │   │   ├── speed_estimator.py
│   │   │   ├── traffic_light_detector.py
│   │   │   ├── uturn_detector.py
│   │   │   ├── vehicle_detector.py
│   │   │   └── yolop_lane_detector.py
│   │   ├── lpr/
│   │   │   ├── __init__.py
│   │   │   └── plate_recognizer.py
│   │   ├── db/
│   │   │   └── database.py
│   │   └── violation_processor.py
│   ├── config/
│   │   ├── config.py
│   │   └── lane_config.json
│   ├── tools/
│   │   └── calibrate_speed.py
│   ├── live_test.py
│   ├── setup_lanes.py
│   ├── test_lanes.py
│   ├── debug_lanes.py
│   ├── diagnostic.py
│   ├── entrypoint.sh
│   ├── Dockerfile
│   ├── requirements-worker.txt
│   └── yolov8n.pt
├── api/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── db/
│   │       └── database.py
│   ├── config/
│   │   └── config.py
│   ├── Dockerfile
│   ├── requirements-api.txt
│   └── main.py
├── dashboard/
│   ├── app/
│   │   └── dashboard.py
│   ├── Dockerfile
│   ├── requirements-dashboard.txt
│   └── .streamlit/
│       └── config.toml
├── ml/
│   ├── helmet_detector/  (args.yaml, results.csv, weights/{best.onnx,best.pt,last.pt})
│   ├── lane_detector/    (weights/yolop-640-640.onnx)
│   ├── lpr_detector/     (args.yaml, results.csv, weights/{best.onnx,best.pt,last.pt})
│   ├── traffic_light_detector/ (args.yaml, results.csv, weights/{best.onnx,best.pt,last.pt})
│   └── vehicle_detector/ (args.yaml, results.csv, weights/{best.onnx,best.pt,last.pt})
├── data/                          # untouched, not used by any container
│   ├── raw/
│   └── processed/
├── outputs/
│   ├── evidence/
│   └── violations/
├── src/                           # dev-only, not shipped in any container
│   ├── data_preparation/
│   │   ├── __init__.py
│   │   └── preprocess_data.py
│   └── training/
│       ├── __init__.py
│       ├── train_models.py
│       └── verify_performance.py
├── kubernetes/
│   ├── worker/
│   │   └── deployment.yml
│   ├── api/
│   │   ├── deployment.yml
│   │   └── service.yml
│   ├── dashboard/
│   │   ├── deployment.yml
│   │   └── service.yml
│   ├── namespace.yml
│   └── pv-pvc.yml
├── tests/
│   ├── generate_test_report.py
│   ├── run_system_tests.py
│   ├── TEST_REPORT.csv
│   └── test_results.json
├── security/
│   ├── owasp-reports/
│   ├── trivy-backend.txt
│   └── trivy-dashboard.txt
├── docker-compose.yml
└── README.md
```

---

## Files I will paste for you to work from (ask me for any you still need):

- src/backend/violation_processor.py
- src/backend/database.py
- config/config.py
- live_test.py
- src/gui/dashboard.py
- Dockerfile.backend
- Dockerfile.dashboard
- docker-compose.yml
- requirements.txt
- kubernetes/*.yml (all 4 files)
- entrypoint.sh
- src/detection/*.py (all 10 files)
- src/lpr/plate_recognizer.py

Ask me for any of these you don't yet have before producing output. Do not fabricate content for a file you haven't seen.
