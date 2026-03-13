#!/bin/sh
# Production container entrypoint.
# Starts Reflex backend only, waits for backend port, then starts nginx
# to serve exported static frontend and proxy backend endpoints.
set -e

BACKEND_PORT="${BACKEND_PORT:-8000}"
PORT="${PORT:-2009}"
export BACKEND_PORT PORT

echo "--- Starting Reflex backend (:${BACKEND_PORT}) ---"
uv run reflex run --env prod --backend-only --loglevel info &
REFLEX_PID=$!

# Wait for backend socket; fail fast if process exits.
python3 - <<'PY'
import os
import socket
import sys
import time

backend = int(os.environ.get("BACKEND_PORT", "8000"))
deadline = time.time() + 90

def is_open(port: int) -> bool:
	for host in ("127.0.0.1", "::1"):
		fam = socket.AF_INET6 if ":" in host else socket.AF_INET
		s = socket.socket(fam, socket.SOCK_STREAM)
		s.settimeout(0.25)
		try:
			s.connect((host, port))
			return True
		except OSError:
			pass
		finally:
			s.close()
	return False

while time.time() < deadline:
	if is_open(backend):
		print(f"Reflex backend is ready on port:{backend}")
		sys.exit(0)
	time.sleep(1)

print(
	f"Timed out waiting for Reflex backend port:{backend}",
	file=sys.stderr,
)
sys.exit(1)
PY

echo "--- Starting nginx on port ${PORT} ---"
nginx -c /app/nginx.conf

# Keep container tied to Reflex lifecycle.
wait "$REFLEX_PID"
