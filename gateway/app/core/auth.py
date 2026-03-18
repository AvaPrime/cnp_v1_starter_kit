from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets

from .db import db_connect

log = logging.getLogger("cnp.auth")

_BOOTSTRAP_TOKEN: str = os.environ.get("BOOTSTRAP_TOKEN", "")
_BOOTSTRAP_DISABLED: bool = (
    os.environ.get("BOOTSTRAP_DISABLED", "false").lower() == "true"
)


def generate_node_secret() -> str:
    return secrets.token_hex(32)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def compute_node_token(node_id: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        node_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def validate_node_token(
    db_path: str,
    node_id: str,
    token: str | None,
) -> bool:
    if not token:
        return False

    stored_hash = await _get_node_secret_hash(db_path, node_id)

    if stored_hash:
        expected_token = hmac.new(
            stored_hash.encode("utf-8"),
            node_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(token.strip(), expected_token)

    if _BOOTSTRAP_DISABLED:
        log.warning(
            (
                "auth.bootstrap_disabled node_id=%s — rejecting "
                "(no per-node secret provisioned)"
            ),
            node_id,
        )
        return False

    if not _BOOTSTRAP_TOKEN:
        return False

    return hmac.compare_digest(token.strip(), _BOOTSTRAP_TOKEN.strip())


async def _get_node_secret_hash(db_path: str, node_id: str) -> str | None:
    try:
        async with db_connect(db_path) as db:
            async with db.execute(
                "SELECT node_secret_hash FROM nodes WHERE node_id=?", (node_id,)
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


async def provision_node_secret(
    db_path: str, node_id: str
) -> str:
    plain_secret = generate_node_secret()
    secret_hash = hash_secret(plain_secret)

    async with db_connect(db_path) as db:
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
    plain_secret = generate_node_secret()
    secret_hash = hash_secret(plain_secret)

    async with db_connect(db_path) as db:
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
