#!/bin/bash
set -euo pipefail

# Usage: ./scripts/spawn-agent.sh [--safe] <beads-task-id> <branch-name> <task-description>
#
# Options:
#   --safe    Use granular tool permissions instead of --allow-all.
#             Agents can read/write files, use git, run tests, submit Slurm jobs,
#             but CANNOT: curl, ssh, rm -rf /, sudo, or access network tools.

SAFE_MODE=false
if [[ "${1:-}" == "--safe" ]]; then
    SAFE_MODE=true
    shift
fi

TASK_ID="$1"
BRANCH_NAME="$2"
TASK_DESC="$3"

# Load config
CONFIG=$(cat .swarm-config.json)
PROJECT_DIR=$(echo "$CONFIG" | jq -r '.project_dir')
SWARM_DIR=$(echo "$CONFIG" | jq -r '.swarm_dir')
TMUX_SESSION=$(echo "$CONFIG" | jq -r '.tmux_session')
AGENT_CMD=$(echo "$CONFIG" | jq -r '.agent_command // "copilot"')

# Select permission mode
if [[ "$SAFE_MODE" == "true" ]]; then
    # Build flags from the agent_flags_safe array in config
    AGENT_FLAGS=$(echo "$CONFIG" | jq -r '(.agent_flags_safe // []) | join(" ")')
    if [[ -z "$AGENT_FLAGS" ]]; then
        echo "⚠ No agent_flags_safe in config, falling back to --allow-all"
        AGENT_FLAGS="--allow-all"
    else
        echo "🔒 Safe mode: using granular tool permissions"
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

# 2. Claim the task in Beads
bd update "$TASK_ID" --claim || echo "Warning: claim failed (may already be claimed)"

# 3. Create/attach tmux session
if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux new-session -d -s "$TMUX_SESSION" -c "$WORKTREE_PATH"
    tmux rename-window -t "$TMUX_SESSION" "$BRANCH_NAME"
else
    tmux new-window -t "$TMUX_SESSION" -n "$BRANCH_NAME" -c "$WORKTREE_PATH"
fi

# 4. Build the agent prompt
AGENT_PROMPT=$(cat <<PROMPT
You are a worker agent in a multi-agent swarm.

YOUR TASK (Beads ID: $TASK_ID):
$TASK_DESC

RULES:
1. Work ONLY in this directory: $WORKTREE_PATH
2. Run bd prime for context at start
3. This task is already claimed by you in Beads
4. Commit often with clear messages
5. When done:
   - Run tests
   - bd close $TASK_ID --reason "Completed: [summary of what you built]"
   - git push origin $BRANCH_NAME
   - THEN STOP. Do not continue to other tasks.
6. If you find work outside your scope, file it:
   bd create "Discovered: [description]" -t task -p 2
7. If you are blocked, update Beads:
   bd update $TASK_ID --notes "BLOCKED: [reason]"
PROMPT
)

# 5. Write prompt to file in worktree (avoids shell quoting issues in tmux)
echo "$AGENT_PROMPT" > "$WORKTREE_PATH/.agent-prompt.txt"

# 6. Launch agent CLI in the tmux pane
#    Flags go before -p so -p gets the prompt as its argument value
tmux send-keys -t "$TMUX_SESSION:$BRANCH_NAME" \
    "$AGENT_CMD $AGENT_FLAGS -p \"\$(cat .agent-prompt.txt)\"" Enter

echo "✓ Agent spawned: $BRANCH_NAME (tmux: $TMUX_SESSION)"
