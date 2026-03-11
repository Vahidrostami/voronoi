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

# 0. Safety: push agent branch to remote first (code survives even if merge fails)
echo "  Pushing $BRANCH_NAME to remote (safety net)..."
if [[ -d "$WORKTREE_PATH" ]]; then
    (cd "$WORKTREE_PATH" && git push origin "$BRANCH_NAME" 2>/dev/null) || \
        git push origin "$BRANCH_NAME" 2>/dev/null || \
        echo "  ⚠ Could not push $BRANCH_NAME to remote (may already be there)"
else
    git push origin "$BRANCH_NAME" 2>/dev/null || \
        echo "  ⚠ Could not push $BRANCH_NAME to remote (may already be there)"
fi

# Load Telegram notifications (fire-and-forget, never fails the merge)
source "${PROJECT_DIR}/scripts/notify-telegram.sh" 2>/dev/null || true

# =========================================================================
# Pre-merge artifact validation (PRODUCES checks)
# =========================================================================
if [ -n "$TASK_ID" ]; then
    TASK_JSON=$(bd show "$TASK_ID" --json 2>/dev/null || echo "{}")
    PRODUCES_LIST=$(echo "$TASK_JSON" | python3 -c "
import sys, json, re
try:
    data = json.load(sys.stdin)
    notes = data.get('notes', '')
    for line in notes.split('\n'):
        m = re.match(r'PRODUCES:\s*(.+)', line.strip())
        if m:
            for f in m.group(1).split(','):
                f = f.strip()
                if f:
                    print(f)
except Exception:
    pass
" 2>/dev/null || true)

    if [ -n "$PRODUCES_LIST" ]; then
        MISSING_PRODUCES=""
        while IFS= read -r prod; do
            [ -z "$prod" ] && continue
            # Check in worktree first, then project root
            if [ ! -e "${WORKTREE_PATH}/${prod}" ] && [ ! -e "${PROJECT_DIR}/${prod}" ]; then
                MISSING_PRODUCES="${MISSING_PRODUCES}  - ${prod}\n"
            fi
        done <<< "$PRODUCES_LIST"
        if [ -n "$MISSING_PRODUCES" ]; then
            echo "✗ Pre-merge FAILED: Missing PRODUCES artifacts:"
            echo -e "$MISSING_PRODUCES"
            echo "  Branch $BRANCH_NAME safely on remote. Fix and retry."
            bd update "$TASK_ID" --notes "MERGE_BLOCKED: Missing output artifacts — merge deferred" 2>/dev/null || true
            notify_telegram "merge_blocked" "⚠️ Merge blocked: \`${BRANCH_NAME}\` — missing PRODUCES artifacts" 2>/dev/null || true
            exit 1
        fi
        echo "✓ Pre-merge: All PRODUCES artifacts present"
    fi

    # Run figure-lint if task produces LaTeX or figure files
    HAS_LATEX=$(echo "$PRODUCES_LIST" | grep -i '\.tex\|\.pdf\|figures/' || true)
    if [ -n "$HAS_LATEX" ]; then
        if [ -x "${PROJECT_DIR}/scripts/figure-lint.sh" ]; then
            echo "  Running figure-lint check..."
            SEARCH_DIR="$WORKTREE_PATH"
            [ ! -d "$SEARCH_DIR" ] && SEARCH_DIR="$PROJECT_DIR"
            if ! "${PROJECT_DIR}/scripts/figure-lint.sh" "$SEARCH_DIR"; then
                echo "⚠ Figure-lint found missing figures (non-blocking warning)"
                bd update "$TASK_ID" --notes "WARNING: figure-lint detected missing figures" 2>/dev/null || true
                notify_telegram "figure_warning" "⚠️ \`${BRANCH_NAME}\`: figure-lint found missing figures" 2>/dev/null || true
            else
                echo "✓ Pre-merge: Figure-lint passed"
            fi
        fi
    fi

    echo "✓ Pre-merge validation complete"
fi

# 1. Ensure we're on main
git checkout main
git pull --rebase

# 2. Merge the agent branch
if git merge "$BRANCH_NAME" --no-ff -m "Merge $BRANCH_NAME: agent work complete"; then
    echo "✓ Merged successfully"
else
    echo "✗ Merge conflict detected. Branch $BRANCH_NAME is safely on remote."
    echo "  Resolve manually: git merge $BRANCH_NAME"
    notify_telegram "merge_conflict" "⚠️ Merge conflict: \`${BRANCH_NAME}\` — needs manual resolve" 2>/dev/null || true
    exit 1
fi

# 3. Push main
git push origin main
echo "✓ Pushed to main"

# 4. Close the Beads task if provided (and not already closed)
if [ -n "$TASK_ID" ]; then
    if bd show "$TASK_ID" --json 2>/dev/null | jq -e '.status == "closed"' >/dev/null 2>&1; then
        echo "✓ Beads task $TASK_ID already closed"
    else
        bd close "$TASK_ID" --reason "Merged to main from $BRANCH_NAME"
        echo "✓ Beads task $TASK_ID closed"
    fi
fi

# 5. Notify Telegram: merge success with progress count
TOTAL=$(bd list --json 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
CLOSED=$(bd list --status closed --json 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
notify_telegram "merge" "✅ Merged \`${BRANCH_NAME}\` · ${CLOSED}/${TOTAL} tasks done" 2>/dev/null || true

# 6. Check for scientific findings and notify immediately
if [ -n "$TASK_ID" ]; then
    FINDING_MSG=$(bd show "$TASK_ID" --json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    title = data.get('title', '')
    notes = data.get('notes', '')
    # Look for TYPE:finding in notes
    if 'TYPE:finding' not in notes and 'FINDING' not in title.upper():
        sys.exit(0)
    parts = []
    for line in notes.split('\\n'):
        line = line.strip()
        if not line:
            continue
        for key in ('EFFECT_SIZE', 'CI_95', 'N:', 'STAT_TEST', 'P:', 'VALENCE', 'CONFIDENCE'):
            if key in line:
                parts.append(line)
                break
    finding = title
    if parts:
        finding += '\\n' + '\\n'.join(parts[:4])  # max 4 lines of stats
    print(finding)
except Exception:
    pass
" 2>/dev/null || true)
    if [ -n "$FINDING_MSG" ]; then
        notify_telegram "finding" "🧬 *Finding* from \`${BRANCH_NAME}\`:\n${FINDING_MSG}" 2>/dev/null || true
        echo "✓ Finding sent to Telegram"
    fi
fi

# 7. Clean up worktree (code is safely on main now)
git worktree remove "$WORKTREE_PATH" 2>/dev/null || rm -rf "$WORKTREE_PATH" 2>/dev/null || true
git branch -d "$BRANCH_NAME" 2>/dev/null || true
# Clean remote branch too
git push origin --delete "$BRANCH_NAME" 2>/dev/null || true
echo "✓ Worktree and branch cleaned up"

# 8. Kill tmux window if it exists
tmux kill-window -t "$TMUX_SESSION:$BRANCH_NAME" 2>/dev/null || true
echo "✓ Tmux window closed"

echo ""
echo "--- Merge complete. Run 'bd ready' to see newly unblocked tasks. ---"
