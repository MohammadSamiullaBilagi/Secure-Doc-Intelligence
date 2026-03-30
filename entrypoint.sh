#!/bin/bash
set -e

echo "Running Alembic migrations..."
# If upgrade fails (e.g., tables already exist from create_all but alembic_version is behind),
# stamp to the pre-custom-notices revision, then retry upgrade to apply only new migrations.
if ! alembic upgrade head 2>/dev/null; then
    echo "Initial upgrade failed — stamping to known-good revision and retrying..."
    alembic stamp f7f1d8075e6a 2>/dev/null || true
    alembic upgrade head || echo "Alembic migration warning (may already be current)"
fi

echo "Starting application..."
exec gunicorn main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 1 \
    --bind 0.0.0.0:8000 \
    --timeout 300 \
    --graceful-timeout 30
