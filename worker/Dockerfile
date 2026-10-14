FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Graceful shutdown: Celery checkpoints in-flight work on SIGTERM (later phases).
STOPSIGNAL SIGTERM

CMD ["celery", "-A", "app.celery_app.celery", "worker", "--loglevel=INFO", "--concurrency=4"]
