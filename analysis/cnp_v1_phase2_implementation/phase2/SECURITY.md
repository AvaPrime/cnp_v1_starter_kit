# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| `0.2.x` (gateway/ — current) | ✅ Active |
| `0.1.x` (legacy/ flat gateway) | ❌ No security patches — upgrade to 0.2.x |

---

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.** Public disclosure before a fix is available puts all deployments at risk.

### How to report

1. **GitHub private advisory (preferred):** Go to [Security → Advisories → Report a vulnerability](https://github.com/AvaPrime/cnp_v1_starter_kit/security/advisories/new) on the repository page. This is a private channel visible only to maintainers.

2. **Email fallback:** If you cannot use GitHub advisories, email the maintainer directly. Find the contact in the repository's GitHub profile.

### What to include

A good vulnerability report includes:
- **Description** — what the vulnerability is and which component is affected
- **Steps to reproduce** — minimal curl commands, code snippets, or configuration needed to trigger it
- **Impact assessment** — what an attacker can achieve (data access, privilege escalation, DoS, etc.)
- **Affected versions** — which gateway version(s) you tested against
- **Suggested fix** — optional but appreciated

---

## Response timeline

| Stage | Target |
|---|---|
| Initial acknowledgement | Within 48 hours |
| Severity assessment | Within 5 business days |
| Fix developed and reviewed | Within 14 days for CRITICAL/HIGH, 30 days for MEDIUM |
| Public disclosure | Coordinated with reporter after fix is released |

We will keep you informed at each stage. If you do not receive an acknowledgement within 48 hours, please follow up.

---

## Known security posture

### Authentication

- **Node auth (X-CNP-Node-Token):** Bootstrap phase uses a shared `BOOTSTRAP_TOKEN`. After node registration, per-node secrets provisioned via `/api/nodes/{id}/provision` provide HMAC-SHA256 derived tokens unique to each node. Per-node secrets are stored as SHA-256 hashes — the plaintext is shown once at provisioning and cannot be retrieved.
- **Admin auth (X-CNP-Admin-Token):** Admin operations (secret provisioning, rotation, fleet status) require a separate `ADMIN_TOKEN` with no relation to node tokens.

### Transport

- **HTTP gateway:** The gateway does not terminate TLS natively. In production, always place a TLS-terminating reverse proxy (Caddy, nginx, Traefik) in front of the gateway. See [TLS_SETUP.md](TLS_SETUP.md).
- **MQTT transport:** Mosquitto should be configured with TLS and password authentication for all production deployments. The `examples/mosquitto.conf` is for local development only — it does not enable TLS or authentication.

### Known limitations (by design)

- **Rate limiting is process-local.** In multi-worker deployments, each worker maintains independent rate limit windows. The effective rate budget scales with worker count. A Redis-backed shared rate limiter is planned for Phase 3. For single-worker deployments (the default Docker configuration) this is not a concern.
- **SQLite is the backing store.** The gateway is designed for single-node or small-fleet deployments. SQLite is not suitable for high-write fleet scenarios with hundreds of nodes — the Phase 6 roadmap addresses this.

### Security hardening checklist for production deployments

Before exposing the gateway to a network:

- [ ] `BOOTSTRAP_TOKEN` is a randomly generated secret of at least 32 hex characters: `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] `ADMIN_TOKEN` is a different randomly generated secret of at least 32 hex characters
- [ ] Neither token is committed to git (check with `git log -p | grep -i token`)
- [ ] TLS termination is in place upstream of the gateway
- [ ] MQTT broker uses TLS + password authentication (see TLS_SETUP.md)
- [ ] `TRUSTED_PROXIES` is set to your reverse proxy IP/CIDR if behind a proxy
- [ ] The SQLite database file is on a volume with appropriate filesystem permissions (mode 600)
- [ ] Docker container runs as non-root (the provided Dockerfile does this)
- [ ] Admin endpoints (`/api/nodes/*/provision`, `/api/nodes/*/rotate-secret`, `/api/fleet/status`) are not exposed on a public network interface

---

## Scope

This security policy covers:
- The gateway application (`gateway/app/`)
- The MQTT bridge (`gateway/app/core/mqtt_client.py`)
- Authentication and authorization logic (`gateway/app/core/auth.py`, `gateway/app/api/admin.py`)
- The CNP v1 message schema (`cnp_v1_schemas.json`)

Out of scope:
- `legacy/` — archived files, no longer maintained
- Third-party dependencies (report those to their respective maintainers and we will update our dependency versions)
- Vulnerabilities that require physical access to the ESP32 device (hardware security is out of scope)
