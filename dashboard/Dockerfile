# ═════════════════════════════════════════════════════════════════════
#  Dockerfile — Dashboard Service
#  What it does: Runs the Streamlit web UI for live monitoring
#  Start command: streamlit run app/dashboard.py → serves on port 8501
# ═════════════════════════════════════════════════════════════════════
#  Key design decisions:
#    • NO torch / opencv / easyocr / ultralytics — only streamlit + pandas + plotly
#      This keeps the image very lightweight (~200 MB)
#    • Calls the API service via HTTP (API_URL env var) instead of
#      reading the database directly — this decouples the services
#    • Connects to API service over Docker internal network, not host
#    • Evidence images served via shared Docker volume, not HTTP
# ═════════════════════════════════════════════════════════════════════

FROM python:3.12-slim

LABEL maintainer="Hamza"
LABEL project="traffic-violation-detection"
LABEL service="dashboard"

# System dependencies: only curl for Streamlit health check probing
# No OpenCV/PyTorch libraries needed — Streamlit + Pandas + Plotly are pure Python
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python packages: lightweight data stack (Streamlit + Pandas + Plotly + Requests)
# NO torch / opencv / easyocr / ultralytics — saves ~3 GB vs worker image
COPY requirements-dashboard.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-dashboard.txt

# Application source code
COPY app/         ./app/
COPY .streamlit/  ./.streamlit/

# Pre-create runtime directories for Docker volume mounts
RUN mkdir -p database outputs/evidence

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Streamlit server configuration (overrides default config.toml)
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8501

# Streamlit health check — curl with -f fails on non-2xx responses
# start-period=15s gives Streamlit time to compile and start serving
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Note: API_URL env var must be set at runtime (e.g., in docker-compose.yml)
# to tell the dashboard where to find the API service.
CMD ["streamlit", "run", "app/dashboard.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
