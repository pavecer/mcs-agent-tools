#!/bin/bash
# Download external static assets required for local development.
#
# Assets are gitignored (assets/external/) and must be fetched before
# running `uv run reflex run` for the first time, or after a clean checkout.
#
# The Docker build performs this step automatically (see Dockerfile).
# Run this script once on your local machine:
#
#   bash scripts/download-assets.sh
#
set -euo pipefail

ASSETS_DIR="$(cd "$(dirname "$0")/.." && pwd)/assets/external"
MERMAID_VERSION="11"
MERMAID_DEST="$ASSETS_DIR/mermaid.min.js"

echo "==> Downloading external assets for local development ..."
mkdir -p "$ASSETS_DIR"

if [ -f "$MERMAID_DEST" ]; then
    echo "    mermaid.min.js already present — skipping."
else
    TMP_DIR=$(mktemp -d)
    echo "    Installing mermaid@${MERMAID_VERSION} via npm ..."
    npm install --prefix "$TMP_DIR" "mermaid@${MERMAID_VERSION}" --silent
    cp "$TMP_DIR/node_modules/mermaid/dist/mermaid.min.js" "$MERMAID_DEST"
    rm -rf "$TMP_DIR"
    echo "    mermaid.min.js → $MERMAID_DEST"
fi

echo "==> Done. External assets are ready."
