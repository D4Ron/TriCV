# --- stage 1: build the embeddable widget ----------------------------------
# The API serves /widget.js, so the bundle ships inside this image.
FROM node:22-alpine AS widget
WORKDIR /widget
COPY widget/package.json widget/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY widget/tsconfig.json ./tsconfig.json
COPY widget/vite.config.ts ./vite.config.ts
COPY widget/src ./src
RUN npm run build

# --- stage 2: the API -------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# spaCy models for local NER. Baked into the image so redaction — and therefore
# the whole analysis pipeline — works with no network at runtime.
RUN python -m spacy download fr_core_news_md \
 && python -m spacy download en_core_web_md

COPY backend/alembic.ini .
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/tools ./tools
COPY backend/tests ./tests
COPY backend/pytest.ini .
COPY backend/entrypoint.sh .
RUN chmod +x entrypoint.sh

COPY --from=widget /widget/dist/widget.js ./static/widget.js

RUN mkdir -p /data/cv

EXPOSE 8000
CMD ["./entrypoint.sh"]
