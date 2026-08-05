# ═════════════════════════════════════════════════════════════════════
#  Dockerfile — API Service
#  What it does: Runs the Flask REST API (lightweight, no ML)
#  Start command: python main.py  → serves on port 5000
# ═════════════════════════════════════════════════════════════════════
#  Key design decisions:
#    • NO torch / opencv / easyocr / ultralytics — only Flask + SQLite
#      This keeps the image tiny (~130 MB vs ~2 GB for the worker)
#    • Shares the SQLite database file with the worker via Docker volume
#    • Shares the evidence / latest_frame.jpg output via another volume
#    • Can start independently of the worker (database may be empty)
# ═════════════════════════════════════════════════════════════════════

FROM python:3.12-slim

LABEL maintainer="Hamza"
LABEL project="traffic-violation-detection"
LABEL service="api"

# No system dependencies needed — pure Python (Flask + SQLite)
# Skipping apt-get saves ~30 MB in image size vs the worker image.

WORKDIR /app

# Python packages: only Flask + SQLite, no ML libraries
COPY requirements-api.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-api.txt

# Application source code
COPY config/ ./config/
COPY app/    ./app/
COPY main.py .

# Pre-create runtime directory for the shared database volume mount
RUN mkdir -p /app/database

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 5000

# Health check — calls /health endpoint every 30s
# start-period=5s gives Flask time to load before first check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

CMD ["python", "main.py"]
