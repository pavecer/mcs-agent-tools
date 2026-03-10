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
        ca-certificates curl unzip \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── uv (fast Python package manager) ─────────────────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# ── Python dependencies (cached independently of application source) ──────────
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

# ── Production environment (set before reflex init/export so they pick it up) ─
ENV REFLEX_ENV=prod \
    PORT=2009

# ── Frontend scaffold: only re-runs when pyproject.toml / uv.lock change ─────
# reflex init downloads npm packages into .web/ — cache this expensive layer.
RUN uv run reflex init

# ── Application source ────────────────────────────────────────────────────────
# Copied AFTER reflex init so that source edits don't bust the npm-install layer.
COPY . .

# Create the uploads directory (gitignored, not present in the COPY above).
RUN mkdir -p uploaded_files

# Pre-build the Next.js frontend for production during image build.
# This avoids a heavy, time-constrained npm/next build at container startup
# which causes health-probe timeouts and container crashes on Container Apps.
RUN uv run reflex export --no-zip

EXPOSE 2009

# USERS env var is injected at runtime via Azure Container App secrets —
# never bake credentials into the image.
CMD ["uv", "run", "reflex", "run", "--env", "prod", "--backend-only", "--loglevel", "info"]
