"""Smoke tests for the health / readiness endpoints.

Importing `main` builds the app against the temp RAG_DATA_DIR set in conftest,
so these never touch real data. They hit only the cheap, no-LLM routes.
"""

from fastapi.testclient import TestClient

import config
from main import app

client = TestClient(app)


def test_root_reports_name_and_version():
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Enterprise RAG API"
    assert body["version"] == config.APP_VERSION


def test_health_shape_and_values():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == config.APP_VERSION
    assert body["mode"] in ("lite", "balanced", "power")
    assert isinstance(body["index_loaded"], bool)
    assert isinstance(body["document_count"], int)
    assert isinstance(body["providers_configured"], int)
