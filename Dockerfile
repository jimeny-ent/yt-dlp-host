FROM python:3.9-slim

# Create non-root user for security
RUN useradd -m -r -u 1001 appuser

WORKDIR /app

# Install system dependencies and build tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        wget \
        gnupg \
        software-properties-common \
        ffmpeg \
        build-essential \
        python3-dev \
        gcc \
        && apt-get clean \
        && rm -rf /var/lib/apt/lists/*

# Install Python packages one by one
RUN pip install --no-cache-dir Flask==3.0.3
RUN pip install --no-cache-dir gunicorn==21.2.0
RUN pip install --no-cache-dir google-cloud-storage==2.14.0
RUN pip install --no-cache-dir requests==2.31.0
RUN pip install --no-cache-dir yt-dlp==2024.8.6

# Create necessary directories first
RUN mkdir -p /app/downloads /app/jsons /app/src

# Copy files with explicit paths to maintain structure
COPY config.py /app/
COPY requirements.txt /app/
COPY src/ /app/src/
COPY jsons/ /app/jsons/

# Create empty __init__.py if it doesn't exist
RUN touch /app/src/__init__.py

# Set proper permissions
RUN chown -R appuser:appuser /app && \
    chmod -R 755 /app

# Switch to non-root user
USER appuser

# Set environment variables
ENV PORT=8080 \
    FLASK_APP=src/server.py \
    FLASK_ENV=production \
    APP_BASE_URL=https://youtube-downloader-api-1010279005443.europe-west1.run.app \
    USE_GCS=True \
    GCS_BUCKET_NAME=nca-toolkit-bucket-jimeny \
    DOWNLOAD_DIR=/app/downloads \
    PYTHONPATH=/app \
    MAX_WORKERS=4 \
    TASK_CLEANUP_TIME=30 \
    GUNICORN_TIMEOUT=300 \
    GUNICORN_WORKERS=1 \
    REQUEST_LIMIT=10 \
    DEFAULT_MEMORY_QUOTA=5368709120 \
    DEFAULT_MEMORY_QUOTA_RATE=10 \
    AVAILABLE_MEMORY=53687091200

# Expose the port
EXPOSE 8080

# Run the app with Gunicorn
CMD ["gunicorn", "--bind", ":8080", "--workers", "1", "--threads", "8", "--timeout", "0", "src.server:app"]