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
    FFMPEG_BIN=/usr/bin/ffmpeg

# Install FFmpeg only
RUN apt-get update && \
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

# Copy frontend build from stage 1
COPY --from=frontend-builder /app/dist ./dist

# Create data directories
RUN mkdir -p data output

EXPOSE 58080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:58080/api/health || exit 1

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:58080", "--timeout", "120", "web:app"]
