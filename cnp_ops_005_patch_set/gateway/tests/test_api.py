from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_health():
    client = TestClient(create_app(enable_bridge=False))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
