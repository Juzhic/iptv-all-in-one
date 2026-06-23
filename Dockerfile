# Stage 1: Build frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app
COPY frontend/ ./frontend/
RUN cd frontend && npm install && npm run build

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Install FFmpeg only
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Copy frontend build from stage 1
COPY --from=frontend-builder /app/dist ./dist

# Create data directories
RUN mkdir -p data output

EXPOSE 58080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:58080/api/health || exit 1

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:58080", "--timeout", "120", "web:app"]
