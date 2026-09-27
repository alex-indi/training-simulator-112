FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
WORKDIR /app/backend
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim

WORKDIR /app/backend
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY --from=builder /app/backend/.venv .venv
COPY backend/alembic.ini ./
COPY backend/app app
COPY backend/migrations migrations
COPY backend/scripts scripts
COPY backend/seed seed

EXPOSE 8000
CMD ["/bin/sh", "-c", "alembic upgrade head && exec uvicorn app.main:socket_app --host 0.0.0.0 --port 8000 --workers 1"]
