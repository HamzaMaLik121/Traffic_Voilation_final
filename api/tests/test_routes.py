"""
Tests for the Traffic Violation Detection API (Flask routes).

Covers all four endpoints:
    GET /health
    GET /violations        (with filters)
    GET /violations/<id>
    GET /statistics        (with date filters)
"""

import json
from datetime import datetime, timedelta

import pytest


# ══════════════════════════════════════════════════════════════════════
#  /health
# ══════════════════════════════════════════════════════════════════════

class TestHealth:
    def test_health_returns_healthy(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        assert isinstance(data["violations_count"], int)

    def test_health_includes_violation_count(self, client):
        resp = client.get("/health")
        data = resp.get_json()
        assert data["violations_count"] > 0  # we seeded 6 violations


# ══════════════════════════════════════════════════════════════════════
#  GET /violations
# ══════════════════════════════════════════════════════════════════════

class TestGetViolations:
    URL = "/violations"

    def test_list_all_violations(self, client):
        resp = client.get(self.URL)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 6  # all seeded records
        assert len(data["violations"]) == 6

    def test_list_violations_returns_json_structure(self, client):
        resp = client.get(self.URL)
        data = resp.get_json()
        for v in data["violations"]:
            assert "id" in v
            assert "violation_type" in v
            assert "timestamp" in v
            assert "license_plate" in v

    def test_filter_by_violation_type(self, client):
        resp = client.get(self.URL, query_string={"violation_type": "NO_HELMET"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(v["violation_type"] == "NO_HELMET" for v in data["violations"])
        assert data["count"] == 2  # two NO_HELMET records seeded

    def test_filter_by_license_plate(self, client):
        resp = client.get(self.URL, query_string={"license_plate": "ABC123"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(v["license_plate"] == "ABC123" for v in data["violations"])
        assert data["count"] == 2  # two ABC123 records seeded

    def test_filter_by_type_and_plate(self, client):
        resp = client.get(self.URL, query_string={
            "violation_type": "NO_HELMET",
            "license_plate": "ABC123",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 2

    def test_filter_by_date_range(self, client):
        """Only violations from the last 24 hours."""
        start = (datetime.now() - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S")
        end = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        resp = client.get(self.URL, query_string={
            "start_date": start,
            "end_date": end,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        # Expecting the 3 most recent violations (NO_HELMET, OVER_SPEED, RED_LIGHT)
        assert data["count"] >= 2

    def test_limit_param(self, client):
        resp = client.get(self.URL, query_string={"limit": 2})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 2
        assert len(data["violations"]) == 2

    def test_filter_no_matches(self, client):
        resp = client.get(self.URL, query_string={"license_plate": "NONEXISTENT"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0
        assert data["violations"] == []

    def test_invalid_type_still_returns_200(self, client):
        """An unknown violation_type should return 200 with empty results."""
        resp = client.get(self.URL, query_string={"violation_type": "ALIEN_INVASION"})
        assert resp.status_code == 200
        assert resp.get_json()["count"] == 0

    def test_default_limit_is_100(self, client):
        resp = client.get(self.URL)
        data = resp.get_json()
        assert data["count"] <= 100  # default limit


# ══════════════════════════════════════════════════════════════════════
#  GET /violations/<id>
# ══════════════════════════════════════════════════════════════════════

class TestGetViolationById:
    URL = "/violations"

    def test_get_existing_violation(self, client):
        resp = client.get(f"{self.URL}/1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == 1
        assert data["violation_type"] == "NO_HELMET"
        assert data["license_plate"] == "ABC123"

    def test_get_violation_contains_all_fields(self, client):
        resp = client.get(f"{self.URL}/1")
        data = resp.get_json()
        expected_keys = {
            "id", "violation_type", "timestamp", "location",
            "vehicle_type", "license_plate", "confidence",
            "evidence_image_path", "video_frame_number", "metadata",
        }
        assert expected_keys.issubset(data.keys())

    def test_get_nonexistent_violation(self, client):
        resp = client.get(f"{self.URL}/9999")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_get_violation_with_evidence_path_null(self, client):
        """Violation #5 has evidence_image_path = None."""
        resp = client.get(f"{self.URL}/5")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["violation_type"] == "ILLEGAL_UTURN"
        assert data.get("evidence_image_path") is None

    def test_get_violation_metadata_parsed(self, client):
        """Violation #1 has metadata '{\"rider_count\": 2}' parsed to dict."""
        resp = client.get(f"{self.URL}/1")
        data = resp.get_json()
        meta = data.get("metadata", {})
        assert isinstance(meta, dict)
        assert meta.get("rider_count") == 2


# ══════════════════════════════════════════════════════════════════════
#  GET /statistics
# ══════════════════════════════════════════════════════════════════════

class TestGetStatistics:
    URL = "/statistics"

    def test_statistics_returns_all_types(self, client):
        resp = client.get(self.URL)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "statistics" in data
        assert "total" in data
        assert data["total"] > 0

    def test_statistics_structure(self, client):
        resp = client.get(self.URL)
        data = resp.get_json()
        stats = data["statistics"]
        # We seeded NO_HELMET, RED_LIGHT, OVER_SPEED, LANE_VIOLATION, ILLEGAL_UTURN
        assert "NO_HELMET" in stats
        assert "RED_LIGHT" in stats
        assert "OVER_SPEED" in stats
        assert "LANE_VIOLATION" in stats
        assert "ILLEGAL_UTURN" in stats

    def test_statistics_counts(self, client):
        resp = client.get(self.URL)
        data = resp.get_json()
        stats = data["statistics"]
        # NO_HELMET: 12 + 10 + 15 + 3 = 40 (plus 2 today)
        assert stats["NO_HELMET"] >= 40
        # RED_LIGHT: 5 + 7 = 12
        assert stats["RED_LIGHT"] >= 12
        # OVER_SPEED: 8 + 6 + 2 = 16
        assert stats["OVER_SPEED"] >= 16

    def test_statistics_with_date_range(self, client):
        """Filter to a specific date range."""
        resp = client.get(self.URL, query_string={
            "start_date": "2026-07-05",
            "end_date": "2026-07-06",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        stats = data["statistics"]
        # Only July 5-6 data
        assert stats.get("NO_HELMET") == 22   # 12 + 10
        assert stats.get("RED_LIGHT") == 5    # only July 5
        assert stats.get("OVER_SPEED") == 8   # only July 5

    def test_statistics_date_range_no_matches(self, client):
        resp = client.get(self.URL, query_string={
            "start_date": "2020-01-01",
            "end_date": "2020-01-02",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["statistics"] == {}
        assert data["total"] == 0

    def test_statistics_total_matches_sum(self, client):
        resp = client.get(self.URL)
        data = resp.get_json()
        assert sum(data["statistics"].values()) == data["total"]


# ══════════════════════════════════════════════════════════════════════
#  Edge cases
# ══════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_invalid_route_returns_404(self, client):
        resp = client.get("/nonexistent")
        assert resp.status_code == 404

    def test_method_not_allowed(self, client):
        """Our routes only accept GET."""
        resp = client.post("/violations", data={})
        assert resp.status_code in (405,)  # Flask returns 405

    def test_negative_id_returns_404(self, client):
        """Negative IDs return 404 because no record has that id."""
        resp = client.get("/violations/-1")
        # Flask's int converter matches -1, but get_violation_by_id(-1)
        # returns None -> 404.
        assert resp.status_code == 404

    def test_string_id_returns_404(self, client):
        resp = client.get("/violations/abc")
        assert resp.status_code == 404

    def test_large_limit_is_accepted(self, client):
        resp = client.get("/violations", query_string={"limit": 9999})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] <= 6  # only 6 records exist

    def test_empty_query_string_is_handled(self, client):
        resp = client.get("/violations?")
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════
#  Swagger / OpenAPI docs (Flasgger)
# ══════════════════════════════════════════════════════════════════════

class TestDocs:
    """Smoke tests protecting the Flasgger Swagger wiring (/docs/)."""

    def test_docs_ui_returns_200(self, client):
        """The Swagger UI page must be served and reference the spec."""
        resp = client.get("/docs/")
        assert resp.status_code == 200
        # The UI page must load the generated OpenAPI spec.
        assert b"apispec_1.json" in resp.data

    def test_openapi_spec_documents_all_routes(self, client):
        """
        The generated OpenAPI spec must be valid JSON and cover every
        documented route. Guards against broken YAML docstrings or
        misconfigured SWAGGER settings silently dropping endpoints.
        """
        resp = client.get("/apispec_1.json")
        assert resp.status_code == 200
        spec = resp.get_json()
        assert spec["info"]["title"] == "Traffic Violation Detection API"

        paths = spec.get("paths", {})
        expected = (
            "/violations",
            "/violations/{violation_id}",
            "/statistics",
            "/health",
            "/worker-status",
            "/live-feed",
            "/mjpeg",
            "/live",
        )
        for route in expected:
            assert route in paths, f"Route {route} missing from OpenAPI spec"
            assert "get" in paths[route], f"Route {route} has no GET operation"
