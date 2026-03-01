#!/bin/bash
set -euo pipefail

CONFIG=$(cat .swarm-config.json)
PROJECT_DIR=$(echo "$CONFIG" | jq -r '.project_dir')
PROJECT_NAME=$(echo "$CONFIG" | jq -r '.project_name')
SWARM_DIR=$(echo "$CONFIG" | jq -r '.swarm_dir')

cd "$PROJECT_DIR"

echo "=============================================="
echo " AGENT SWARM STANDUP — $(date '+%Y-%m-%d %H:%M')"
echo " Project: $PROJECT_NAME"
echo "=============================================="
echo ""

# 1. Overall Beads status
echo "--- TASK SUMMARY ---"
echo ""
echo "Open tasks:"
bd list --status open --json 2>/dev/null | jq -r '.[] | "  [\(.id)] P\(.priority) \(.title)"' 2>/dev/null || bd list --status open 2>/dev/null || echo "  (none)"
echo ""
echo "In progress:"
bd list --status in_progress --json 2>/dev/null | jq -r '.[] | "  [\(.id)] \(.assignee // "unassigned") — \(.title)"' 2>/dev/null || bd list --status in_progress 2>/dev/null || echo "  (none)"
echo ""
echo "Ready (unblocked):"
bd ready 2>/dev/null || echo "  (none or bd ready not available)"
echo ""
echo "Recently closed (24h):"
bd list --status closed --json 2>/dev/null | jq -r '.[] | "  [\(.id)] \(.title)"' 2>/dev/null || bd list --status closed 2>/dev/null || echo "  (none)"
echo ""

# 2. Per-agent branch activity
echo "--- AGENT BRANCHES ---"
echo ""
for worktree in "$SWARM_DIR"/agent-*; do
    [ -d "$worktree" ] || continue
    BRANCH=$(basename "$worktree")
    echo "Agent: $BRANCH"

    # Recent commits
    COMMITS=$(git log "main..$BRANCH" --oneline 2>/dev/null | head -5)
    if [ -n "$COMMITS" ]; then
        echo "  Commits:"
        echo "$COMMITS" | sed 's/^/    /'
    else
        echo "  Commits: (none)"
    fi

    # Files changed
    STAT=$(git diff "main..$BRANCH" --stat 2>/dev/null | tail -1)
    echo "  Changes: ${STAT:-none}"

    # Last commit time
    LAST=$(git log "$BRANCH" -1 --format="%ar" 2>/dev/null)
    echo "  Last activity: ${LAST:-unknown}"
    echo ""
done

# 3. Conflict detection
echo "--- CONFLICT CHECK ---"
BRANCHES=$(git worktree list --porcelain | grep "branch refs/heads/agent" | sed 's|branch refs/heads/||')
CONFLICT_FOUND=false
for b1 in $BRANCHES; do
    for b2 in $BRANCHES; do
        [ "$b1" \< "$b2" ] || continue
        if ! git merge-tree $(git merge-base "$b1" "$b2") "$b1" "$b2" >/dev/null 2>&1; then
            echo "  ⚠ Potential conflict: $b1 ↔ $b2"
            CONFLICT_FOUND=true
        fi
    done
done
$CONFLICT_FOUND || echo "  No conflicts detected"
echo ""

echo "--- RECOMMENDATIONS ---"
echo ""
echo "Run /merge to merge completed branches."
echo "Run /swarm to plan and dispatch next tasks."
echo "=============================================="
