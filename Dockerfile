# syntax=docker/dockerfile:1
# The API in a container: http://<host>:8000 (docs at /docs). Runs are kept in
# the PostgreSQL database of BALATRO_API_DATABASE_URL. /data is where the SQLite
# file of earlier versions is read from, to import it (README.md, Storage).
#
#   docker build --network host -t balatro-api .
#   docker run -p 8000:8000 -e BALATRO_API_DATABASE_URL=postgresql://... balatro-api
#
# (--network host: the build downloads through this machine's connection, which
# also works behind a VPN whose MTU is smaller than Docker's bridge.)

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /bin/uv
# the engine is a git dependency (pyproject.toml, [tool.uv.sources])
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --system --uid 10001 --no-create-home balatro && mkdir /data && chown balatro /data
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    BALATRO_API_HOST=0.0.0.0 \
    BALATRO_API_PORT=8000
USER balatro
WORKDIR /data
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"]
CMD ["balatro-api"]
