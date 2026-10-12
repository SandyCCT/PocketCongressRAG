FROM python:3.12-slim-bookworm AS runtime-base

ENV PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    TZ=Asia/Taipei

WORKDIR /app

RUN pip install --no-cache-dir poetry==2.2.1

COPY pyproject.toml poetry.lock README.md ./
RUN poetry install --only main --no-root --no-interaction --no-ansi

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/instance /app/deployment \
    && chown -R appuser:appuser /app/instance /app/deployment

COPY --chown=appuser:appuser src/ ./src/

USER appuser
WORKDIR /app/src

EXPOSE 8000
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn api:app --host 0.0.0.0 --port \"${PORT:-8000}\" --workers 1"]


# Cloud Run image: bundle is validated before this target is built.
FROM runtime-base AS cloud

ARG DEPLOYMENT_BUNDLE_PATH=deployment_bundles/2026-09-28-v6

ENV CHROMA_DIR=/app/instance/chroma_db \
    DB_PATH=/app/instance/legislature.db \
    LOG_DIR=/app/instance/logs \
    LOG_FILE_ENABLED=false \
    RUNTIME_METADATA_PATH=/app/deployment/runtime_metadata.json \
    DEPLOYMENT_MANIFEST_PATH=/app/deployment/manifest.json \
    INDEX_REBUILD_POLICY=verify_only

COPY --chown=appuser:appuser ${DEPLOYMENT_BUNDLE_PATH}/instance/ /app/instance/
COPY --chown=appuser:appuser ${DEPLOYMENT_BUNDLE_PATH}/runtime_metadata.json /app/deployment/runtime_metadata.json
COPY --chown=appuser:appuser ${DEPLOYMENT_BUNDLE_PATH}/manifest.json /app/deployment/manifest.json


# Local Compose image: data and indexes are mounted from the host.
FROM runtime-base AS local

ENV LOG_DIR=/app/instance/logs \
    LOG_FILE_ENABLED=true \
    RUNTIME_METADATA_PATH="" \
    DEPLOYMENT_MANIFEST_PATH=""
