#!/bin/bash
set -euo pipefail

PROJECT_DIR=$(pwd)
PROJECT_NAME=$(basename "$PROJECT_DIR")

echo "=== Voronoi: Initializing $PROJECT_NAME ==="

# 1. Check dependencies
# Detect platform for install hints
if [[ "$OSTYPE" == "darwin"* ]]; then
    PKG_HINT="brew install"
else
    PKG_HINT="apt install"  # or your distro's package manager
fi

command -v bd   >/dev/null 2>&1 || { echo "Install beads: $PKG_HINT beads"; exit 1; }
command -v tmux >/dev/null 2>&1 || { echo "Install tmux: $PKG_HINT tmux"; exit 1; }
command -v gh   >/dev/null 2>&1 && echo "✓ GitHub CLI found" || echo "⚠ GitHub CLI (gh) not found — optional, needed for PR workflows"

# Detect agent CLI
if command -v copilot >/dev/null 2>&1; then
    AGENT_CMD="copilot"
else
    echo "⚠ Copilot CLI not found. Install it to dispatch agents."
    AGENT_CMD="copilot"
fi

# 2. Initialize Beads
if [ ! -d ".beads" ]; then
    bd init --quiet
    echo "✓ Beads initialized"
else
    echo "✓ Beads already initialized"
fi

# 3. Ensure CLAUDE.md exists
if [ ! -f "CLAUDE.md" ]; then
    # CLAUDE.md should have been placed by 'voronoi init'; warn if missing
    echo "⚠ CLAUDE.md not found. Run 'voronoi init' first or create it manually."
fi

# 4. Create swarm working directory (parent of worktrees)
SWARM_DIR="../${PROJECT_NAME}-swarm"
mkdir -p "$SWARM_DIR"

# 5. Create .swarm/ directory and investigation journal
mkdir -p .swarm
if [ ! -f ".swarm/journal.md" ]; then
    cat > .swarm/journal.md << 'JOURNAL'
# Investigation Journal

> Maintained by the Synthesizer. Read by the Orchestrator at session start and the Theorist when building causal models.

<!-- Append new cycles below. Do not edit previous entries. -->
JOURNAL
    echo "✓ Investigation journal initialized at .swarm/journal.md"
fi

# 5b. Warn about stale state from prior runs
if [ -f ".swarm/autopilot-state.json" ]; then
    echo "⚠ Found autopilot state from a prior run (.swarm/autopilot-state.json)"
    echo "  This means a previous autopilot session crashed or was interrupted."
    echo "  Use --resume to continue, or delete it to start fresh."
fi

# 6. Write swarm config
cat > .swarm-config.json << EOF
{
  "project_name": "$PROJECT_NAME",
  "project_dir": "$PROJECT_DIR",
  "swarm_dir": "$(cd "$SWARM_DIR" && pwd)",
  "tmux_session": "${PROJECT_NAME}-swarm",
  "max_agents": 4,
  "agent_command": "$AGENT_CMD",
  "agent_flags": "--allow-all",
  "agent_flags_safe": [
    "--disallow-tool", "mcp__curl",
    "--disallow-tool", "mcp__ssh",
    "--disallow-tool", "mcp__sudo"
  ],
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
  "notifications": {
    "telegram": {
      "enabled": false,
      "bot_token": "",
      "chat_id": "",
      "events": ["swarm_start", "wave_dispatch", "merge", "quality_gate_fail", "convergence", "swarm_complete", "agent_timeout", "agent_retry", "swarm_abort", "inbox_command"],
      "mvcha_gateway_url": "",
      "mvcha_api_secret": "",
      "prefer_mvcha": false,
      "bridge_enabled": true
    }
  },
  "created": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "✓ Swarm config written to .swarm-config.json"
echo ""
echo "=== Setup complete ==="
echo ""
echo "To enable Telegram notifications:"
echo "  1. Set bot_token and chat_id in .swarm-config.json → notifications.telegram"
echo "  2. Set enabled: true"
echo "  3. (Optional) Start the bridge: python3 scripts/telegram-bridge.py"
echo ""
echo "Run: copilot then /swarm <your task>"
