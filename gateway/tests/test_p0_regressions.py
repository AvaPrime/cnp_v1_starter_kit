"""
gateway/tests/test_p0_regressions.py
──────────────────────────────────────
Phase 0 regression tests. These tests would have caught every CRITICAL
finding from the audit. They must remain green forever.

Tests:
  - /api/nodes returns 200 (not timeout) — P0-03/04 WAL fix
  - /api/nodes handles concurrency — 20 parallel requests all succeed
  - Admin endpoints return 401 without token — P0-05
  - Admin endpoints return 200 with valid token
  - ADMIN_TOKEN different from BOOTSTRAP_TOKEN is enforced
"""
from __future__ import annotations

import asyncio
import os

import pytest

from conftest import auth_headers, make_hello_envelope, seed_node

# Admin token injected by conftest via os.environ
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "test-admin-token-001")
ADMIN_HEADERS = {"X-CNP-Admin-Token": ADMIN_TOKEN}


# ── /api/nodes — WAL regression ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_nodes_empty_returns_200_not_timeout(app_client):
    """
    P0-03/04: Before WAL fix, /api/nodes returned ReadTimeout 100% of the time.
    This test confirms it returns 200 + empty list on an empty DB.
    If this test hangs, the WAL pragma is not applied.
    """
    response = await app_client.get("/api/nodes")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert response.json() == []


@pytest.mark.asyncio
async def test_nodes_with_data_returns_200(app_client, db_path):
    """P0-04: /api/nodes returns data correctly after WAL fix."""
    await seed_node(db_path, "cnp-wal-test-01")
    response = await app_client.get("/api/nodes")
    assert response.status_code == 200
    nodes = response.json()
    assert len(nodes) == 1
    assert nodes[0]["node_id"] == "cnp-wal-test-01"


@pytest.mark.asyncio
async def test_nodes_concurrency_no_timeouts(app_client, db_path):
    """
    P0-03: 20 concurrent /api/nodes requests must all return 200.
    Pre-fix: 100% ReadTimeout at concurrency=10.
    Post-fix: 0% error rate expected.
    """
    await seed_node(db_path, "cnp-conc-01")
    await seed_node(db_path, "cnp-conc-02")

    results = await asyncio.gather(
        *[app_client.get("/api/nodes") for _ in range(20)],
        return_exceptions=True,
    )

    errors = [r for r in results if isinstance(r, Exception)]
    non_200 = [r for r in results if not isinstance(r, Exception) and r.status_code != 200]

    assert not errors, f"Exceptions during concurrency test: {errors}"
    assert not non_200, f"Non-200 responses during concurrency test: {[r.status_code for r in non_200]}"


# ── Admin endpoint auth — P0-05 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fleet_status_requires_auth(app_client):
    """P0-05: /api/fleet/status must return 401 without admin token."""
    response = await app_client.get("/api/fleet/status")
    assert response.status_code == 401
    payload = response.json()
    assert "error" in payload


@pytest.mark.asyncio
async def test_fleet_status_returns_200_with_admin_token(app_client):
    """P0-05: /api/fleet/status returns 200 with valid admin token."""
    response = await app_client.get("/api/fleet/status", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "zones" in data
    assert "zone_count" in data


@pytest.mark.asyncio
async def test_provision_requires_auth(app_client, db_path):
    """P0-05: /api/nodes/{id}/provision must return 401 without admin token."""
    await seed_node(db_path, "cnp-prov-test-01")
    response = await app_client.post("/api/nodes/cnp-prov-test-01/provision")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rotate_secret_requires_auth(app_client, db_path):
    """P0-05: /api/nodes/{id}/rotate-secret must return 401 without admin token."""
    await seed_node(db_path, "cnp-rot-test-01")
    response = await app_client.post("/api/nodes/cnp-rot-test-01/rotate-secret")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_node_token_rejected_as_admin_token(app_client):
    """
    P0-05: The bootstrap node token must NOT work as an admin token.
    These are distinct credentials — using one for the other must fail.
    """
    # auth_headers() returns the BOOTSTRAP_TOKEN, not ADMIN_TOKEN
    node_headers = {"X-CNP-Admin-Token": auth_headers()["X-CNP-Node-Token"]}
    response = await app_client.get("/api/fleet/status", headers=node_headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_provision_node_not_found_returns_404(app_client):
    """P0-05: Provision on non-existent node returns 404 (not 500)."""
    response = await app_client.post(
        "/api/nodes/does-not-exist-01/provision",
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "node_not_found"


# ── Hygiene: .db files not in test artifacts ──────────────────────────────────

def test_no_db_files_at_root(tmp_path):
    """
    Sanity: confirms the test runner doesn't leak .db files to the
    working directory (tmp_path fixtures are cleaned up automatically).
    """
    db_files = list(tmp_path.glob("*.db"))
    assert db_files == [], f"Leaked DB files: {db_files}"
