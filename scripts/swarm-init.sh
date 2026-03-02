#!/bin/bash
set -euo pipefail

PROJECT_DIR=$(pwd)
PROJECT_NAME=$(basename "$PROJECT_DIR")

echo "=== Agent Swarm: Initializing $PROJECT_NAME ==="

# 1. Check dependencies
command -v bd   >/dev/null 2>&1 || { echo "Install beads: brew install beads"; exit 1; }
command -v tmux >/dev/null 2>&1 || { echo "Install tmux: brew install tmux"; exit 1; }
command -v gh   >/dev/null 2>&1 || { echo "Install GitHub CLI: brew install gh"; exit 1; }

# Detect agent CLI: prefer copilot, fall back to claude
if command -v copilot >/dev/null 2>&1; then
    AGENT_CMD="copilot"
elif command -v claude >/dev/null 2>&1; then
    AGENT_CMD="claude"
else
    echo "⚠ No agent CLI found (copilot or claude). Install one to dispatch agents."
    AGENT_CMD="copilot"
fi

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

# 6. Create .swarm/ directory and investigation journal
mkdir -p .swarm
if [ ! -f ".swarm/journal.md" ]; then
    cat > .swarm/journal.md << 'JOURNAL'
# Investigation Journal

> Maintained by the Synthesizer. Read by the Orchestrator at session start and the Theorist when building causal models.

<!-- Append new cycles below. Do not edit previous entries. -->
JOURNAL
    echo "✓ Investigation journal initialized at .swarm/journal.md"
fi

# 7. Write swarm config
cat > .swarm-config.json << EOF
{
  "project_name": "$PROJECT_NAME",
  "project_dir": "$PROJECT_DIR",
  "swarm_dir": "$(cd "$SWARM_DIR" && pwd)",
  "tmux_session": "${PROJECT_NAME}-swarm",
  "max_agents": 4,
  "agent_command": "$AGENT_CMD",
  "agent_flags": "--allow-all",
  "rigor": {
    "default": "auto",
    "serendipity_budget": 0.15,
    "replication_threshold": 0.7,
    "paradigm_stress_threshold": 3,
    "bias_alert_ratio": 0.8,
    "bias_alert_min_sample": 5,
    "max_investigation_cycles": 20,
    "require_pre_registration": "scientific",
    "require_methodologist": "scientific",
    "require_statistician": "analytical",
    "require_adversarial_review": "scientific"
  },
  "created": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "✓ Swarm config written to .swarm-config.json"
echo ""
echo "=== Setup complete. Run: claude then /swarm <your task> ==="
