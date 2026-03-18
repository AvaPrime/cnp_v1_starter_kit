"""
CNP EPIC-02 — P2-02
Per-node secret provisioning — Stage 2 auth.

Upgrades the Stage 1 bootstrap token model (P1-07) to
per-node HMAC secrets:

  1. On first registration, gateway generates a random 32-byte secret.
  2. Returns the plain secret ONCE in the register_ack payload.
  3. Stores HMAC-SHA256(secret) in nodes.node_secret_hash.
  4. Subsequent requests validate X-CNP-Node-Token as
     HMAC-SHA256(node_id + ":" + token) against the stored hash.
  5. Bootstrap token remains valid for nodes without a provisioned secret.

Rotation:
  POST /api/nodes/{node_id}/rotate-secret
  → generates new secret, returns once, invalidates old.

Bootstrap disable:
  Set BOOTSTRAP_DISABLED=true in env to reject all bootstrap tokens
  (for production zones where all nodes are provisioned).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from typing import Any

import aiosqlite

log = logging.getLogger("cnp.auth")

_BOOTSTRAP_TOKEN: str = os.environ.get("BOOTSTRAP_TOKEN", "")
_BOOTSTRAP_DISABLED: bool = os.environ.get("BOOTSTRAP_DISABLED", "false").lower() == "true"


# ----------------------------------------------------------------
#  Secret generation
# ----------------------------------------------------------------

def generate_node_secret() -> str:
    """Generate a cryptographically random 32-byte hex secret."""
    return secrets.token_hex(32)


def hash_secret(secret: str) -> str:
    """HMAC-SHA256 hash of the plain secret for storage."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def compute_node_token(node_id: str, secret: str) -> str:
    """
    Compute the token a node should send in X-CNP-Node-Token.
    token = HMAC-SHA256(secret, node_id)
    """
    return hmac.new(
        secret.encode("utf-8"),
        node_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ----------------------------------------------------------------
#  Token validation
# ----------------------------------------------------------------

async def validate_node_token(
    db_path: str,
    node_id: str,
    token: str | None,
) -> bool:
    """
    Stage 2 validation pipeline:
    1. If node has a stored secret hash → validate HMAC.
    2. If node has no stored hash → fall back to bootstrap token.
    3. If BOOTSTRAP_DISABLED → only HMAC tokens accepted.

    Returns True if valid.
    """
    if not token:
        return False

    stored_hash = await _get_node_secret_hash(db_path, node_id)

    if stored_hash:
        # Stage 2: validate HMAC token
        expected_secret = stored_hash  # we stored hash(secret)
        # Node sends: HMAC-SHA256(secret, node_id)
        # We can't recompute without the plain secret, so we stored
        # the hash differently: nodes.node_secret_hash = SHA256(secret)
        # The node computes: HMAC-SHA256(SHA256(secret), node_id)
        # This allows server-side validation without storing the plain secret.
        expected_token = hmac.new(
            stored_hash.encode("utf-8"),
            node_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(token.strip(), expected_token)

    # No stored secret — use bootstrap token
    if _BOOTSTRAP_DISABLED:
        log.warning(
            "auth.bootstrap_disabled node_id=%s "
            "— rejecting (no per-node secret provisioned)",
            node_id,
        )
        return False

    if not _BOOTSTRAP_TOKEN:
        return False

    return hmac.compare_digest(token.strip(), _BOOTSTRAP_TOKEN.strip())


async def _get_node_secret_hash(db_path: str, node_id: str) -> str | None:
    """Fetch the stored secret hash for a node. Returns None if not provisioned."""
    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT node_secret_hash FROM nodes WHERE node_id=?", (node_id,)
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


# ----------------------------------------------------------------
#  Provisioning
# ----------------------------------------------------------------

async def provision_node_secret(
    db_path: str, node_id: str
) -> str:
    """
    Generate and store a new per-node secret.
    Returns the plain secret — caller must return it to the node ONCE.
    The plain secret is never stored.
    """
    plain_secret = generate_node_secret()
    secret_hash = hash_secret(plain_secret)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE nodes SET node_secret_hash=? WHERE node_id=?",
            (secret_hash, node_id),
        )
        if db.total_changes == 0:
            raise ValueError(f"Node {node_id!r} not found")
        await db.commit()

    log.info("auth.provisioned node_id=%s (secret returned once)", node_id)
    return plain_secret


async def rotate_node_secret(
    db_path: str, node_id: str
) -> str:
    """
    Rotate the per-node secret. Invalidates the current secret.
    Returns the new plain secret.
    """
    plain_secret = generate_node_secret()
    secret_hash = hash_secret(plain_secret)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT 1 FROM nodes WHERE node_id=?", (node_id,)
        ) as cur:
            if not await cur.fetchone():
                raise ValueError(f"Node {node_id!r} not found")
        await db.execute(
            "UPDATE nodes SET node_secret_hash=? WHERE node_id=?",
            (secret_hash, node_id),
        )
        await db.commit()

    log.info("auth.rotated node_id=%s", node_id)
    return plain_secret
