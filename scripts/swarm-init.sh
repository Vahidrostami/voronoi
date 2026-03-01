#!/bin/bash
set -euo pipefail

PROJECT_DIR=$(pwd)
PROJECT_NAME=$(basename "$PROJECT_DIR")

echo "=== Agent Swarm: Initializing $PROJECT_NAME ==="

# 1. Check dependencies
command -v bd   >/dev/null 2>&1 || { echo "Install beads: brew install beads"; exit 1; }
command -v tmux >/dev/null 2>&1 || { echo "Install tmux: brew install tmux"; exit 1; }
command -v gh   >/dev/null 2>&1 || { echo "Install GitHub CLI: brew install gh"; exit 1; }

# 2. Initialize Beads
if [ ! -d ".beads" ]; then
    bd init --quiet
    echo "✓ Beads initialized"
else
    echo "✓ Beads already initialized"
fi

# 3. Set up Claude Code integration
bd setup claude 2>/dev/null || echo "⚠ Claude Code hooks: set up manually if needed"

# 4. Ensure CLAUDE.md exists
if [ ! -f "CLAUDE.md" ]; then
    cp templates/claude-md-template.md CLAUDE.md 2>/dev/null || echo "⚠ Create CLAUDE.md manually"
fi

# 5. Create swarm working directory (parent of worktrees)
SWARM_DIR="../${PROJECT_NAME}-swarm"
mkdir -p "$SWARM_DIR"

# 6. Write swarm config
cat > .swarm-config.json << EOF
{
  "project_name": "$PROJECT_NAME",
  "project_dir": "$PROJECT_DIR",
  "swarm_dir": "$(realpath "$SWARM_DIR")",
  "tmux_session": "${PROJECT_NAME}-swarm",
  "max_agents": 4,
  "created": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "✓ Swarm config written to .swarm-config.json"
echo ""
echo "=== Setup complete. Run: claude then /swarm <your task> ==="
