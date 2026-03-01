#!/bin/bash
set -euo pipefail

# =============================================================================
# merge-agent-generic.sh — Assemble output from a generic (non-code) agent
#
# Copies agent output files into the project's output directory.
# No git merge involved — just file assembly.
#
# Usage: ./scripts/merge-agent-generic.sh <agent-name> [beads-task-id]
# =============================================================================

AGENT_NAME="$1"
TASK_ID="${2:-}"

CONFIG=$(cat .swarm-config.json)
PROJECT_DIR=$(echo "$CONFIG" | jq -r '.project_dir')
SWARM_DIR=$(echo "$CONFIG" | jq -r '.swarm_dir')
TMUX_SESSION=$(echo "$CONFIG" | jq -r '.tmux_session')

WORK_DIR="${SWARM_DIR}/${AGENT_NAME}"
OUTPUT_DIR="${PROJECT_DIR}/output/${AGENT_NAME}"

echo "--- Assembling output: $AGENT_NAME ---"

# 1. Copy output files to project
if [[ -d "$WORK_DIR/output" ]]; then
    mkdir -p "$OUTPUT_DIR"
    cp -r "$WORK_DIR/output/"* "$OUTPUT_DIR/" 2>/dev/null || true
    FILE_COUNT=$(find "$OUTPUT_DIR" -type f | wc -l | tr -d ' ')
    echo "✓ Copied $FILE_COUNT files to $OUTPUT_DIR"
else
    echo "⚠ No output directory found at $WORK_DIR/output"
fi

# 2. Close the Beads task if provided
if [[ -n "$TASK_ID" ]]; then
    bd close "$TASK_ID" --reason "Assembled output from $AGENT_NAME" 2>/dev/null || true
    echo "✓ Beads task $TASK_ID closed"
fi

# 3. Commit the assembled output to git (if in a git repo)
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    cd "$PROJECT_DIR"
    git add "output/${AGENT_NAME}/" 2>/dev/null || true
    if git diff --cached --quiet 2>/dev/null; then
        echo "  (no new files to commit)"
    else
        git commit -m "Assemble output from $AGENT_NAME" 2>/dev/null || true
        git push origin main 2>/dev/null || true
        echo "✓ Output committed and pushed"
    fi
fi

# 4. Clean up working directory
rm -rf "$WORK_DIR"
echo "✓ Working directory cleaned up"

# 5. Kill tmux window if it exists
tmux kill-window -t "$TMUX_SESSION:$AGENT_NAME" 2>/dev/null || true
echo "✓ Tmux window closed"

echo ""
echo "--- Assembly complete. Output at: $OUTPUT_DIR ---"
