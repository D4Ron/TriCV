#!/usr/bin/env bash
set -e

echo "[entrypoint] running migrations..."
alembic upgrade head

echo "[entrypoint] starting api..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
