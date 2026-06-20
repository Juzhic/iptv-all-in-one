FROM python:3.12-slim

WORKDIR /app

# Install FFmpeg and Node.js
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Build frontend
RUN cd frontend && npm install --production=false && npm run build

# Remove Node.js after build (keep only runtime)
RUN apt-get purge -y nodejs && apt-get autoremove -y

# Create data directories
RUN mkdir -p data output

EXPOSE 58080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:58080/api/health || exit 1

CMD ["python", "-m", "web"]
