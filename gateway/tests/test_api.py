from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from conftest import auth_headers, make_hello_envelope


def test_health():
    from app.main import app
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_node_hello_accepts_valid_node_id(monkeypatch, app_client, db_path: str):
    import app.api.routes as routes
    from dataclasses import replace

    monkeypatch.setattr(
        routes,
        "settings",
        replace(routes.settings, gateway_db_path=db_path),
    )
    response = await app_client.post(
        "/api/node/hello",
        headers=auth_headers(),
        json=make_hello_envelope(node_id="cnp-test-01"),
    )
    assert response.status_code == 200
    assert response.json()["registered"] is True


@dataclass
class _FakeEnvelope:
    node_id: str

    def model_dump(self):
        return {"node_id": self.node_id}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node_id",
    [
        "",
        "aa",
        "CNp-01",
        "cnp_test_01",
        "cnp test",
        "cnp/test",
        "cnp-01!",
    ],
)
async def test_node_hello_rejects_invalid_node_id_format(monkeypatch, app_client, node_id: str):
    import app.api.routes as routes

    async def _fake_parse_envelope(_request):
        return _FakeEnvelope(node_id=node_id), {"node_id": node_id}

    monkeypatch.setattr(routes, "_parse_envelope", _fake_parse_envelope)

    response = await app_client.post(
        "/api/node/hello",
        headers=auth_headers(),
        json=make_hello_envelope(node_id="cnp-test-01"),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "node_id must match ^[a-z0-9-]{3,64}$"
