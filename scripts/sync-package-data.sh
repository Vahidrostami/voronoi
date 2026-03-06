#!/bin/bash
set -euo pipefail

# Sync framework files into src/voronoi/data/ for pip packaging.
# Run this before `pip install .` or `python -m build`.
# Editable installs (`pip install -e .`) don't need this — the CLI
# auto-detects the repo root.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$REPO_ROOT/src/voronoi/data"

echo "Syncing framework files → $DATA_DIR"

# Clean slate
rm -rf "$DATA_DIR"
mkdir -p "$DATA_DIR"

# Scripts
cp -R "$REPO_ROOT/scripts" "$DATA_DIR/scripts"

# Demos
cp -R "$REPO_ROOT/demos" "$DATA_DIR/demos"

# .github (agents, prompts, skills — skip workflows)
mkdir -p "$DATA_DIR/.github"
for subdir in agents prompts skills; do
    if [ -d "$REPO_ROOT/.github/$subdir" ]; then
        cp -R "$REPO_ROOT/.github/$subdir" "$DATA_DIR/.github/$subdir"
    fi
done

# Top-level framework files
cp "$REPO_ROOT/CLAUDE.md" "$DATA_DIR/CLAUDE.md"
cp "$REPO_ROOT/AGENTS.md" "$DATA_DIR/AGENTS.md"
cp "$REPO_ROOT/.env.example" "$DATA_DIR/.env.example"

echo "✓ Done. $(find "$DATA_DIR" -type f | wc -l | tr -d ' ') files synced."
