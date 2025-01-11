FROM python:3.9

WORKDIR /app

COPY requirements.txt .
RUN apt update && \
    apt install ffmpeg -y && \
    pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
ENV FLASK_APP=src/server.py
ENV FLASK_ENV=production
ENV APP_BASE_URL=https://youtube-downloader-api-1010279005443.europe-west1.run.app
ENV USE_GCS=True
ENV GCS_BUCKET_NAME=nca-toolkit-bucket-jimeny

EXPOSE 8080

# Use gunicorn for production
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 "src.server:app"
