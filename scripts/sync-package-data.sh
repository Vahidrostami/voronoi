#!/bin/bash
set -euo pipefail

# Sync root .env.example → src/voronoi/data/.env.example
#
# src/voronoi/data/.env.example is tracked in git and is the canonical
# runtime copy shipped with pip install. Run this script only when the
# repo-root .env.example is updated and you want to propagate it.
#
# All other runtime content (agents, prompts, skills, scripts, demos,
# templates) is maintained in-tree under src/voronoi/data/ and never
# needs syncing.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$REPO_ROOT/src/voronoi/data"

echo "Syncing .env.example → $DATA_DIR"

# .env.example
if [ -f "$REPO_ROOT/.env.example" ]; then
    cp "$REPO_ROOT/.env.example" "$DATA_DIR/.env.example"
    echo "  ✓ .env.example"
fi

echo "✓ Done. Remember to commit src/voronoi/data/.env.example."
