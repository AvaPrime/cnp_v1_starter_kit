from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from conftest import auth_headers, make_hello_envelope
from conftest import _now_utc


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
    payload = response.json()
    assert "error" in payload
    assert payload["error"]["code"] == "invalid_node_id"
    assert payload["error"]["message"] == "node_id must match ^[a-z0-9-]{3,64}$"
    assert payload["error"]["details"]["node_id"] in (node_id, None)
    assert "timestamp" in payload["error"]
    assert "path" in payload["error"]


@pytest.mark.asyncio
async def test_node_hello_missing_node_id_shape(monkeypatch, app_client):
    import app.api.routes as routes

    from starlette.requests import Request

    async def _fake_json_missing():
        return {
            "protocol_version": "CNPv1",
            "message_type": "hello",
            "message_id": "abc",
            "ts_utc": _now_utc(),
            "qos": 1,
            "payload": {},
        }

    class _Req:
        async def json(self):
            return await _fake_json_missing()

    async def _fake_parse_envelope(request: Request):
        return await routes._parse_envelope(_Req())

    response = await app_client.post(
        "/api/node/hello",
        headers=auth_headers(),
        json=await _fake_json_missing(),
    )
    assert response.status_code == 400
    payload = response.json()
    assert "error" in payload
    assert payload["error"]["code"] == "missing_node_id"
    assert payload["error"]["message"] == "node_id is required"
    assert payload["error"]["details"]["node_id"] is None
    assert "timestamp" in payload["error"]
    assert "path" in payload["error"]


@pytest.mark.asyncio
async def test_get_node_not_found_shape(app_client):
    response = await app_client.get("/api/nodes/does-not-exist-123")
    assert response.status_code == 404
    payload = response.json()
    assert "error" in payload
    assert payload["error"]["code"] == "node_not_found"
    assert payload["error"]["message"] == "node_id not found"
    assert payload["error"]["details"]["node_id"] == "does-not-exist-123"
    assert "timestamp" in payload["error"]
    assert "path" in payload["error"]


@pytest.mark.asyncio
async def test_compat_hello_invalid_node_id_shape(app_client):
    bad_id = "Bad_ID"
    raw = make_hello_envelope(node_id=bad_id)
    raw["protocol"] = raw.pop("protocol_version")
    raw["timestamp"] = raw.pop("ts_utc")
    response = await app_client.post(
        "/v1/compat/node/hello",
        headers=auth_headers(),
        json=raw,
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "invalid_node_id"
    assert payload["error"]["message"] == "node_id must match ^[a-z0-9-]{3,64}$"
    assert payload["error"]["details"]["node_id"] == bad_id
    assert "timestamp" in payload["error"]
    assert "path" in payload["error"]


@pytest.mark.asyncio
async def test_commands_endpoint_node_not_found_shape(app_client):
    command = {
        "command_type": "reboot",
        "category": "maintenance",
        "timeout_ms": 2000,
        "arguments": {},
        "issued_by": "test",
        "dry_run": True,
    }
    response = await app_client.post(
        "/api/nodes/nonexistent-01/commands",
        json=command,
    )
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "node_not_found"
    assert payload["error"]["message"] == "node_id not found"
    assert payload["error"]["details"]["node_id"] == "nonexistent-01"
    assert "timestamp" in payload["error"]
    assert "path" in payload["error"]


@pytest.mark.asyncio
async def test_update_config_node_not_found_shape(app_client):
    response = await app_client.patch(
        "/api/nodes/missing-xyz/config",
        json={"heartbeat_interval_sec": 45, "report_interval_sec": 60},
    )
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "node_not_found"
    assert payload["error"]["message"] == "node_id not found"
    assert payload["error"]["details"]["node_id"] == "missing-xyz"
    assert "timestamp" in payload["error"]
    assert "path" in payload["error"]


@pytest.mark.asyncio
async def test_send_command_request_validation_shape(app_client):
    # Missing command_type should trigger RequestValidationError
    body = {
        # "command_type": "reboot",  # omitted
        "category": "maintenance",
        "timeout_ms": 2000,
        "arguments": {},
        "issued_by": "test",
        "dry_run": False,
    }
    response = await app_client.post("/api/nodes/cnp-test-01/commands", json=body)
    assert response.status_code == 400
    payload = response.json()
    assert "detail" not in payload
    assert payload["error"]["code"] == "request_validation_failed"
    assert payload["error"]["message"] == "The request is invalid"
    assert "fields" in payload["error"]["details"]
    assert "timestamp" in payload["error"]
    assert "path" in payload["error"]


@pytest.mark.asyncio
async def test_invalid_json_envelope_shape(app_client):
    # Force invalid JSON payload for /api/node/hello
    headers = auth_headers()
    headers["Content-Type"] = "application/json"
    response = await app_client.post("/api/node/hello", headers=headers, content="{ invalid-json")
    assert response.status_code == 400
    payload = response.json()
    assert "detail" not in payload
    assert payload["error"]["code"] == "invalid_json"
    assert payload["error"]["message"] == "Request body is not valid JSON"
    assert "timestamp" in payload["error"]
    assert "path" in payload["error"]


def test_openapi_has_no_legacy_validation(client: TestClient | None = None):
    from app.main import app
    client = client or TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    schemas = data.get("components", {}).get("schemas", {})
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas
    assert "ErrorResponse" in schemas
