# ─────────────────────────────────────────────────────────────────────────────
# PP Agent Toolkit — Production Docker image
#
# Single-stage build (Node.js required both at build time to compile the
# Reflex/Next.js frontend and at runtime if Reflex needs to hot-patch assets).
# Image size is ~700 MB; the trade-off is a reliable, no-fuss container.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# ── System packages: Node.js 20 LTS + nginx ──────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl unzip nginx \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── uv (fast Python package manager) ─────────────────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# ── Python dependencies (cached independently of application source) ──────────
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

# ── Production environment ────────────────────────────────────────────────────
ENV REFLEX_ENV=prod \
    PORT=2009

# API_URL is the public URL the browser uses for WebSocket connections.
# It is baked into the JS bundle by `reflex export`.
# Override at build time: docker build --build-arg API_URL=https://<your-fqdn>
# Defaults to localhost:2009 (works for local `docker run -p 2009:2009`).
ARG API_URL=http://localhost:2009
ENV API_URL=$API_URL

# ── Application source ────────────────────────────────────────────────────────
# All source must be present before `reflex init` so that Reflex finds the
# existing `web/` app module and does NOT prompt for a template (which aborts
# in a non-interactive ACR build environment).
COPY . .

# Create the uploads directory (gitignored, not present in the COPY above).
# Also create nginx temp dirs (required when running as non-root).
RUN mkdir -p uploaded_files \
    && mkdir -p /tmp/nginx_client_temp /tmp/nginx_proxy_temp \
        /tmp/nginx_fastcgi_temp /tmp/nginx_uwsgi_temp /tmp/nginx_scgi_temp \
    && chmod +x /app/docker-entrypoint.sh

# ── Reflex frontend setup ─────────────────────────────────────────────────────
# reflex init: installs npm packages into .web/ (requires web/ app to exist).
# reflex export: compiles the Next.js production build into .web/_static/.
RUN echo "--- node/npm versions ---" \
    && node --version \
    && npm --version \
    && echo "--- reflex init ---" \
    && uv run reflex init \
    && echo "--- reflex export ---" \
    && uv run reflex export --no-zip \
    && echo "--- build complete ---"

EXPOSE 2009

# USERS env var is injected at runtime via Azure Container App secrets —
# never bake credentials into the image.
# Topology: nginx:2009 (external) → Next.js:3000 (frontend) + granian:8000 (backend)
CMD ["/app/docker-entrypoint.sh"]
