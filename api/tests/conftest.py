"""
pytest conftest for API endpoint tests.

Creates a temporary SQLite database seeded with test data,
then builds the Flask app pointed at that database so all
routes can be exercised via the test client.
"""

import os
import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Ensure the api/ package is importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── helpers ─────────────────────────────────────────────────────────────

def _seed_database(db_path: str):
    """Create tables and insert sample data into *db_path*."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ── violations table ────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            violation_type TEXT NOT NULL,
            timestamp DATETIME NOT NULL,
            location TEXT,
            vehicle_type TEXT,
            license_plate TEXT,
            confidence REAL,
            speed REAL,
            speed_limit REAL,
            evidence_image_path TEXT,
            video_frame_number INTEGER,
            metadata TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    sample_violations = [
        {
            "violation_type": "NO_HELMET",
            "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(),
            "location": "Intersection A",
            "vehicle_type": "motorcycle",
            "license_plate": "ABC123",
            "confidence": 0.95,
            "speed": None,
            "speed_limit": None,
            "evidence_image_path": "/app/outputs/evidence/ev_001.jpg",
            "video_frame_number": 42,
            "metadata": '{"rider_count": 2}',
        },
        {
            "violation_type": "RED_LIGHT",
            "timestamp": (datetime.now() - timedelta(hours=5)).isoformat(),
            "location": "Intersection B",
            "vehicle_type": "car",
            "license_plate": "XYZ789",
            "confidence": 0.88,
            "speed": None,
            "speed_limit": None,
            "evidence_image_path": "/app/outputs/evidence/ev_002.jpg",
            "video_frame_number": 128,
            "metadata": "{}",
        },
        {
            "violation_type": "OVER_SPEED",
            "timestamp": (datetime.now() - timedelta(hours=1)).isoformat(),
            "location": "Highway 101",
            "vehicle_type": "truck",
            "license_plate": "SPD001",
            "confidence": 0.92,
            "speed": 95.0,
            "speed_limit": 80.0,
            "evidence_image_path": "/app/outputs/evidence/ev_003.jpg",
            "video_frame_number": 203,
            "metadata": "{}",
        },
        {
            "violation_type": "LANE_VIOLATION",
            "timestamp": (datetime.now() - timedelta(days=1)).isoformat(),
            "location": "Main St",
            "vehicle_type": "sedan",
            "license_plate": "LANE99",
            "confidence": 0.76,
            "speed": None,
            "speed_limit": None,
            "evidence_image_path": "/app/outputs/evidence/ev_004.jpg",
            "video_frame_number": 87,
            "metadata": "{}",
        },
        {
            "violation_type": "ILLEGAL_UTURN",
            "timestamp": (datetime.now() - timedelta(days=3)).isoformat(),
            "location": "Oak Ave & 5th",
            "vehicle_type": "suv",
            "license_plate": "UTRN77",
            "confidence": 0.81,
            "speed": 35.0,
            "speed_limit": None,
            "evidence_image_path": None,
            "video_frame_number": 310,
            "metadata": "{}",
        },
        {
            "violation_type": "NO_HELMET",
            "timestamp": (datetime.now() - timedelta(days=7)).isoformat(),
            "location": "Broadway",
            "vehicle_type": "scooter",
            "license_plate": "ABC123",
            "confidence": 0.93,
            "speed": None,
            "speed_limit": None,
            "evidence_image_path": "/app/outputs/evidence/ev_006.jpg",
            "video_frame_number": 55,
            "metadata": '{"rider_count": 1}',
        },
    ]

    for v in sample_violations:
        cur.execute("""
            INSERT INTO violations (
                violation_type, timestamp, location, vehicle_type,
                license_plate, confidence, speed, speed_limit,
                evidence_image_path, video_frame_number, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            v["violation_type"], v["timestamp"], v["location"],
            v["vehicle_type"], v["license_plate"], v["confidence"],
            v["speed"], v["speed_limit"], v["evidence_image_path"],
            v["video_frame_number"], v["metadata"],
        ))

    # ── statistics table ───────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            violation_type TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            UNIQUE(date, violation_type)
        )
    """)

    stats_data = [
        ("2026-07-05", "NO_HELMET", 12),
        ("2026-07-05", "RED_LIGHT", 5),
        ("2026-07-05", "OVER_SPEED", 8),
        ("2026-07-06", "NO_HELMET", 10),
        ("2026-07-06", "LANE_VIOLATION", 3),
        ("2026-07-07", "ILLEGAL_UTURN", 2),
        ("2026-07-07", "OVER_SPEED", 6),
        ("2026-07-08", "NO_HELMET", 15),
        ("2026-07-08", "RED_LIGHT", 7),
        ("2026-07-08", "LANE_VIOLATION", 4),
        (datetime.now().strftime("%Y-%m-%d"), "NO_HELMET", 3),
        (datetime.now().strftime("%Y-%m-%d"), "OVER_SPEED", 2),
    ]

    for date, vtype, count in stats_data:
        cur.execute("""
            INSERT OR IGNORE INTO statistics (date, violation_type, count)
            VALUES (?, ?, ?)
        """, (date, vtype, count))

    conn.commit()
    conn.close()


# ── fixtures ───────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """Create a temporary SQLite database seeded with test data."""
    tmp = tmp_path_factory.mktemp("data")
    path = str(tmp / "test_violations.db")
    _seed_database(path)
    return path


@pytest.fixture(scope="session")
def app(db_path, tmp_path_factory):
    """Build the Flask application pointed at the test database."""
    # Point DATABASE_DIR at the temp dir so the db module doesn't
    # try to create /app/database/ on the local dev machine.
    tmp = tmp_path_factory.mktemp("app-db-dir")
    os.environ["DATABASE_DIR"] = str(tmp)

    from api.main import create_app
    application = create_app(db_path=db_path)
    application.config["TESTING"] = True
    return application


@pytest.fixture(scope="session")
def client(app):
    """Flask test client."""
    return app.test_client()



