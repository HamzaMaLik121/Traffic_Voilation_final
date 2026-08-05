"""
Configuration settings for API Service
All paths are environment-variable-driven.
"""

import os
from pathlib import Path

DATABASE_DIR = Path(os.getenv("DATABASE_DIR", "/app/database"))
DATABASE_NAME = "violations.db"
DATABASE_PATH = DATABASE_DIR / DATABASE_NAME

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "5000"))
API_DEBUG = os.getenv("API_DEBUG", "0") == "1"
