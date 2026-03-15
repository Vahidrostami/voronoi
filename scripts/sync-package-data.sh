#!/bin/bash
set -euo pipefail

# Sync framework files into src/voronoi/data/ for pip packaging.
# Run this before `pip install .` or `python -m build`.
# Editable installs (`pip install -e .`) don't need this — the CLI
# auto-detects the repo root.
#
# Layout after sync:
#   src/voronoi/data/
#   ├── agents/        ← from .github/agents/
#   ├── skills/        ← from .github/skills/
#   ├── prompts/       ← from .github/prompts/
#   ├── scripts/       ← from scripts/ (runtime only)
#   ├── demos/         ← from demos/
#   ├── templates/     ← CLAUDE.md + AGENTS.md for investigation workspaces
#   └── .env.example

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$REPO_ROOT/src/voronoi/data"

echo "Syncing framework files → $DATA_DIR"

# Preserve templates (they're maintained in-tree, not generated)
TEMPLATES_BACKUP=""
if [ -d "$DATA_DIR/templates" ]; then
    TEMPLATES_BACKUP="$(mktemp -d)"
    cp -R "$DATA_DIR/templates" "$TEMPLATES_BACKUP/"
fi

# Clean slate (except templates)
rm -rf "$DATA_DIR/agents" "$DATA_DIR/skills" "$DATA_DIR/prompts" \
       "$DATA_DIR/scripts" "$DATA_DIR/demos" "$DATA_DIR/.env.example"
mkdir -p "$DATA_DIR"

# Restore templates
if [ -n "$TEMPLATES_BACKUP" ] && [ -d "$TEMPLATES_BACKUP/templates" ]; then
    cp -R "$TEMPLATES_BACKUP/templates" "$DATA_DIR/templates"
    rm -rf "$TEMPLATES_BACKUP"
fi

# Ensure templates exist
mkdir -p "$DATA_DIR/templates"

# Agent roles, skills, prompts (from .github/)
for subdir in agents prompts skills; do
    if [ -d "$REPO_ROOT/.github/$subdir" ]; then
        cp -R "$REPO_ROOT/.github/$subdir" "$DATA_DIR/$subdir"
    fi
done

# Runtime scripts
cp -R "$REPO_ROOT/scripts" "$DATA_DIR/scripts"

# Demos
cp -R "$REPO_ROOT/demos" "$DATA_DIR/demos"

# .env.example
if [ -f "$REPO_ROOT/.env.example" ]; then
    cp "$REPO_ROOT/.env.example" "$DATA_DIR/.env.example"
fi

echo "✓ Done. $(find "$DATA_DIR" -type f | wc -l | tr -d ' ') files synced."
echo "  Layout:"
echo "    agents/    ← .github/agents/ ($(ls "$DATA_DIR/agents" 2>/dev/null | wc -l | tr -d ' ') files)"
echo "    skills/    ← .github/skills/ ($(ls "$DATA_DIR/skills" 2>/dev/null | wc -l | tr -d ' ') dirs)"
echo "    prompts/   ← .github/prompts/ ($(ls "$DATA_DIR/prompts" 2>/dev/null | wc -l | tr -d ' ') files)"
echo "    scripts/   ← scripts/"
echo "    demos/     ← demos/"
echo "    templates/ ← runtime CLAUDE.md + AGENTS.md"
