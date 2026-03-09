# ─────────────────────────────────────────────────────────────────────────────
# PP Agent Toolkit — Production Docker image
#
# Single-stage build (Node.js required both at build time to compile the
# Reflex/Next.js frontend and at runtime if Reflex needs to hot-patch assets).
# Image size is ~700 MB; the trade-off is a reliable, no-fuss container.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# ── System packages: Node.js 20 LTS (needed by Reflex for the frontend) ──────
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

# ── uv (fast Python package manager) ─────────────────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# ── Python dependencies (install before copying source for better layer cache)
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

# ── Application source ────────────────────────────────────────────────────────
COPY . .

# Create the uploads directory (gitignored, not present in the COPY above).
RUN mkdir -p uploaded_files

# ── Production environment ────────────────────────────────────────────────────
ENV REFLEX_ENV=prod \
    PORT=2009

# Pre-initialise Reflex: installs npm packages into .web/ so container startup
# is fast (no npm install on every container boot).
RUN uv run reflex init

EXPOSE 2009

# USERS env var is injected at runtime via Azure Container App secrets —
# never bake credentials into the image.
CMD ["uv", "run", "reflex", "run", "--env", "prod", "--loglevel", "info"]
