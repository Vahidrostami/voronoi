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
command -v docker >/dev/null 2>&1 && echo "✓ Docker found" || echo "⚠ Docker not found — agent code will run on host (no sandbox)"

# Load .env if present (before any checks that depend on env vars)
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
    echo "✓ Loaded .env"
fi

# Check GitHub auth (needed for cloning repos and publishing results)
if [[ -n "${GH_TOKEN:-}" ]]; then
    echo "✓ GH_TOKEN set"
elif command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    echo "✓ GitHub authenticated via gh CLI"
else
    echo "⚠ No GitHub auth found. Set GH_TOKEN in .env or run: gh auth login"
    echo "  Needed for: cloning repos, publishing results to voronoi-lab org"
fi

# Detect agent CLI (env var overrides auto-detection)
if [[ -n "${VORONOI_AGENT_COMMAND:-}" ]]; then
    AGENT_CMD="$VORONOI_AGENT_COMMAND"
    echo "✓ Agent CLI from env: $AGENT_CMD"
elif command -v copilot >/dev/null 2>&1; then
    AGENT_CMD="copilot"
elif command -v claude >/dev/null 2>&1; then
    AGENT_CMD="claude"
else
    echo "⚠ No agent CLI found (copilot/claude). Install one to dispatch agents."
    AGENT_CMD="copilot"
fi

# 2. Ensure at least one git commit exists (git worktree requires it)
if ! git rev-parse HEAD >/dev/null 2>&1; then
    echo "Creating initial commit (required for agent worktrees)..."
    git add -A 2>/dev/null || true
    git commit --allow-empty -m "voronoi: initial commit" >/dev/null 2>&1
    echo "✓ Initial commit created"
fi

# 3. Initialize Beads
if [ ! -d ".beads" ]; then
    echo "Y" | timeout 30 bd init --quiet 2>/dev/null || true
    if [ -d ".beads" ]; then
        echo "✓ Beads initialized"
    else
        echo "⚠ Beads init failed or timed out (non-fatal)"
    fi
else
    echo "✓ Beads already initialized"
fi

# 4. Ensure CLAUDE.md exists
if [ ! -f "CLAUDE.md" ]; then
    # CLAUDE.md should have been placed by 'voronoi init'; warn if missing
    echo "⚠ CLAUDE.md not found. Run 'voronoi init' first or create it manually."
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

# 6b. Warn about stale state from prior runs
if [ -f ".swarm/autopilot-state.json" ]; then
    echo "⚠ Found autopilot state from a prior run (.swarm/autopilot-state.json)"
    echo "  This means a previous autopilot session crashed or was interrupted."
    echo "  Use --resume to continue, or delete it to start fresh."
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
      "events": ["swarm_start", "wave_dispatch", "merge", "quality_gate_fail", "convergence", "swarm_complete", "agent_timeout", "agent_retry", "swarm_abort", "inbox_command"],
      "prefer_mvcha": false,
      "bridge_enabled": true
    }
  },
  "created": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "✓ Swarm config written to .swarm-config.json"

# 8. Auto-start Telegram bridge if credentials are configured
_tg_bot_token="${VORONOI_TG_BOT_TOKEN:-}"

TMUX_SESSION="${PROJECT_NAME}-swarm"

if [[ -n "$_tg_bot_token" ]]; then
    echo ""
    echo "✓ Telegram bot token found"
    # Ensure tmux session exists
    if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
        tmux new-session -d -s "$TMUX_SESSION" -n "orchestrator"
    fi
    # Kill any existing bridge pane/window to avoid duplicates
    tmux kill-window -t "${TMUX_SESSION}:telegram" 2>/dev/null || true
    # Start bridge in a dedicated tmux window
    tmux new-window -t "$TMUX_SESSION" -n "telegram" \
        "cd '$PROJECT_DIR' && python3 scripts/telegram-bridge.py; read -p 'Bridge exited. Press enter to close.'"
    echo "✓ Telegram bridge started in tmux window '${TMUX_SESSION}:telegram'"
else
    echo ""
    echo "To enable Telegram notifications:"
    echo "  1. Copy .env.example to .env and fill in your credentials"
    echo "  2. Re-run swarm-init or: voronoi server start"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Run: $AGENT_CMD then /swarm <your task>"
