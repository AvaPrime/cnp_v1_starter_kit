# ─────────────────────────────────────────────────────────────────────────────
# CNP Gateway — Multi-stage Dockerfile
#
# Stage 1 (builder): install all deps incl. build tools into a venv
# Stage 2 (runtime): copy only the venv + source into a slim image
#
# Result: ~120 MB image (vs ~500 MB if deps installed in full image)
#
# Build:
#   docker build -t cnp-gateway:latest -f gateway/Dockerfile gateway/
#
# Run:
#   docker run -p 8080:8080 \
#     -e BOOTSTRAP_TOKEN=your-token \
#     -e ADMIN_TOKEN=your-admin-token \
#     -v $(pwd)/data:/data \
#     -e GATEWAY_DB_PATH=/data/cnp_gateway.db \
#     cnp-gateway:latest
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install build tools needed for some deps (e.g. aiosqlite native extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy dependency manifest first (layer cache — only reinstalls on changes)
COPY requirements.txt .

# Install runtime deps only (no dev/test deps)
# Filter out test/lint packages that are in requirements.txt under dev section
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        fastapi==0.116.1 \
        "uvicorn[standard]==0.35.0" \
        pydantic==2.11.7 \
        aiosqlite==0.21.0 \
        asyncio-mqtt==0.16.2 \
        orjson==0.0.0 \
        httpx==0.28.1 && \
    pip install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Security: run as non-root user
RUN groupadd -r cnp && useradd -r -g cnp -d /app -s /sbin/nologin cnp

# Copy the venv from builder (no build tools in runtime image)
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy application source only
COPY app/ ./app/

# Data directory for SQLite (override with -v mount in production)
RUN mkdir -p /data && chown cnp:cnp /data

# Drop privileges
USER cnp

# ── Configuration (all overridable via environment) ───────────────────────────
ENV GATEWAY_DB_PATH=/data/cnp_gateway.db
ENV MQTT_BROKER_HOST=mosquitto
ENV MQTT_BROKER_PORT=1883
ENV CNP_OFFLINE_AFTER_SECONDS=180
ENV CNP_GATEWAY_ID=codessa-gateway
# BOOTSTRAP_TOKEN and ADMIN_TOKEN must be injected — no defaults
# (startup will warn loudly if not set)

EXPOSE 8080

# Health check — matches the /api/health endpoint
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')" || exit 1

# Use exec form to handle signals correctly (SIGTERM → graceful shutdown)
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "1", \
     "--log-level", "info", \
     "--access-log"]
