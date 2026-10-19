# One image for tube2dev-api, tube2dev-worker and the migrate/cleanup jobs; the command differs.
FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.11 /uv /uvx /bin/
# yt-dlp needs a JavaScript runtime to extract YouTube metadata reliably.
COPY --from=denoland/deno:bin-2.1.4 /deno /usr/local/bin/deno

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANGGRAPH_STRICT_MSGPACK=true \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first for layer caching
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

RUN useradd --uid 10001 --create-home app && mkdir -p /data && chown -R app /app /data
USER app

ENV PORT=8080
EXPOSE 8080
# Override per service:
#   worker:  uvicorn app.main_worker:app --host 0.0.0.0 --port 8080
#   migrate: python -m app.cli migrate
#   cleanup: python -m app.cli cleanup
CMD ["sh", "-c", "exec uvicorn app.main_api:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 20"]
