#!/bin/sh
# Production container entrypoint.
# Starts nginx (external reverse proxy on PORT) then Reflex (Next.js on 3000
# + granian on 8000 internally).
set -e

echo "--- Starting nginx on port ${PORT:-2009} ---"
nginx -c /app/nginx.conf

echo "--- Starting Reflex (frontend :3000, backend :8000) ---"
exec uv run reflex run --env prod --loglevel info
