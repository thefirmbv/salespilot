# Multi-stage Dockerfile for the FastAPI service.
#
# - `dev`  target installs everything incl. dev deps and is used by
#   docker-compose.override.yml with the source bind-mounted.
# - `production` target installs only runtime deps and copies in the source.

ARG PYTHON_VERSION=3.13-slim-bookworm

# ---------- base: shared system + Python wheels ----------
FROM python:${PYTHON_VERSION} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for psycopg, cryptography, etc. Kept in a separate layer so
# they can be removed in the production target.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    dnsutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps separately so they are cached.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e ".[dev]"

# ---------- dev target ----------
FROM base AS dev

# Source is bind-mounted by docker-compose.override.yml; no COPY needed.
EXPOSE 8000
CMD ["uvicorn", "salespilot.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------- production target ----------
FROM python:${PYTHON_VERSION} AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Runtime deps only (no compilers).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    dnsutils \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app

# Copy installed site-packages from base.
COPY --from=base /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=base /usr/local/bin /usr/local/bin

COPY --chown=app:app . /app

USER app
EXPOSE 8000

CMD ["uvicorn", "salespilot.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
