# Admin API Reference

The admin API provides fleet management operations requiring elevated credentials. All endpoints require the `X-CNP-Admin-Token` header.

> **Security:** The admin token must be different from the node bootstrap token. Store it as `ADMIN_TOKEN` in your environment (see `.env.example`). Never expose admin endpoints on a public network interface.

---

## Authentication

All admin endpoints require:

```http
X-CNP-Admin-Token: <your-ADMIN_TOKEN>
```

A missing or invalid token returns:

```json
{
  "error": {
    "code": "unauthorized",
    "message": "X-CNP-Admin-Token header is required",
    "details": {}
  }
}
```
**Status:** `401 Unauthorized`

If `ADMIN_TOKEN` is not configured on the gateway:
```json
{
  "error": {
    "code": "admin_not_configured",
    "message": "ADMIN_TOKEN is not configured on this gateway",
    "details": {}
  }
}
```
**Status:** `503 Service Unavailable`

---

## Endpoints

### GET /api/fleet/status

Returns the current node count broken down by zone and status.

**Request**
```http
GET /api/fleet/status
X-CNP-Admin-Token: your-admin-token
```

**Response** `200 OK`
```json
{
  "zones": [
    {
      "zone": "lab",
      "total": 3,
      "online": 2,
      "offline": 1
    },
    {
      "zone": "office",
      "total": 5,
      "online": 5
    },
    {
      "zone": "unassigned",
      "total": 1,
      "unknown": 1
    }
  ],
  "zone_count": 3
}
```

**Notes**
- Retired nodes (`status = 'retired'`) are excluded from all counts
- `zone` is extracted from `nodes.metadata_json -> '$.zone'`; nodes without a zone appear under `"unassigned"`
- Status keys (`online`, `offline`, `unknown`) only appear in a zone object if at least one node has that status

---

### POST /api/nodes/{node_id}/provision

Generate and store a new per-node HMAC secret. The secret is returned **once** and cannot be retrieved again.

**Path parameters**

| Parameter | Type | Description |
|---|---|---|
| `node_id` | string | The node to provision. Must already be registered via `/api/node/hello`. |

**Request**
```http
POST /api/nodes/cnp-lab-temp-01/provision
X-CNP-Admin-Token: your-admin-token
```

**Response** `200 OK`
```json
{
  "node_id": "cnp-lab-temp-01",
  "secret": "a3f8e2c1d4b5a6f7e8d9c0b1a2f3e4d5c6b7a8f9e0d1c2b3a4f5e6d7c8b9a0f1",
  "instructions": "Store this secret on the node in NVS. Compute X-CNP-Node-Token as HMAC-SHA256(SHA256(secret), node_id). This secret is shown ONCE and cannot be retrieved."
}
```

**Error responses**

`404 Not Found` — node_id does not exist in the registry:
```json
{
  "error": {
    "code": "node_not_found",
    "message": "node_id not found",
    "details": { "node_id": "cnp-lab-temp-01" }
  }
}
```

**Security flow**

```
1. Gateway generates:  plain_secret = secrets.token_hex(32)
2. Gateway stores:     SHA256(plain_secret) in nodes.node_secret_hash
3. Gateway returns:    plain_secret (once only)
4. Node computes:      token = HMAC-SHA256(SHA256(plain_secret), node_id)
5. Node sends:         X-CNP-Node-Token: <token> on all requests
6. Gateway validates:  recompute expected_token from stored hash, compare_digest
```

The plain secret never leaves this response and is not stored on the gateway. If lost, rotate using `/api/nodes/{id}/rotate-secret`.

---

### POST /api/nodes/{node_id}/rotate-secret

Rotate the per-node secret. **The previous secret is immediately invalidated.** The node will be unable to communicate until it receives and stores the new secret.

**Path parameters**

| Parameter | Type | Description |
|---|---|---|
| `node_id` | string | The node whose secret to rotate. |

**Request**
```http
POST /api/nodes/cnp-lab-temp-01/rotate-secret
X-CNP-Admin-Token: your-admin-token
```

**Response** `200 OK`
```json
{
  "node_id": "cnp-lab-temp-01",
  "secret": "b4e9f3d2c5a6b7e8f9d0c1b2a3f4e5d6c7b8a9f0e1d2c3b4a5f6e7d8c9b0a1f2",
  "instructions": "The previous secret is now invalid. Deploy this new secret to the node via secure channel (USB/QR). This secret is shown ONCE."
}
```

**Error responses**

Same as `/provision` — `404` if node not found, `401` if token invalid.

**Deployment workflow for secret rotation**

```
1. Call POST /api/nodes/{id}/rotate-secret → receive new_secret
2. Connect to node physically (USB serial) or via an out-of-band channel
3. Flash new_secret into NVS:
      Preferences prefs;
      prefs.begin("cnp", false);
      prefs.putString("node_secret", new_secret);
      prefs.end();
4. Node reboots → computes new token → resumes normal operation
```

If you have OTA capability and the current secret is still valid (pre-emptive rotation), you can deliver the new secret via a `config_update` command before rotating.

---

## Error shape reference

All admin endpoints return structured errors consistent with the rest of the CNP Gateway API:

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "details": {},
    "timestamp": "2026-03-18T12:00:00Z",
    "path": "/api/nodes/cnp-xyz/provision"
  }
}
```

| Code | Status | Meaning |
|---|---|---|
| `unauthorized` | 401 | Missing or invalid `X-CNP-Admin-Token` |
| `admin_not_configured` | 503 | `ADMIN_TOKEN` env var not set on gateway |
| `node_not_found` | 404 | `node_id` does not exist in registry |

---

## Audit logging

All admin operations are logged at `INFO` level with structured fields:

```
admin.provision node_id=cnp-lab-temp-01
admin.rotate node_id=cnp-lab-temp-01
```

These log lines can be used to build an audit trail. In production, pipe gateway logs to a log aggregator (Loki, CloudWatch, etc.) and alert on unexpected `admin.provision` or `admin.rotate` events.
