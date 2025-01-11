FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080 \
    FLASK_APP=src/server.py \
    FLASK_ENV=production \
    APP_BASE_URL=https://youtube-downloader-api-1010279005443.europe-west1.run.app \
    USE_GCS=True \
    GCS_BUCKET_NAME=nca-toolkit-bucket-jimeny

EXPOSE 8080

CMD ["gunicorn", "--bind", ":8080", "--workers", "1", "--threads", "8", "--timeout", "0", "src.server:app"]