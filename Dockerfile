# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first (cache layer)
COPY pyproject.toml uv.lock ./

# Install dependencies into .venv
RUN uv sync --frozen --no-dev

# --- Stage 2: Runtime ---
FROM python:3.12-slim AS runtime

# Install Tesseract OCR + system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY . .

# Ensure .venv/bin is on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV ENV=production

# Create directories for persistent volumes
RUN mkdir -p user_sessions global_vector_db Database blueprints

EXPOSE 8000

# Run Alembic migrations then start gunicorn
# --timeout 300: LLM-based audit/reconciliation can take minutes
# --workers 1: prevents duplicate APScheduler jobs; scale via container replicas
COPY entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]
