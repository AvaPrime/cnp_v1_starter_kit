"""
================================================================
  Codessa Node Protocol v1 — Python Gateway
  File: gateway.py

  Run:
    pip install fastapi uvicorn aiosqlite python-dateutil
    python gateway.py

  Then test:
    curl http://localhost:5000/api/nodes

  The gateway:
    1. Receives hello / heartbeat / event / state / error
    2. Stores everything in SQLite via node_registry.sql schema
    3. Exposes REST endpoints for dashboard / Codessa Core
    4. Issues commands to nodes via /api/node/commands/{node_id}
    5. (Optional) bridges events to memory/external systems
================================================================
"""

import asyncio
import json
import logging
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ----------------------------------------------------------------
#  CONFIG
# ----------------------------------------------------------------
DB_PATH          = "codessa_registry.db"
SCHEMA_PATH      = "node_registry.sql"
GATEWAY_HOST     = "0.0.0.0"
GATEWAY_PORT     = 5000
LOG_LEVEL        = "INFO"
NODE_OFFLINE_SEC = 90   # Mark offline after this many seconds without heartbeat

# Simple token auth — replace with per-node tokens in production
VALID_TOKENS = {"YOUR_NODE_TOKEN"}

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("cnp-gateway")


# ----------------------------------------------------------------
#  DATABASE
# ----------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    schema = Path(SCHEMA_PATH)
    if not schema.exists():
        log.warning(f"Schema file not found: {SCHEMA_PATH}. Database may be incomplete.")
        return
    db = get_db()
    db.executescript(schema.read_text())
    db.commit()
    db.close()
    log.info(f"Database initialized: {DB_PATH}")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------
#  AUTH
# ----------------------------------------------------------------
def verify_token(token: Optional[str]):
    if not token or token not in VALID_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid or missing X-CNP-Token")


# ----------------------------------------------------------------
#  LIFESPAN
# ----------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info(f"CNP Gateway running on {GATEWAY_HOST}:{GATEWAY_PORT}")
    # Start background task to mark stale nodes offline
    task = asyncio.create_task(offline_watcher())
    yield
    task.cancel()


async def offline_watcher():
    """Periodically marks nodes as offline if they've missed heartbeats."""
    while True:
        await asyncio.sleep(30)
        try:
            db = get_db()
            db.execute("""
                UPDATE nodes
                SET status = 'offline'
                WHERE status = 'online'
                  AND last_seen IS NOT NULL
                  AND CAST((julianday('now') - julianday(last_seen)) * 86400 AS INTEGER) > ?
            """, (NODE_OFFLINE_SEC,))
            changed = db.execute("SELECT changes()").fetchone()[0]
            if changed:
                log.info(f"[WATCHER] Marked {changed} node(s) offline.")
            db.commit()
            db.close()
        except Exception as e:
            log.error(f"[WATCHER] Error: {e}")


# ----------------------------------------------------------------
#  APP
# ----------------------------------------------------------------
app = FastAPI(
    title="Codessa Node Protocol v1 Gateway",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------
#  HELLO — node registration
# ----------------------------------------------------------------
@app.post("/api/node/hello")
async def node_hello(
    request: Request,
    x_cnp_token: Optional[str] = Header(default=None)
):
    verify_token(x_cnp_token)
    body = await request.json()
    payload = body.get("payload", {})
    node_id = body.get("node_id")

    if not node_id:
        raise HTTPException(400, "Missing node_id")

    caps = payload.get("capabilities", {})
    db = get_db()
    try:
        db.execute("""
            INSERT INTO nodes (node_id, node_name, node_type, zone,
                               firmware_version, capabilities_json, status, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, 'online', ?)
            ON CONFLICT(node_id) DO UPDATE SET
                node_name        = excluded.node_name,
                node_type        = excluded.node_type,
                zone             = excluded.zone,
                firmware_version = excluded.firmware_version,
                capabilities_json= excluded.capabilities_json,
                status           = 'online',
                last_seen        = excluded.last_seen
        """, (
            node_id,
            payload.get("node_name", node_id),
            payload.get("node_type", "sensor"),
            payload.get("zone", "unassigned"),
            payload.get("firmware_version", "unknown"),
            json.dumps(caps),
            now_utc(),
        ))

        # Insert default config if not exists
        db.execute("""
            INSERT OR IGNORE INTO node_config (node_id) VALUES (?)
        """, (node_id,))

        db.commit()
        log.info(f"[HELLO] Registered: {node_id}  ({payload.get('node_name')})")

        # Return config to the node
        config = db.execute(
            "SELECT * FROM node_config WHERE node_id = ?", (node_id,)
        ).fetchone()

        return {
            "protocol": "CNPv1",
            "message_type": "register_ack",
            "registered": True,
            "config": {
                "heartbeat_interval_sec": config["heartbeat_interval_sec"] if config else 30,
                "report_interval_sec":    config["report_interval_sec"]    if config else 60,
                "zone":                   payload.get("zone", "unassigned"),
                "permissions":            ["control", "configuration", "maintenance"],
            }
        }
    finally:
        db.close()


# ----------------------------------------------------------------
#  HEARTBEAT
# ----------------------------------------------------------------
@app.post("/api/node/heartbeat")
async def node_heartbeat(
    request: Request,
    x_cnp_token: Optional[str] = Header(default=None)
):
    verify_token(x_cnp_token)
    body    = await request.json()
    node_id = body.get("node_id")
    payload = body.get("payload", {})

    if not node_id:
        raise HTTPException(400, "Missing node_id")

    db = get_db()
    try:
        db.execute("""
            UPDATE nodes
            SET status = ?, battery = ?, wifi_rssi = ?, uptime_sec = ?, last_seen = ?
            WHERE node_id = ?
        """, (
            payload.get("status", "online"),
            payload.get("battery"),
            payload.get("wifi_rssi"),
            payload.get("uptime_sec"),
            now_utc(),
            node_id,
        ))

        db.execute("""
            INSERT INTO heartbeats (node_id, status, uptime_sec, battery, wifi_rssi)
            VALUES (?, ?, ?, ?, ?)
        """, (
            node_id,
            payload.get("status", "online"),
            payload.get("uptime_sec"),
            payload.get("battery"),
            payload.get("wifi_rssi"),
        ))

        db.commit()
        log.debug(f"[HB] {node_id} — uptime={payload.get('uptime_sec')}s")
        return {"status": "ok"}
    finally:
        db.close()


# ----------------------------------------------------------------
#  EVENT
# ----------------------------------------------------------------
@app.post("/api/node/event")
async def node_event(
    request: Request,
    x_cnp_token: Optional[str] = Header(default=None)
):
    verify_token(x_cnp_token)
    body    = await request.json()
    node_id = body.get("node_id")
    payload = body.get("payload", {})

    if not node_id:
        raise HTTPException(400, "Missing node_id")

    db = get_db()
    try:
        db.execute("""
            INSERT OR IGNORE INTO events
                (event_id, node_id, event_type, category, priority, data_json, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.get("event_id", f"evt-{uuid.uuid4().hex[:8]}"),
            node_id,
            payload.get("event_type", "unknown"),
            payload.get("category", "telemetry"),
            payload.get("priority", "normal"),
            json.dumps(payload.get("data", {})),
            body.get("timestamp", now_utc()),
        ))

        # Update node last_seen
        db.execute("UPDATE nodes SET last_seen = ? WHERE node_id = ?", (now_utc(), node_id))
        db.commit()

        priority = payload.get("priority", "normal")
        log.info(f"[EVENT] {node_id} — {payload.get('event_type')} [{priority}]")

        # --------------------------------------------------------
        #  MEMORY BRIDGE HOOK — add your Codessa Core forwarding here
        #  Example: await forward_to_memory_cortex(node_id, payload)
        # --------------------------------------------------------
        if priority in ("high", "critical"):
            log.warning(f"[ALERT] {node_id}: {payload.get('event_type')} — {payload.get('data')}")

        return {"status": "ok", "event_id": payload.get("event_id")}
    finally:
        db.close()


# ----------------------------------------------------------------
#  STATE UPDATE
# ----------------------------------------------------------------
@app.post("/api/node/state")
async def node_state(
    request: Request,
    x_cnp_token: Optional[str] = Header(default=None)
):
    verify_token(x_cnp_token)
    body    = await request.json()
    node_id = body.get("node_id")
    payload = body.get("payload", {})

    db = get_db()
    try:
        db.execute("""
            UPDATE nodes
            SET status = ?, battery = ?, wifi_rssi = ?, uptime_sec = ?, last_seen = ?
            WHERE node_id = ?
        """, (
            payload.get("status", "online"),
            payload.get("battery"),
            payload.get("wifi_rssi"),
            payload.get("uptime_sec"),
            now_utc(),
            node_id,
        ))
        db.commit()
        return {"status": "ok"}
    finally:
        db.close()


# ----------------------------------------------------------------
#  ERROR REPORT
# ----------------------------------------------------------------
@app.post("/api/node/error")
async def node_error(
    request: Request,
    x_cnp_token: Optional[str] = Header(default=None)
):
    verify_token(x_cnp_token)
    body    = await request.json()
    node_id = body.get("node_id")
    payload = body.get("payload", {})

    db = get_db()
    try:
        db.execute("""
            INSERT INTO errors (node_id, error_code, error_msg, recoverable)
            VALUES (?, ?, ?, ?)
        """, (
            node_id,
            payload.get("error_code", "UNKNOWN"),
            payload.get("error_msg", ""),
            1 if payload.get("recoverable", True) else 0,
        ))
        db.commit()
        log.error(f"[ERROR] {node_id} — {payload.get('error_code')}: {payload.get('error_msg')}")
        return {"status": "ok"}
    finally:
        db.close()


# ----------------------------------------------------------------
#  COMMAND RESULT (acknowledgment from node)
# ----------------------------------------------------------------
@app.post("/api/node/command_result")
async def command_result(
    request: Request,
    x_cnp_token: Optional[str] = Header(default=None)
):
    verify_token(x_cnp_token)
    body    = await request.json()
    node_id = body.get("node_id")
    payload = body.get("payload", {})

    db = get_db()
    try:
        db.execute("""
            UPDATE commands
            SET status = ?, ack_at = ?, detail = ?
            WHERE command_id = ?
        """, (
            payload.get("status", "executed"),
            now_utc(),
            payload.get("detail"),
            payload.get("command_id"),
        ))
        db.commit()
        log.info(f"[ACK] {node_id} — cmd {payload.get('command_id')} → {payload.get('status')}")
        return {"status": "ok"}
    finally:
        db.close()


# ----------------------------------------------------------------
#  POLL COMMANDS (node asks "do you have anything for me?")
# ----------------------------------------------------------------
@app.get("/api/node/commands/{node_id}")
async def get_pending_command(
    node_id: str,
    x_cnp_token: Optional[str] = Header(default=None)
):
    verify_token(x_cnp_token)
    db = get_db()
    try:
        cmd = db.execute("""
            SELECT * FROM commands
            WHERE node_id = ? AND status = 'pending'
            ORDER BY issued_at ASC
            LIMIT 1
        """, (node_id,)).fetchone()

        if not cmd:
            return {"command": None}

        # Mark as queued (in-flight)
        db.execute("UPDATE commands SET status = 'queued' WHERE command_id = ?", (cmd["command_id"],))
        db.commit()

        return {
            "protocol":     "CNPv1",
            "message_type": "command",
            "node_id":      node_id,
            "timestamp":    now_utc(),
            "payload": {
                "command_id":   cmd["command_id"],
                "command_type": cmd["command_type"],
                "category":     cmd["category"],
                "params":       json.loads(cmd["params_json"] or "{}"),
            },
            "command": True,
        }
    finally:
        db.close()


# ----------------------------------------------------------------
#  DASHBOARD / MANAGEMENT ENDPOINTS
# ----------------------------------------------------------------

@app.get("/api/nodes")
async def list_nodes():
    """All registered nodes with current status."""
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM v_node_status ORDER BY zone, node_id").fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


@app.get("/api/nodes/{node_id}")
async def get_node(node_id: str):
    """Single node detail."""
    db = get_db()
    try:
        row = db.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Node not found")
        return dict(row)
    finally:
        db.close()


@app.get("/api/events")
async def list_events(limit: int = 50, priority: Optional[str] = None):
    """Recent events, optionally filtered by priority."""
    db = get_db()
    try:
        if priority:
            rows = db.execute(
                "SELECT * FROM events WHERE priority = ? ORDER BY received_at DESC LIMIT ?",
                (priority, limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM events ORDER BY received_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


@app.get("/api/alerts")
async def list_alerts():
    """Recent high/critical alerts (last 24h)."""
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM v_recent_alerts LIMIT 100").fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


@app.post("/api/commands")
async def issue_command(request: Request):
    """
    Issue a command to a node.
    Body: { "node_id": "...", "command_type": "...", "category": "...", "params": {} }
    """
    body        = await request.json()
    node_id     = body.get("node_id")
    command_type= body.get("command_type")
    category    = body.get("category", "control")
    params      = body.get("params", {})

    if not node_id or not command_type:
        raise HTTPException(400, "node_id and command_type required")

    command_id = f"cmd-{uuid.uuid4().hex[:8]}"
    db = get_db()
    try:
        db.execute("""
            INSERT INTO commands (command_id, node_id, command_type, category, params_json, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (command_id, node_id, command_type, category, json.dumps(params)))
        db.commit()
        log.info(f"[CMD] Issued: {command_id} → {node_id} ({command_type})")
        return {"command_id": command_id, "status": "pending"}
    finally:
        db.close()


@app.patch("/api/nodes/{node_id}/config")
async def update_node_config(node_id: str, request: Request):
    """Update per-node configuration (will be returned on next hello/heartbeat)."""
    body = await request.json()
    db = get_db()
    try:
        db.execute("""
            INSERT INTO node_config (node_id, heartbeat_interval_sec, report_interval_sec)
            VALUES (?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                heartbeat_interval_sec = excluded.heartbeat_interval_sec,
                report_interval_sec    = excluded.report_interval_sec,
                updated_at             = ?
        """, (
            node_id,
            body.get("heartbeat_interval_sec", 30),
            body.get("report_interval_sec", 60),
            now_utc(),
        ))
        db.commit()
        return {"status": "ok"}
    finally:
        db.close()


@app.get("/health")
async def health():
    return {"status": "ok", "gateway": "CNPv1", "time": now_utc()}


# ----------------------------------------------------------------
#  ENTRY POINT
# ----------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "gateway:app",
        host=GATEWAY_HOST,
        port=GATEWAY_PORT,
        reload=False,
        log_level=LOG_LEVEL.lower(),
    )
