#!/bin/bash
set -euo pipefail

# =============================================================================
# spawn-agent-generic.sh — Spawn agent for non-code (generic/research) domains
#
# Uses plain directories instead of git worktrees. Agents write output files
# to their assigned directory. No git branching involved.
#
# Usage: ./scripts/spawn-agent-generic.sh <beads-task-id> <agent-name> <task-description>
# =============================================================================

TASK_ID="$1"
AGENT_NAME="$2"
TASK_DESC="$3"

CONFIG=$(cat .swarm-config.json)
PROJECT_DIR=$(echo "$CONFIG" | jq -r '.project_dir')
SWARM_DIR=$(echo "$CONFIG" | jq -r '.swarm_dir')
TMUX_SESSION=$(echo "$CONFIG" | jq -r '.tmux_session')
AGENT_CMD=$(echo "$CONFIG" | jq -r '.agent_command // "copilot"')
AGENT_FLAGS=$(echo "$CONFIG" | jq -r '.agent_flags // "--allow-all"')

# Pre-flight: verify agent CLI exists
AGENT_BIN="${AGENT_CMD%% *}"
if ! command -v "$AGENT_BIN" >/dev/null 2>&1; then
    echo "✗ Agent CLI not found: $AGENT_BIN"
    exit 1
fi

WORK_DIR="${SWARM_DIR}/${AGENT_NAME}"

echo "--- Spawning generic agent: $AGENT_NAME ---"

# 1. Create working directory (plain directory, not git worktree)
mkdir -p "$WORK_DIR"

# 2. Copy shared context files (if any exist in project)
for f in "$PROJECT_DIR"/.swarm-config.json "$PROJECT_DIR"/CLAUDE.md "$PROJECT_DIR"/AGENTS.md; do
    [[ -f "$f" ]] && cp "$f" "$WORK_DIR/" 2>/dev/null || true
done

# 3. Create output directory for this agent
mkdir -p "$WORK_DIR/output"

# 4. Claim the task in Beads
bd update "$TASK_ID" --claim

# 5. Create/attach tmux session
if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux new-session -d -s "$TMUX_SESSION" -c "$WORK_DIR"
    tmux rename-window -t "$TMUX_SESSION" "$AGENT_NAME"
else
    tmux new-window -t "$TMUX_SESSION" -n "$AGENT_NAME" -c "$WORK_DIR"
fi

# 6. Build the agent prompt
AGENT_PROMPT=$(cat <<PROMPT
You are a worker agent in a multi-agent swarm.

YOUR TASK (Beads ID: $TASK_ID):
$TASK_DESC

RULES:
1. Work ONLY in this directory: $WORK_DIR
2. Write all output files to: $WORK_DIR/output/
3. This task is already claimed by you in Beads
4. When done:
   - Write a summary to $WORK_DIR/output/SUMMARY.md
   - bd close $TASK_ID --reason "Completed: [summary of what you produced]"
   - THEN STOP. Do not continue to other tasks.
5. If you find work outside your scope, file it:
   bd create "Discovered: [description]" -t task -p 2
6. If you are blocked, update Beads:
   bd update $TASK_ID --notes "BLOCKED: [reason]"
PROMPT
)

# 7. Write prompt to file
echo "$AGENT_PROMPT" > "$WORK_DIR/.agent-prompt.txt"

# 8. Launch agent CLI in tmux
tmux send-keys -t "$TMUX_SESSION:$AGENT_NAME" \
    "$AGENT_CMD $AGENT_FLAGS -p \"\$(cat .agent-prompt.txt)\"" Enter

echo "✓ Generic agent spawned: $AGENT_NAME (tmux: $TMUX_SESSION)"
