#!/bin/bash
set -euo pipefail

# =============================================================================
# spawn-agent.sh — Git worktree + tmux plumbing for agent spawning
#
# Creates a worktree on a new branch, opens a tmux window, and launches the
# agent CLI with a prompt file. The ORCHESTRATOR writes the prompt — this
# script is pure infrastructure plumbing.
#
# Usage: ./scripts/spawn-agent.sh [--safe] <task-id> <branch-name> [prompt-file]
#
# If prompt-file is provided, it's copied into the worktree as .agent-prompt.txt.
# If omitted, the orchestrator must have already written .agent-prompt.txt
# into the worktree path.
# =============================================================================

SAFE_MODE=false
if [[ "${1:-}" == "--safe" ]]; then
    SAFE_MODE=true
    shift
fi

TASK_ID="$1"
BRANCH_NAME="$2"
PROMPT_FILE="${3:-}"

# Load config
CONFIG=$(cat .swarm-config.json)
PROJECT_DIR=$(echo "$CONFIG" | jq -r '.project_dir')
SWARM_DIR=$(echo "$CONFIG" | jq -r '.swarm_dir')
TMUX_SESSION=$(echo "$CONFIG" | jq -r '.tmux_session')
AGENT_CMD=$(echo "$CONFIG" | jq -r '.agent_command // "copilot"')

# Select permission mode
if [[ "$SAFE_MODE" == "true" ]]; then
    AGENT_FLAGS=$(echo "$CONFIG" | jq -r '(.agent_flags_safe // []) | join(" ")')
    if [[ -z "$AGENT_FLAGS" ]]; then
        echo "⚠ No agent_flags_safe in config, falling back to --allow-all"
        AGENT_FLAGS="--allow-all"
    fi
else
    AGENT_FLAGS=$(echo "$CONFIG" | jq -r '.agent_flags // "--allow-all"')
fi

# Pre-flight: verify agent CLI exists
AGENT_BIN="${AGENT_CMD%% *}"
if ! command -v "$AGENT_BIN" >/dev/null 2>&1; then
    echo "✗ Agent CLI not found: $AGENT_BIN"
    echo "  Install it or update agent_command in .swarm-config.json"
    exit 1
fi

WORKTREE_PATH="${SWARM_DIR}/${BRANCH_NAME}"

echo "--- Spawning agent: $BRANCH_NAME ---"

# 1. Create worktree on a new branch
cd "$PROJECT_DIR"
git worktree add "$WORKTREE_PATH" -b "$BRANCH_NAME" 2>/dev/null || {
    echo "Worktree or branch already exists, reusing..."
    git worktree add "$WORKTREE_PATH" "$BRANCH_NAME" 2>/dev/null || true
}

if [[ ! -d "$WORKTREE_PATH" ]]; then
    echo "✗ Failed to create worktree at $WORKTREE_PATH"
    echo "  This usually means the git repo has no commits yet."
    echo "  Fix: git add -A && git commit -m 'initial commit'"
    exit 1
fi

# 2. Claim the task in Beads
bd update "$TASK_ID" --claim 2>/dev/null || echo "Warning: claim failed (may already be claimed)"

# 3. Copy prompt file into worktree if provided
if [[ -n "$PROMPT_FILE" && -f "$PROMPT_FILE" ]]; then
    cp "$PROMPT_FILE" "$WORKTREE_PATH/.agent-prompt.txt"
fi

# 4. Create/attach tmux session
if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux new-session -d -s "$TMUX_SESSION" -c "$WORKTREE_PATH"
    tmux rename-window -t "$TMUX_SESSION" "$BRANCH_NAME"
else
    if tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$BRANCH_NAME"; then
        echo "⚠ tmux window '$BRANCH_NAME' already exists, reusing"
    else
        tmux new-window -t "$TMUX_SESSION" -n "$BRANCH_NAME" -c "$WORKTREE_PATH"
    fi
fi

# 5. Launch agent CLI in the tmux pane
if [[ -f "$WORKTREE_PATH/.agent-prompt.txt" ]]; then
    tmux send-keys -t "$TMUX_SESSION:$BRANCH_NAME" \
        "cd \"$WORKTREE_PATH\" && $AGENT_CMD $AGENT_FLAGS -p \"\$(cat .agent-prompt.txt)\"" Enter
else
    echo "⚠ No prompt file found — agent will start in interactive mode"
    tmux send-keys -t "$TMUX_SESSION:$BRANCH_NAME" \
        "cd \"$WORKTREE_PATH\" && $AGENT_CMD $AGENT_FLAGS" Enter
fi

echo "✓ Agent spawned: $BRANCH_NAME (tmux: $TMUX_SESSION)"

# 6. Notify Telegram (fire-and-forget)
source "${PROJECT_DIR}/scripts/notify-telegram.sh" 2>/dev/null || true
notify_telegram "agent_spawn" "⚡ Agent spawned: \`${BRANCH_NAME}\` → task ${TASK_ID}" 2>/dev/null || true
