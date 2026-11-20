# RampScout: one image for the web service (API + built UI) and the worker.

FROM node:24-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/rampscout ./rampscout
COPY backend/scripts ./scripts
COPY backend/alembic.ini ./
RUN pip install .
COPY --from=web /web/dist /app/frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist PORT=8000
RUN useradd --create-home rampscout
USER rampscout
EXPOSE 8000
# Web: migrate, then serve. The worker overrides CMD (see render.yaml / docker-compose.yml).
CMD ["sh", "-c", "alembic upgrade head && uvicorn rampscout.api.server:app --host 0.0.0.0 --port ${PORT}"]
