#!/bin/bash
set -euo pipefail

# Sync optional files into src/voronoi/data/ for pip packaging.
#
# All core runtime content (agents, prompts, skills, scripts, demos,
# templates) is maintained in-tree under src/voronoi/data/ and does
# NOT need syncing.  This script only copies supplementary files that
# live at the repo root.
#
# Layout of src/voronoi/data/:
#   ├── agents/        ← canonical (in-tree)
#   ├── skills/        ← canonical (in-tree)
#   ├── prompts/       ← canonical (in-tree)
#   ├── scripts/       ← canonical (in-tree)
#   ├── demos/         ← canonical (in-tree)
#   ├── templates/     ← canonical (in-tree)
#   └── .env.example   ← synced from repo root

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$REPO_ROOT/src/voronoi/data"

echo "Syncing supplementary files → $DATA_DIR"

# .env.example
if [ -f "$REPO_ROOT/.env.example" ]; then
    cp "$REPO_ROOT/.env.example" "$DATA_DIR/.env.example"
    echo "  ✓ .env.example"
fi

echo "✓ Done. All core content is maintained in-tree under data/."
echo "  $(find "$DATA_DIR" -type f | wc -l | tr -d ' ') total files in data/"
