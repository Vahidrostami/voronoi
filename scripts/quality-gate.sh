#!/bin/bash
set -euo pipefail

# =============================================================================
# quality-gate.sh — Pluggable validation for agent output
#
# Called by autopilot.sh before merging an agent branch.
# Exit 0 = pass (proceed to merge), Exit 1 = fail (trigger retry).
#
# Usage: ./scripts/quality-gate.sh <branch> <task-id> <worktree-path>
#
# Override by setting --quality-gate in autopilot.sh or by editing this file.
# =============================================================================

BRANCH="$1"
TASK_ID="$2"
WORKTREE="$3"

echo "--- Quality Gate: $BRANCH ---"

PASS=true

# --- Gate 1: Must have commits ---
COMMIT_COUNT=$(git log "main..$BRANCH" --oneline 2>/dev/null | wc -l | tr -d ' ')
if [[ "$COMMIT_COUNT" -eq 0 ]]; then
    echo "  ✗ No commits on branch"
    PASS=false
else
    echo "  ✓ $COMMIT_COUNT commit(s) found"
fi

# --- Gate 2: Beads task must be closed ---
if bd show "$TASK_ID" --json 2>/dev/null | jq -e '.status == "closed"' >/dev/null 2>&1; then
    echo "  ✓ Beads task closed"
else
    echo "  ✗ Beads task not closed"
    PASS=false
fi

# --- Gate 3: No merge conflicts with main ---
MERGE_BASE=$(git merge-base main "$BRANCH" 2>/dev/null || echo "")
if [[ -n "$MERGE_BASE" ]]; then
    if git merge-tree "$MERGE_BASE" main "$BRANCH" >/dev/null 2>&1; then
        echo "  ✓ No merge conflicts"
    else
        echo "  ⚠ Potential merge conflicts detected"
        # Don't fail on this — the merge script handles conflicts
    fi
fi

# --- Gate 4: Run tests if they exist ---
if [[ -d "$WORKTREE" ]]; then
    # Check for Python tests
    if ls "$WORKTREE"/tests/test_*.py 1>/dev/null 2>&1; then
        echo "  Running Python tests..."
        if (cd "$WORKTREE" && python -m pytest tests/ -q --tb=short 2>&1 | tail -5); then
            echo "  ✓ Tests passed"
        else
            echo "  ✗ Tests failed"
            PASS=false
        fi
    # Check for Node tests
    elif [[ -f "$WORKTREE/package.json" ]] && grep -q '"test"' "$WORKTREE/package.json" 2>/dev/null; then
        echo "  Running npm tests..."
        if (cd "$WORKTREE" && npm test --silent 2>&1 | tail -5); then
            echo "  ✓ Tests passed"
        else
            echo "  ✗ Tests failed"
            PASS=false
        fi
    else
        echo "  ⊘ No tests found (skipping)"
    fi
fi

# --- Gate 5: Artifact contract — expected outputs must exist ---
PRODUCES=$(bd show "$TASK_ID" --json 2>/dev/null | jq -r '.notes // ""' | sed -n 's/.*PRODUCES:\(.*\)/\1/p' | head -1 || true)
if [[ -n "$PRODUCES" ]]; then
    echo "  Checking artifact contract (PRODUCES)..."
    IFS=',' read -ra ARTIFACTS <<< "$PRODUCES"
    for artifact in "${ARTIFACTS[@]}"; do
        artifact=$(echo "$artifact" | xargs)  # trim whitespace
        # Check in the worktree first, then in the project root
        if [[ -e "$WORKTREE/$artifact" || -e "$artifact" ]]; then
            echo "    ✓ Found: $artifact"
        else
            echo "    ✗ Missing: $artifact"
            PASS=false
        fi
    done
else
    echo "  ⊘ No artifact contract (PRODUCES not set)"
fi

# --- Gate 6: Custom gate hook (if exists) ---
CUSTOM_GATE=".swarm-quality-gate.sh"
if [[ -x "$CUSTOM_GATE" ]]; then
    echo "  Running custom quality gate..."
    if "$CUSTOM_GATE" "$BRANCH" "$TASK_ID" "$WORKTREE"; then
        echo "  ✓ Custom gate passed"
    else
        echo "  ✗ Custom gate failed"
        PASS=false
    fi
fi

echo ""
if [[ "$PASS" == "true" ]]; then
    echo "  ✅ Quality gate PASSED"
    exit 0
else
    echo "  ❌ Quality gate FAILED"
    exit 1
fi
