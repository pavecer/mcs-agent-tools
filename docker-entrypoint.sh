#!/bin/sh
# Production container entrypoint.
# Starts Reflex first, waits for internal ports, then starts nginx
# (external reverse proxy on PORT).
set -e

FRONTEND_PORT="${FRONTEND_PORT:-3100}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
PORT="${PORT:-2009}"
export FRONTEND_PORT BACKEND_PORT PORT

echo "--- Starting Reflex (frontend :${FRONTEND_PORT}, backend :${BACKEND_PORT}) ---"
uv run reflex run --env prod --loglevel info &
REFLEX_PID=$!

# Wait for Reflex sockets; fail fast if process exits.
python3 - <<'PY'
import os
import socket
import sys
import time

frontend = int(os.environ.get("FRONTEND_PORT", "3100"))
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
	if is_open(frontend) and is_open(backend):
		print(f"Reflex is ready on frontend:{frontend} backend:{backend}")
		sys.exit(0)
	time.sleep(1)

print(
	f"Timed out waiting for Reflex ports frontend:{frontend} backend:{backend}",
	file=sys.stderr,
)
sys.exit(1)
PY

echo "--- Starting nginx on port ${PORT} ---"
nginx -c /app/nginx.conf

# Keep container tied to Reflex lifecycle.
wait "$REFLEX_PID"
