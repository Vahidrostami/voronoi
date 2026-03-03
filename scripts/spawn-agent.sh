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

# 3. Create/attach tmux session (guard against duplicate windows)
if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux new-session -d -s "$TMUX_SESSION" -c "$WORKTREE_PATH"
    tmux rename-window -t "$TMUX_SESSION" "$BRANCH_NAME"
else
    # Check if a window with this name already exists — reuse it instead of creating a duplicate
    if tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$BRANCH_NAME"; then
        echo "⚠ tmux window '$BRANCH_NAME' already exists, reusing"
    else
        tmux new-window -t "$TMUX_SESSION" -n "$BRANCH_NAME" -c "$WORKTREE_PATH"
    fi
fi

# 4. Read artifact contract from Beads
TASK_NOTES=$(bd show "$TASK_ID" --json 2>/dev/null | jq -r '.notes // ""' || true)
PRODUCES=$(echo "$TASK_NOTES" | sed -n 's/.*PRODUCES:\(.*\)/\1/p' | head -1 || true)
REQUIRES=$(echo "$TASK_NOTES" | sed -n 's/.*REQUIRES:\(.*\)/\1/p' | head -1 || true)
GATE=$(echo "$TASK_NOTES" | sed -n 's/.*GATE:\(.*\)/\1/p' | head -1 || true)

ARTIFACT_RULES=""
if [[ -n "$PRODUCES" ]]; then
    ARTIFACT_RULES="${ARTIFACT_RULES}
8. ARTIFACT CONTRACT — You MUST create these files before closing your task:
   $PRODUCES
   The quality gate will REJECT your work if any of these files are missing."
fi
if [[ -n "$REQUIRES" ]]; then
    ARTIFACT_RULES="${ARTIFACT_RULES}
9. REQUIRED INPUTS — These files must exist (they should already be present):
   $REQUIRES
   If any are missing, update Beads with BLOCKED status and STOP."
fi
if [[ -n "$GATE" ]]; then
    ARTIFACT_RULES="${ARTIFACT_RULES}
10. GATE CHECK — Before doing ANY work, verify this gate artifact:
    $GATE
    The file must exist AND contain passing verdicts. If it doesn't, STOP and report BLOCKED."
fi

# 4b. Read demo-scoped output directory from environment (set by autopilot.sh)
OUTPUT_DIR_RULE=""
if [[ -n "${SWARM_OUTPUT_DIR:-}" ]]; then
    OUTPUT_DIR_RULE="
CRITICAL — OUTPUT DIRECTORY:
All output files MUST be written under: $SWARM_OUTPUT_DIR/
Do NOT write output to the repository root. All source code goes in $SWARM_OUTPUT_DIR/src/
and all generated output goes in $SWARM_OUTPUT_DIR/output/.
This is the demo working directory — scope ALL your work within it."
fi

# 4c. Include original prompt context if available
PROMPT_CONTEXT=""
if [[ -n "${SWARM_PROMPT_FILE:-}" && -f "${SWARM_PROMPT_FILE:-}" ]]; then
    # Include the first 100 lines of the prompt for context (avoid huge prompts)
    PROMPT_EXCERPT=$(head -100 "$SWARM_PROMPT_FILE")
    PROMPT_CONTEXT="
ORIGINAL PROJECT BRIEF (first 100 lines — read the full file at $SWARM_PROMPT_FILE if needed):
---
$PROMPT_EXCERPT
---"
fi

# 4d. Include lab notebook context for improvement/iteration tasks
LAB_NOTEBOOK_CONTEXT=""
IS_IMPROVEMENT=$(echo "$TASK_NOTES" | grep -c 'IMPROVEMENT_TASK\|CONVERGENCE' || true)
NOTEBOOK_FILE="${PROJECT_DIR}/.swarm/lab-notebook.json"
if [[ "$IS_IMPROVEMENT" -gt 0 && -f "$NOTEBOOK_FILE" ]]; then
    LAB_NOTEBOOK_SUMMARY=$(python3 -c "
import json
with open('$NOTEBOOK_FILE') as f: nb = json.load(f)
iters = nb.get('iterations', [])
lines = []
for it in iters:
    v = it.get('verdict', '?')
    p = it.get('phase', '?')
    fails = it.get('failures', [])
    steps = it.get('next_steps', [])
    lines.append(f'Iteration {it.get(\"iteration\",\"?\")}: {v}')
    for fail in fails[:3]:
        issue = fail.get('issue','') if isinstance(fail,dict) else str(fail)
        lines.append(f'  FAILED: {issue[:150]}')
    for step in steps[:2]:
        lines.append(f'  NEXT: {step[:100]}')
print('\n'.join(lines[-30:]))  # Last 30 lines max
" 2>/dev/null || echo "No lab notebook data available")
    LAB_NOTEBOOK_CONTEXT="
ITERATION CONTEXT (from lab notebook — DO NOT repeat failed approaches):
$LAB_NOTEBOOK_SUMMARY"
fi

# 5. Build the agent prompt
AGENT_PROMPT=$(cat <<PROMPT
You are a worker agent in a multi-agent swarm.

YOUR TASK (Beads ID: $TASK_ID):
$TASK_DESC
$OUTPUT_DIR_RULE
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
   bd update $TASK_ID --notes "BLOCKED: [reason]"$ARTIFACT_RULES
$PROMPT_CONTEXT
$LAB_NOTEBOOK_CONTEXT
PROMPT
)

# 6. Write prompt to file in worktree (avoids shell quoting issues in tmux)
echo "$AGENT_PROMPT" > "$WORKTREE_PATH/.agent-prompt.txt"

# 7. Launch agent CLI in the tmux pane
#    Flags go before -p so -p gets the prompt as its argument value
tmux send-keys -t "$TMUX_SESSION:$BRANCH_NAME" \
    "$AGENT_CMD $AGENT_FLAGS -p \"\$(cat .agent-prompt.txt)\"" Enter

echo "✓ Agent spawned: $BRANCH_NAME (tmux: $TMUX_SESSION)"
