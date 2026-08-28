# syntax=docker/dockerfile:1

# Stage 1: Build frontend. Both base images publish amd64 and arm64 variants.
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

# Install the minimal runtime system packages.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg tzdata && \
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

# Copy frontend build from stage 1
COPY --from=frontend-builder /app/dist ./dist

# Runtime source, dependencies and frontend assets stay root-owned/read-only.
# UID 10001 owns the only two application-writable paths.
RUN groupadd --gid 10001 iptv \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin iptv \
    && mkdir -p /app/data /app/output \
    && chown -R iptv:iptv /app/data /app/output \
    && chmod 0750 /app/data /app/output \
    && chmod -R a-w /app/engine /app/web /app/database /app/scanner_integration /app/dist \
    && chmod a-w /app/requirements.txt

USER 10001:10001

EXPOSE 58080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:58080/api/health', timeout=4).read()"]

CMD ["gunicorn", "-w", "1", "--worker-class", "gthread", "--threads", "8", "-b", "0.0.0.0:58080", "--timeout", "120", "web:app"]
