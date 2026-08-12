# Stage 1: Build frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app
ENV TZ=Asia/Shanghai \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FFMPEG_BIN=/usr/bin/ffmpeg

# Install FFmpeg only
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends ffmpeg curl tzdata && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy runtime project files only. Do not copy frontend sources into the
# runtime image, otherwise startup may try to rebuild them without Node/npm.
COPY engine/ ./engine/
COPY web/ ./web/
COPY database/ ./database/
COPY scanner_integration/ ./scanner_integration/
COPY generate_env.py migrate_2_0.py ./

# Copy frontend build from stage 1
COPY --from=frontend-builder /app/dist ./dist

# Runtime source, dependencies and frontend assets stay root-owned/read-only.
# UID 10001 owns the writable directories for hardened and first-2.0
# deployments; group root can also write when the current Compose file
# deliberately runs legacy compatibility as root. No access is granted to
# others.
RUN groupadd --gid 10001 iptv \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin iptv \
    && mkdir -p /app/data /app/output \
    && chown -R iptv:root /app/data /app/output \
    && chmod 0770 /app/data /app/output \
    && chmod -R a-w /app/engine /app/web /app/database /app/scanner_integration /app/dist \
    && chmod a-w /app/requirements.txt /app/generate_env.py /app/migrate_2_0.py

# Keep the image default compatible with both the standard 1.x Compose file
# (which had no application bind mounts) and the first 2.0 Compose release
# (which relied on the image USER and created UID-10001-owned volumes).
# The current Compose file can explicitly use compatibility root when an
# operator has older root-owned custom mounts.
USER 10001:10001

EXPOSE 58080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:58080/api/health || exit 1

CMD ["gunicorn", "-w", "1", "--worker-class", "gthread", "--threads", "8", "-b", "0.0.0.0:58080", "--timeout", "120", "web:app"]
