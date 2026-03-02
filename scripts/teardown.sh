#!/bin/bash
set -euo pipefail

CONFIG=$(cat .swarm-config.json)
PROJECT_DIR=$(echo "$CONFIG" | jq -r '.project_dir')
SWARM_DIR=$(echo "$CONFIG" | jq -r '.swarm_dir')
TMUX_SESSION=$(echo "$CONFIG" | jq -r '.tmux_session')

# Safety flag: --force to clean even unmerged branches (dangerous!)
FORCE=false
if [[ "${1:-}" == "--force" ]]; then
    FORCE=true
    echo "⚠ FORCE MODE: Will destroy ALL agent branches including unmerged ones"
fi

cd "$PROJECT_DIR"

echo "=== TEARDOWN: Removing agent worktrees and sessions ==="
echo ""

# 1. Kill tmux session
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null && echo "✓ Tmux session killed" || echo "  No tmux session found"

# 2. Remove worktrees — but preserve unmerged ones unless --force
for worktree in "$SWARM_DIR"/agent-*; do
    [ -d "$worktree" ] || continue
    BRANCH=$(basename "$worktree")

    if [[ "$FORCE" == "true" ]]; then
        # Force mode: destroy everything
        git worktree remove "$worktree" --force 2>/dev/null || rm -rf "$worktree"
        echo "✓ Removed worktree: $BRANCH (forced)"
    elif git branch --merged main 2>/dev/null | grep -q "$BRANCH"; then
        # Safe mode: only remove if merged to main
        git worktree remove "$worktree" --force 2>/dev/null || rm -rf "$worktree"
        echo "✓ Removed merged worktree: $BRANCH"
    else
        # Push to remote first so code isn't lost
        (cd "$worktree" && git add -A && git commit -m "teardown: preserve unfinished work" 2>/dev/null && git push origin "$BRANCH" 2>/dev/null) || true
        echo "⚠ Preserved unmerged worktree: $BRANCH (branch pushed to remote)"
    fi
done

# 3. Clean up branches (only merged or forced)
for branch in $(git branch --list "agent-*" 2>/dev/null); do
    branch=$(echo "$branch" | tr -d ' *')
    if [[ "$FORCE" == "true" ]]; then
        git branch -D "$branch" 2>/dev/null || true
        echo "✓ Deleted local branch: $branch (forced)"
    elif git branch --merged main 2>/dev/null | grep -q "$branch"; then
        git branch -d "$branch" 2>/dev/null || true
        echo "✓ Deleted merged local branch: $branch"
    else
        echo "⚠ Preserved unmerged local branch: $branch"
    fi
done

# 4. Clean up remote agent branches (only merged or forced)
echo ""
echo "Cleaning remote agent branches..."
for remote_branch in $(git branch -r --list 'origin/agent-*' 2>/dev/null); do
    local_name="${remote_branch#origin/}"
    if [[ "$FORCE" == "true" ]]; then
        git push origin --delete "$local_name" 2>/dev/null || true
        echo "✓ Deleted remote branch: $local_name (forced)"
    elif git branch --merged main 2>/dev/null | grep -q "$local_name"; then
        git push origin --delete "$local_name" 2>/dev/null || true
        echo "✓ Deleted merged remote branch: $local_name"
    else
        echo "⚠ Preserved unmerged remote branch: $local_name"
    fi
done
git remote prune origin 2>/dev/null || true

# 5. Prune worktree metadata
git worktree prune
echo ""

# 6. Clean up state file if --force
if [[ "$FORCE" == "true" ]]; then
    rm -f "${PROJECT_DIR}/.swarm/autopilot-state.json" 2>/dev/null || true
    echo "✓ Removed autopilot state file"
fi

echo "=== Teardown complete. Beads data is preserved. ==="
if [[ "$FORCE" != "true" ]]; then
    echo "  Unmerged branches are preserved. Run with --force to destroy everything."
fi
