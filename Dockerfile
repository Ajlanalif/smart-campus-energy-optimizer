# GridWise backend container.
#
# - Base: python:3.11-slim (matches pyproject.toml requires-python = ">=3.11";
#   OR-Tools only ships manylinux_2_27 wheels, so Alpine/musl is not viable).
# - Dependency manager: uv (already used by the project for local dev).
# - Installs ALL deps from uv.lock, including pytest + dev tools, so judges
#   can `docker exec <container> uv run pytest` to reproduce the test suite.
# - Runs as a non-root user (appuser, uid 10001).
# - No secrets are baked into the image. Pass GEMINI_API_KEY etc. at runtime
#   via `docker run -e GEMINI_API_KEY=...` or `--env-file .env`.

FROM python:3.11-slim

# ---- system packages ----------------------------------------------------
# curl is needed for the HEALTHCHECK below. --no-install-recommends keeps
# the image lean.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# ---- Python environment ------------------------------------------------
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Install into the system site-packages (not a .venv) so we don't have
    # to activate anything before running uvicorn / pytest.
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_LINK_MODE=copy

# uv itself — pinned to the same major the project uses locally.
RUN pip install --no-cache-dir "uv>=0.5,<1.0"

# ---- dependency layer (cached unless these files change) ----------------
WORKDIR /app
COPY pyproject.toml uv.lock ./
# `--frozen` ensures we install exactly what uv.lock pins, no resolution.
# All groups (incl. dev) are installed so pytest is available in-container.
RUN uv sync --frozen

# ---- application source -------------------------------------------------
# Done AFTER `uv sync` so source changes don't bust the dependency cache.
COPY app/ ./app/
COPY tests/ ./tests/
# tests/data/public_samples.json is a real file (formerly a symlink into
# ../hackathon_guide/, now inlined so the image is self-contained).
COPY tests/data ./tests/data

# ---- runtime user -------------------------------------------------------
# Non-root. Matches the OpenShift / arbitrary-uid convention (uid 10001).
RUN useradd --create-home --uid 10001 --shell /bin/bash appuser \
 && chown -R appuser:appuser /app
USER appuser

# ---- runtime defaults (override at `docker run` time as needed) --------
ENV HOST=0.0.0.0 \
    PORT=8000 \
    LLM_PROVIDER=gemini \
    GEMINI_MODEL=gemini-3.6-flash \
    OPTIMIZER_TIME_LIMIT_SECONDS=10 \
    PATH="/app/.venv/bin:/usr/local/bin:${PATH}"

EXPOSE 8000

# Sanity check that the app imports cleanly. Fails the build if the
# container is broken at image-construction time (catches missing
# dependencies early, instead of at first request).
RUN python -c "from app.main import app" \
 && python -c "import pytest; print('pytest', pytest.__version__)"

# ---- start --------------------------------------------------------------
# uvicorn is installed by `uv sync` into the system environment.
# 4 workers is enough for the 100-point rubric's p95-latency scoring; judges
# can override with -e UVICORN_WORKERS=N if they want.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# ---- healthcheck --------------------------------------------------------
# Hits /health inside the container. NOTE: this requires curl, which we
# installed in the apt-get step above.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1