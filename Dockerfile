FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements-api.lock .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --requirement requirements-api.lock

FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    LOG_LEVEL=INFO \
    MODEL_ROOT=/app/models \
    CORS_ORIGINS=http://localhost:3000

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system api \
    && adduser --system --ingroup api --home /nonexistent --no-create-home api

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY api/__init__.py api/config.py api/errors.py api/logging.py api/main.py \
     api/schemas.py api/status.py api/ui.py ./api/
COPY api/services ./api/services
COPY api/static ./api/static
COPY models/FINAL_STATUS.json models/FINAL_STATUS.sha256.json ./models/
COPY models/api_bundle ./models/api_bundle

USER api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=2)"]
CMD ["sh", "-c", "exec uvicorn api.main:app --host ${API_HOST} --port ${API_PORT} --workers 1 --no-access-log"]
