#!/bin/bash
set -euo pipefail

# Usage: ./scripts/spawn-agent.sh <beads-task-id> <branch-name> <task-description>
TASK_ID="$1"
BRANCH_NAME="$2"
TASK_DESC="$3"

# Load config
CONFIG=$(cat .swarm-config.json)
PROJECT_DIR=$(echo "$CONFIG" | jq -r '.project_dir')
SWARM_DIR=$(echo "$CONFIG" | jq -r '.swarm_dir')
TMUX_SESSION=$(echo "$CONFIG" | jq -r '.tmux_session')

WORKTREE_PATH="${SWARM_DIR}/${BRANCH_NAME}"

echo "--- Spawning agent: $BRANCH_NAME ---"

# 1. Create worktree on a new branch
cd "$PROJECT_DIR"
git worktree add "$WORKTREE_PATH" -b "$BRANCH_NAME" 2>/dev/null || {
    echo "Worktree or branch already exists, reusing..."
    git worktree add "$WORKTREE_PATH" "$BRANCH_NAME" 2>/dev/null || true
}

# 2. Claim the task in Beads
bd update "$TASK_ID" --claim

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

# 5. Launch Claude Code in the tmux pane
tmux send-keys -t "$TMUX_SESSION:$BRANCH_NAME" \
    "claude -p '$AGENT_PROMPT'" Enter

echo "✓ Agent spawned: $BRANCH_NAME (tmux: $TMUX_SESSION)"
