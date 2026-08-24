FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1

# Dependencies first, so a code change does not redo this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY kebplayground ./kebplayground
RUN uv sync --frozen --no-dev

# Shell form on purpose: Cloud Run passes the port through $PORT.
CMD uv run --no-sync uvicorn kebplayground.web.app:app --host 0.0.0.0 --port ${PORT:-8080}
