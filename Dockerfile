FROM python:3.9-slim

# Create non-root user for security
RUN useradd -m -r -u 1001 appuser

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (for better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create necessary directories with proper permissions
RUN mkdir -p /app/downloads /app/jsons && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Set environment variables
ENV PORT=8080 \
    FLASK_APP=src/server.py \
    FLASK_ENV=production \
    APP_BASE_URL=https://youtube-downloader-api-1010279005443.europe-west1.run.app \
    USE_GCS=True \
    GCS_BUCKET_NAME=nca-toolkit-bucket-jimeny \
    DOWNLOAD_DIR=/app/downloads

# Expose the port
EXPOSE 8080

# Run the app with Gunicorn
CMD ["gunicorn", "--bind", ":8080", "--workers", "1", "--threads", "8", "--timeout", "0", "src.server:app"]