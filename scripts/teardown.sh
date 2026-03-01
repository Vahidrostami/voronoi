#!/bin/bash
set -euo pipefail

CONFIG=$(cat .swarm-config.json)
PROJECT_DIR=$(echo "$CONFIG" | jq -r '.project_dir')
SWARM_DIR=$(echo "$CONFIG" | jq -r '.swarm_dir')
TMUX_SESSION=$(echo "$CONFIG" | jq -r '.tmux_session')

cd "$PROJECT_DIR"

echo "=== TEARDOWN: Removing all agent worktrees and sessions ==="
echo ""

# 1. Kill tmux session
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null && echo "✓ Tmux session killed" || echo "  No tmux session found"

# 2. Remove all worktrees
for worktree in "$SWARM_DIR"/agent-*; do
    [ -d "$worktree" ] || continue
    BRANCH=$(basename "$worktree")
    git worktree remove "$worktree" --force 2>/dev/null || rm -rf "$worktree"
    echo "✓ Removed worktree: $BRANCH"
done

# 3. Clean up branches (only agent-* branches)
for branch in $(git branch --list "agent-*" 2>/dev/null); do
    branch=$(echo "$branch" | tr -d ' *')
    git branch -D "$branch" 2>/dev/null || true
    echo "✓ Deleted branch: $branch"
done

# 4. Prune worktree metadata
git worktree prune
echo ""
echo "=== Teardown complete. Beads data is preserved. ==="
