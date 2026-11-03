# Celery worker image. Built with the backend directory as context
# (see docker-compose.yml: context ./backend, dockerfile ../worker/Dockerfile),
# so the worker runs exactly the same domain code as the API, but as an independent process.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home /app app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml ./
COPY app ./app

USER app
CMD ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=INFO", "-Q", "deliveries,maintenance", "--concurrency=4", "-n", "celery@%h"]
