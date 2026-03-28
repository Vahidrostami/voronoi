#!/bin/bash
set -euo pipefail

# =============================================================================
# spawn-agent.sh — Git worktree + tmux plumbing for agent spawning
#
# Creates a worktree on a new branch, opens a tmux window, and launches the
# agent CLI with a prompt file. The ORCHESTRATOR writes the prompt — this
# script is pure infrastructure plumbing.
#
# Usage: ./scripts/spawn-agent.sh [--safe] <task-id> <branch-name> [prompt-file]
#
# If prompt-file is provided, it's copied into the worktree as .agent-prompt.txt.
# If omitted, the orchestrator must have already written .agent-prompt.txt
# into the worktree path.
# =============================================================================

SAFE_MODE=false
if [[ "${1:-}" == "--safe" ]]; then
    SAFE_MODE=true
    shift
fi

TASK_ID="$1"
BRANCH_NAME="$2"
PROMPT_FILE="${3:-}"

# Load config
CONFIG=$(cat .swarm-config.json)
PROJECT_DIR=$(echo "$CONFIG" | jq -r '.project_dir')
SWARM_DIR=$(echo "$CONFIG" | jq -r '.swarm_dir')
TMUX_SESSION=$(echo "$CONFIG" | jq -r '.tmux_session')
AGENT_CMD=$(echo "$CONFIG" | jq -r '.agent_command // "copilot"')
WORKER_MODEL=$(echo "$CONFIG" | jq -r '.worker_model // ""')
EFFORT=$(echo "$CONFIG" | jq -r '.effort // "medium"')

# Select permission mode
if [[ "$SAFE_MODE" == "true" ]]; then
    AGENT_FLAGS=$(echo "$CONFIG" | jq -r '(.agent_flags_safe // []) | join(" ")')
    if [[ -z "$AGENT_FLAGS" ]]; then
        echo "⚠ No agent_flags_safe in config, falling back to --allow-all"
        AGENT_FLAGS="--allow-all"
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

resolve_default_branch() {
    local branch
    branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##') || true
    if [[ -n "$branch" ]]; then
        echo "$branch"
        return
    fi
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || true
    if [[ -n "$branch" && "$branch" != "HEAD" ]]; then
        echo "$branch"
        return
    fi
    if git show-ref --verify --quiet refs/heads/main; then
        echo "main"
        return
    fi
    if git show-ref --verify --quiet refs/heads/master; then
        echo "master"
        return
    fi
    echo "main"
}

echo "--- Spawning agent: $BRANCH_NAME ---"

# =========================================================================
# Pre-dispatch artifact validation (REQUIRES / GATE checks)
# =========================================================================
TASK_JSON=$(bd show "$TASK_ID" --json 2>/dev/null || echo "{}")
TASK_NOTES=$(echo "$TASK_JSON" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('notes', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")

# Extract TASK_TYPE from notes (e.g. TASK_TYPE:scout) for role-based permissions
TASK_TYPE=$(echo "$TASK_NOTES" | python3 -c "
import sys, re
notes = sys.stdin.read()
for line in notes.split('\n'):
    m = re.match(r'TASK_TYPE:\s*(\S+)', line.strip())
    if m:
        print(m.group(1))
        break
" 2>/dev/null || echo "")

# Check REQUIRES: files must exist before dispatch
REQUIRES_LIST=$(echo "$TASK_NOTES" | python3 -c "
import sys, re
notes = sys.stdin.read()
for line in notes.split('\n'):
    m = re.match(r'REQUIRES:\s*(.+)', line.strip())
    if m:
        for f in m.group(1).split(','):
            f = f.strip()
            if f:
                print(f)
" 2>/dev/null || true)

if [ -n "$REQUIRES_LIST" ]; then
    MISSING_REQUIRES=""
    while IFS= read -r req; do
        [ -z "$req" ] && continue
        if [ ! -e "${PROJECT_DIR}/${req}" ]; then
            MISSING_REQUIRES="${MISSING_REQUIRES}  - ${req}\n"
        fi
    done <<< "$REQUIRES_LIST"
    if [ -n "$MISSING_REQUIRES" ]; then
        echo "✗ Pre-dispatch FAILED: Missing REQUIRES artifacts:"
        echo -e "$MISSING_REQUIRES"
        bd update "$TASK_ID" --notes "BLOCKED: Missing required artifacts — dispatch deferred" 2>/dev/null || true
        echo "  Task $TASK_ID marked BLOCKED. Fix upstream tasks first."
        exit 1
    fi
    echo "✓ Pre-dispatch: All REQUIRES artifacts present"
fi

# Check GATE: validation file must exist AND pass
GATE_PATH=$(echo "$TASK_NOTES" | python3 -c "
import sys, re
notes = sys.stdin.read()
for line in notes.split('\n'):
    m = re.match(r'GATE:\s*(.+)', line.strip())
    if m:
        print(m.group(1).strip())
        break
" 2>/dev/null || true)

if [ -n "$GATE_PATH" ]; then
    GATE_FULL="${PROJECT_DIR}/${GATE_PATH}"
    if [ ! -f "$GATE_FULL" ]; then
        echo "✗ Pre-dispatch FAILED: GATE file missing: $GATE_PATH"
        bd update "$TASK_ID" --notes "BLOCKED: GATE artifact missing — dispatch deferred" 2>/dev/null || true
        exit 1
    fi
    # Verify GATE contains passing verdict
    GATE_STATUS=$(python3 -c "
import sys, json
try:
    data = json.load(open('$GATE_FULL'))
    status = data.get('status', '')
    converged = data.get('converged', False)
    if status in ('converged', 'pass', 'passed') or converged:
        print('PASS')
    else:
        print('FAIL:' + status)
except Exception as e:
    print('ERROR:' + str(e))
" 2>/dev/null || echo "ERROR:parse_failed")
    if [[ "$GATE_STATUS" != "PASS" ]]; then
        echo "✗ Pre-dispatch FAILED: GATE not passing: $GATE_PATH ($GATE_STATUS)"
        bd update "$TASK_ID" --notes "BLOCKED: GATE validation not passing — dispatch deferred" 2>/dev/null || true
        exit 1
    fi
    echo "✓ Pre-dispatch: GATE $GATE_PATH is passing"
fi

# =========================================================================
# DESIGN_INVALID hard gate: block paper/scribe/compile tasks while open
# =========================================================================
TASK_TITLE=$(echo "$TASK_JSON" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('title', '').lower())
except Exception:
    print('')
" 2>/dev/null || echo "")

if echo "$TASK_TITLE" | grep -qiE "paper|scribe|write.*paper|compile|latex|deliverable"; then
    DESIGN_INVALID_IDS=$(bd list --json 2>/dev/null | python3 -c "
import sys, json
try:
    tasks = json.load(sys.stdin)
    invalid = [str(t.get('id','')) for t in tasks
               if 'DESIGN_INVALID' in t.get('notes','')
               and t.get('status') != 'closed']
    if invalid:
        print(','.join(invalid))
except Exception:
    pass
" 2>/dev/null || true)
    if [ -n "$DESIGN_INVALID_IDS" ]; then
        echo "✗ Pre-dispatch BLOCKED: Cannot start paper/compile task while DESIGN_INVALID experiments remain open: $DESIGN_INVALID_IDS"
        bd update "$TASK_ID" --notes "BLOCKED: DESIGN_INVALID must be resolved before paper writing" 2>/dev/null || true
        exit 1
    fi
    echo "✓ Pre-dispatch: No open DESIGN_INVALID experiments"
fi

echo "✓ Pre-dispatch validation complete"

# =========================================================================
# BLIND directive: remove files the agent must not see
# Format in Beads notes: BLIND:path/to/file
# =========================================================================
BLIND_LIST=$(echo "$TASK_NOTES" | python3 -c "
import sys, re
notes = sys.stdin.read()
for line in notes.split('\n'):
    m = re.match(r'BLIND:\s*(.+)', line.strip())
    if m:
        for f in m.group(1).split(','):
            f = f.strip()
            if f:
                print(f)
" 2>/dev/null || true)

# 1. Create worktree on a new branch
cd "$PROJECT_DIR"
git worktree prune >/dev/null 2>&1 || true
DEFAULT_BRANCH=$(resolve_default_branch)
git worktree add "$WORKTREE_PATH" -b "$BRANCH_NAME" "$DEFAULT_BRANCH" 2>/dev/null || {
    echo "Worktree or branch already exists, reusing..."
    git worktree add "$WORKTREE_PATH" "$BRANCH_NAME" 2>/dev/null || true
}

if [[ ! -d "$WORKTREE_PATH" ]]; then
    echo "✗ Failed to create worktree at $WORKTREE_PATH"
    echo "  This usually means the git repo has no commits yet."
    echo "  Fix: git add -A && git commit -m 'initial commit'"
    exit 1
fi

# 2. Claim the task in Beads
bd update "$TASK_ID" --claim 2>/dev/null || echo "Warning: claim failed (may already be claimed)"

# 2b. Enforce BLIND directive: remove blinded files from worktree
if [ -n "$BLIND_LIST" ]; then
    while IFS= read -r blind_file; do
        [ -z "$blind_file" ] && continue
        BLIND_TARGET="${WORKTREE_PATH}/${blind_file}"
        if [ -e "$BLIND_TARGET" ]; then
            rm -f "$BLIND_TARGET"
            echo "🔒 BLIND: removed $blind_file from agent worktree"
        fi
    done <<< "$BLIND_LIST"
fi

# 3. Copy prompt file into worktree if provided
if [[ -n "$PROMPT_FILE" && -f "$PROMPT_FILE" ]]; then
    cp "$PROMPT_FILE" "$WORKTREE_PATH/.agent-prompt.txt"
fi

# 4. Create/attach tmux session
if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux new-session -d -s "$TMUX_SESSION" -c "$WORKTREE_PATH"
    tmux rename-window -t "$TMUX_SESSION" "$BRANCH_NAME"
else
    if tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$BRANCH_NAME"; then
        echo "⚠ tmux window '$BRANCH_NAME' already exists, reusing"
    else
        tmux new-window -t "$TMUX_SESSION" -n "$BRANCH_NAME" -c "$WORKTREE_PATH"
    fi
fi

# 5. Launch agent CLI in the tmux pane
# Quote config-derived values to prevent shell injection
SAFE_CMD=$(printf '%q' "$AGENT_CMD")
SAFE_FLAGS=$(printf '%q' "$AGENT_FLAGS")
SAFE_WP=$(printf '%q' "$WORKTREE_PATH")

# Build --model flag for workers (if configured)
MODEL_FLAG=""
if [[ -n "$WORKER_MODEL" ]]; then
    MODEL_FLAG=" --model $(printf '%q' "$WORKER_MODEL")"
fi

# Build --effort flag from config (rigor-scaled, written by dispatcher)
EFFORT_FLAG=""
if [[ -n "$EFFORT" && "$EFFORT" != "null" ]]; then
    EFFORT_FLAG=" --effort $EFFORT"
fi

# Build --share flag for clean audit trail
SHARE_FLAG=" --share $(printf '%q' "$WORKTREE_PATH/.swarm/session.md")"
mkdir -p "$WORKTREE_PATH/.swarm"

# 5b. Role-based --deny-tool permissions.
# Read-only roles get --deny-tool=write to structurally enforce
# that reviewers cannot modify code (belt + suspenders with .agent.md tools list).
ROLE_PERMS=$(echo "$CONFIG" | jq -r ".role_permissions.\"$TASK_TYPE\" // \"\"" 2>/dev/null || true)
if [[ -n "$ROLE_PERMS" && "$ROLE_PERMS" != "null" ]]; then
    AGENT_FLAGS="$ROLE_PERMS"
    SAFE_FLAGS=$(printf '%q' "$AGENT_FLAGS")
fi

# 5c. Inject auth tokens via tmux set-environment (INV-31: no secrets in logs).
# tmux shells inherit the tmux server's env, not the caller's. Using
# set-environment avoids inline export commands that would be captured
# by pipe-pane logging.
for _var in GH_TOKEN GITHUB_TOKEN COPILOT_GITHUB_TOKEN; do
    _val="${!_var:-}"
    if [[ -n "$_val" ]]; then
        tmux set-environment -t "$TMUX_SESSION" "$_var" "$_val" 2>/dev/null || true
    fi
done

# 5c. Export BEADS_DIR so workers can find the Beads database from worktrees.
# Worktrees live in a sibling directory, so bd's upward discovery won't
# find .beads in the main workspace.
if [[ -d "${PROJECT_DIR}/.beads" ]]; then
    tmux set-environment -t "$TMUX_SESSION" "BEADS_DIR" "${PROJECT_DIR}/.beads" 2>/dev/null || true
fi

if [[ -f "$WORKTREE_PATH/.agent-prompt.txt" ]]; then
    tmux send-keys -t "$TMUX_SESSION:$BRANCH_NAME" \
        "cd $SAFE_WP && $SAFE_CMD $SAFE_FLAGS$MODEL_FLAG$EFFORT_FLAG$SHARE_FLAG -p \"\$(cat .agent-prompt.txt)\"" Enter
else
    echo "⚠ No prompt file found — agent will start in interactive mode"
    tmux send-keys -t "$TMUX_SESSION:$BRANCH_NAME" \
        "cd $SAFE_WP && $SAFE_CMD $SAFE_FLAGS$MODEL_FLAG$EFFORT_FLAG$SHARE_FLAG" Enter
fi

echo "✓ Agent spawned: $BRANCH_NAME (tmux: $TMUX_SESSION)"

# 6. Notify Telegram (fire-and-forget)
source "${PROJECT_DIR}/scripts/notify-telegram.sh" 2>/dev/null || true
notify_telegram "agent_spawn" "⚡ Agent spawned: \`${BRANCH_NAME}\` → task ${TASK_ID}" 2>/dev/null || true
