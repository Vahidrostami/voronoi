#!/bin/bash
set -euo pipefail

# Usage: ./scripts/merge-agent.sh <branch-name> [beads-task-id]
BRANCH_NAME="$1"
TASK_ID="${2:-}"

CONFIG=$(cat .swarm-config.json)
PROJECT_DIR=$(echo "$CONFIG" | jq -r '.project_dir')
SWARM_DIR=$(echo "$CONFIG" | jq -r '.swarm_dir')
TMUX_SESSION=$(echo "$CONFIG" | jq -r '.tmux_session')

WORKTREE_PATH="${SWARM_DIR}/${BRANCH_NAME}"

cd "$PROJECT_DIR"

echo "--- Merging agent: $BRANCH_NAME ---"

# 1. Ensure we're on main
git checkout main
git pull --rebase

# 2. Merge the agent branch
if git merge "$BRANCH_NAME" --no-ff -m "Merge $BRANCH_NAME: agent work complete"; then
    echo "✓ Merged successfully"
else
    echo "✗ Merge conflict detected. Resolve manually, then re-run."
    exit 1
fi

# 3. Push main
git push origin main
echo "✓ Pushed to main"

# 4. Close the Beads task if provided
if [ -n "$TASK_ID" ]; then
    bd close "$TASK_ID" --reason "Merged to main from $BRANCH_NAME"
    echo "✓ Beads task $TASK_ID closed"
fi

# 5. Clean up worktree
git worktree remove "$WORKTREE_PATH" 2>/dev/null || true
git branch -d "$BRANCH_NAME" 2>/dev/null || true
echo "✓ Worktree and branch cleaned up"

# 6. Kill tmux window if it exists
tmux kill-window -t "$TMUX_SESSION:$BRANCH_NAME" 2>/dev/null || true
echo "✓ Tmux window closed"

echo ""
echo "--- Merge complete. Run 'bd ready' to see newly unblocked tasks. ---"
