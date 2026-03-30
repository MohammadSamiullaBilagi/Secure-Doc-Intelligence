#!/bin/bash
set -e

echo "Running Alembic migrations..."
alembic upgrade head || echo "Alembic migration warning (may already be current)"

echo "Starting application..."
exec gunicorn main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 1 \
    --bind 0.0.0.0:8000 \
    --timeout 300 \
    --graceful-timeout 30
