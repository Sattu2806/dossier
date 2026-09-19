# Two stages: dependencies are installed once into a virtualenv, and the
# runtime image copies it. Keeping uv out of the final image means a smaller
# attack surface and nothing that can install packages at runtime.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, in their own layer: application code changes on every
# commit, the lockfile rarely does, so this layer stays cached.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev --extra postgres

COPY src/ ./src/
COPY evals/topics.json ./evals/topics.json
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra postgres


FROM python:3.13-slim-bookworm AS runtime

# Never run as root, and give the app a home it can write to for the
# Chroma index and, in single-container deployments, the SQLite file.
RUN useradd --create-home --uid 10001 dossier \
    && mkdir -p /data && chown dossier:dossier /data

WORKDIR /app
COPY --from=builder --chown=dossier:dossier /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DOSSIER_HOST=0.0.0.0 \
    DOSSIER_PORT=8500 \
    DOSSIER_DATA_DIR=/data/chroma \
    DOSSIER_DATABASE_URL=sqlite:////data/dossier.db

USER dossier
EXPOSE 8500
VOLUME ["/data"]

# No curl in a slim image, so the check uses the interpreter that is already here.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8500/health', timeout=4).status==200 else 1)"

CMD ["dossier", "serve"]
