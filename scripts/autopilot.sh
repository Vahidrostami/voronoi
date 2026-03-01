#!/bin/bash
set -euo pipefail

# =============================================================================
# autopilot.sh — Autonomous swarm orchestration daemon
#
# Replaces human-in-the-loop merge/dispatch cycle. Polls for agent completions,
# runs quality gates, merges branches, and dispatches newly unblocked tasks.
#
# Usage:
#   ./scripts/autopilot.sh [options]
#
# Options:
#   --poll-interval N    Seconds between polls (default: 30)
#   --max-retries N      Max retries for failed agents (default: 3)
#   --quality-gate CMD   Custom quality gate command (default: scripts/quality-gate.sh)
#   --no-merge           Skip auto-merge (just monitor and dispatch)
#   --dry-run            Show what would happen without acting
#   --quiet              Suppress live status output
#   --dashboard FILE     Write live dashboard to file (tail -f to watch)
#   --timeout N          Max seconds per agent before killing (default: 600)
#   --notify CMD         Command to run on completion (e.g., "say done")
# =============================================================================

# --- Defaults ---
POLL_INTERVAL=30
MAX_RETRIES=3
QUALITY_GATE="./scripts/quality-gate.sh"
NO_MERGE=false
DRY_RUN=false
QUIET=false
DASHBOARD_FILE=""
AGENT_TIMEOUT=600
NOTIFY_CMD=""

# --- Parse args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --poll-interval) POLL_INTERVAL="$2"; shift 2 ;;
        --max-retries)   MAX_RETRIES="$2"; shift 2 ;;
        --quality-gate)  QUALITY_GATE="$2"; shift 2 ;;
        --no-merge)      NO_MERGE=true; shift ;;
        --dry-run)       DRY_RUN=true; shift ;;
        --quiet)         QUIET=true; shift ;;
        --dashboard)     DASHBOARD_FILE="$2"; shift 2 ;;
        --timeout)       AGENT_TIMEOUT="$2"; shift 2 ;;
        --notify)        NOTIFY_CMD="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- Load config ---
CONFIG=$(cat .swarm-config.json)
PROJECT_DIR=$(echo "$CONFIG" | jq -r '.project_dir')
PROJECT_NAME=$(echo "$CONFIG" | jq -r '.project_name')
SWARM_DIR=$(echo "$CONFIG" | jq -r '.swarm_dir')
TMUX_SESSION=$(echo "$CONFIG" | jq -r '.tmux_session')
MAX_AGENTS=$(echo "$CONFIG" | jq -r '.max_agents // 4')

cd "$PROJECT_DIR"
shopt -s nullglob   # globs that match nothing expand to nothing

# --- State tracking ---
declare -A AGENT_RETRIES        # branch -> retry count
declare -A AGENT_SPAWN_TIME     # branch -> epoch seconds
declare -A AGENT_TASK_MAP       # branch -> beads task id
declare -A TASK_DESCRIPTION_MAP # task_id -> description
WAVE=0
TOTAL_MERGED=0
TOTAL_DISPATCHED=0
START_TIME=$(date +%s)

# --- Logging ---
log() {
    local level="$1"; shift
    local msg="$*"
    local ts
    ts=$(date '+%H:%M:%S')
    local line="[$ts] [$level] $msg"
    if [[ "$QUIET" != "true" || "$level" == "ERROR" ]]; then
        echo "$line"
    fi
    if [[ -n "$DASHBOARD_FILE" ]]; then
        echo "$line" >> "$DASHBOARD_FILE"
    fi
}

log_status() {
    log "STATUS" "$*"
}

log_action() {
    log "ACTION" "$*"
}

log_error() {
    log "ERROR" "$*"
}

# --- Dashboard writer ---
write_dashboard() {
    [[ -n "$DASHBOARD_FILE" ]] || return 0
    local _elapsed=$(( $(date +%s) - START_TIME ))
    local _elapsed_min=$(( _elapsed / 60 ))

    cat > "${DASHBOARD_FILE}.tmp" <<EOF
┌─ SWARM AUTOPILOT ─────────────────────────────────────────────┐
│ Project: $PROJECT_NAME                     Runtime: ${_elapsed_min}m      │
│ Wave: $WAVE   Merged: $TOTAL_MERGED   Dispatched: $TOTAL_DISPATCHED          │
├───────────────────────────────────────────────────────────────┤
EOF
    # Active agents
    local _wt _branch _tid _spawn _age _age_min _st
    for _wt in "$SWARM_DIR"/agent-*; do
        [ -d "$_wt" ] || continue
        _branch=$(basename "$_wt")
        _tid="${AGENT_TASK_MAP[$_branch]:-?}"
        _spawn="${AGENT_SPAWN_TIME[$_branch]:-0}"
        _age=$(( $(date +%s) - _spawn ))
        _age_min=$(( _age / 60 ))
        _st="🔄 running (${_age_min}m)"

        # Check if task is closed in beads
        if bd show "$_tid" 2>/dev/null | grep -q 'status.*closed'; then
            _st="✅ complete"
        fi

        printf "│ %-20s %-12s %s\n" "$_branch" "$_tid" "$_st" >> "${DASHBOARD_FILE}.tmp"
    done

    # Ready tasks
    local _ready_count _open_count
    _ready_count=$(bd ready --json 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
    _open_count=$(bd list --status open --json 2>/dev/null | jq 'length' 2>/dev/null || echo 0)

    cat >> "${DASHBOARD_FILE}.tmp" <<EOF
├───────────────────────────────────────────────────────────────┤
│ Ready: $_ready_count   Open: $_open_count   Poll: ${POLL_INTERVAL}s   Timeout: ${AGENT_TIMEOUT}s │
└───────────────────────────────────────────────────────────────┘
EOF
    mv "${DASHBOARD_FILE}.tmp" "$DASHBOARD_FILE"
}

# --- Check if an agent has completed ---
# Returns 0 if complete, 1 if still running
agent_is_complete() {
    local branch="$1"
    local task_id="$2"

    # Check 1: Beads task closed (agent closed it itself)
    if bd show "$task_id" --json 2>/dev/null | jq -e '.status == "closed"' >/dev/null 2>&1; then
        return 0
    fi

    # Check 2: tmux window gone (agent process exited)
    if ! tmux list-windows -t "$TMUX_SESSION" 2>/dev/null | grep -q "$branch"; then
        return 0
    fi

    # Check 3: Timeout exceeded
    local spawn_time="${AGENT_SPAWN_TIME[$branch]:-0}"
    local now
    now=$(date +%s)
    if (( now - spawn_time > AGENT_TIMEOUT )); then
        log_error "$branch timed out after ${AGENT_TIMEOUT}s"
        # Kill the tmux window
        tmux kill-window -t "$TMUX_SESSION:$branch" 2>/dev/null || true
        bd update "$task_id" --notes "TIMEOUT: Agent killed after ${AGENT_TIMEOUT}s" 2>/dev/null || true
        return 0
    fi

    return 1
}

# --- Check if agent succeeded ---
# Returns 0 if the branch has commits and task is closed with success
agent_succeeded() {
    local branch="$1"
    local task_id="$2"

    # Must have commits
    local commit_count
    commit_count=$(git log "main..$branch" --oneline 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$commit_count" -eq 0 ]]; then
        return 1
    fi

    # Task should be closed
    if bd show "$task_id" --json 2>/dev/null | jq -e '.status == "closed"' >/dev/null 2>&1; then
        return 0
    fi

    return 1
}

# --- Run quality gate ---
run_quality_gate() {
    local branch="$1"
    local task_id="$2"
    local worktree="$SWARM_DIR/$branch"

    if [[ ! -x "$QUALITY_GATE" ]]; then
        log_status "No quality gate configured, auto-passing"
        return 0
    fi

    log_action "Running quality gate for $branch"
    if "$QUALITY_GATE" "$branch" "$task_id" "$worktree"; then
        log_status "Quality gate passed for $branch"
        return 0
    else
        log_error "Quality gate failed for $branch"
        return 1
    fi
}

# --- Retry a failed agent ---
retry_agent() {
    local branch="$1"
    local task_id="$2"
    local retry_count="${AGENT_RETRIES[$branch]:-0}"

    if (( retry_count >= MAX_RETRIES )); then
        log_error "$branch failed after $MAX_RETRIES retries, skipping"
        bd update "$task_id" --notes "FAILED: Exhausted $MAX_RETRIES retries" 2>/dev/null || true
        return 1
    fi

    retry_count=$((retry_count + 1))
    AGENT_RETRIES[$branch]=$retry_count
    log_action "Retrying $branch (attempt $retry_count/$MAX_RETRIES)"

    # Clean up old worktree
    git worktree remove "$SWARM_DIR/$branch" 2>/dev/null || true
    tmux kill-window -t "$TMUX_SESSION:$branch" 2>/dev/null || true

    # Reopen the task
    bd update "$task_id" --status open 2>/dev/null || true

    # Get description
    local desc="${TASK_DESCRIPTION_MAP[$task_id]:-Retry task $task_id}"
    local retry_desc="RETRY $retry_count/$MAX_RETRIES: $desc

Previous attempt failed. Check git log for what was tried before. Fix issues and complete the task."

    # Re-spawn
    if [[ "$DRY_RUN" == "true" ]]; then
        log_action "[DRY RUN] Would re-spawn $branch for $task_id"
    else
        ./scripts/spawn-agent.sh "$task_id" "$branch" "$retry_desc"
        AGENT_SPAWN_TIME[$branch]=$(date +%s)
        AGENT_TASK_MAP[$branch]=$task_id
    fi
    return 0
}

# --- Merge a completed agent ---
merge_agent() {
    local branch="$1"
    local task_id="$2"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_action "[DRY RUN] Would merge $branch (task $task_id)"
        return 0
    fi

    log_action "Merging $branch → main"
    if ./scripts/merge-agent.sh "$branch" "$task_id" 2>&1; then
        TOTAL_MERGED=$((TOTAL_MERGED + 1))
        # Remove from tracking
        unset "AGENT_RETRIES[$branch]"
        unset "AGENT_SPAWN_TIME[$branch]"
        unset "AGENT_TASK_MAP[$branch]"
        log_status "✅ Merged $branch successfully"
        return 0
    else
        log_error "Merge failed for $branch — may need manual conflict resolution"
        return 1
    fi
}

# --- Dispatch ready tasks ---
dispatch_ready() {
    # Count active agents
    local active=0
    local worktree
    for worktree in "$SWARM_DIR"/agent-*; do
        [ -d "$worktree" ] && active=$((active + 1))
    done

    local slots=$((MAX_AGENTS - active))
    if (( slots <= 0 )); then
        return 0
    fi

    # Get ready tasks
    local ready_json
    ready_json=$(bd ready --json 2>/dev/null || echo "[]")
    local ready_count
    ready_count=$(echo "$ready_json" | jq 'length')

    if (( ready_count == 0 )); then
        return 0
    fi

    WAVE=$((WAVE + 1))
    log_status "=== Wave $WAVE: $ready_count tasks ready, $slots slots available ==="

    local dispatched=0
    for i in $(seq 0 $((ready_count - 1))); do
        if (( dispatched >= slots )); then
            break
        fi

        local task_id
        task_id=$(echo "$ready_json" | jq -r ".[$i].id")
        local title
        title=$(echo "$ready_json" | jq -r ".[$i].title")
        local desc
        desc=$(echo "$ready_json" | jq -r ".[$i].description // .[$i].title")

        # Skip epics (only dispatch tasks)
        local issue_type
        issue_type=$(echo "$ready_json" | jq -r ".[$i].issue_type // \"task\"")
        if [[ "$issue_type" == "epic" ]]; then
            continue
        fi

        # Generate branch name from title
        local branch
        branch="agent-$(echo "$title" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | cut -c1-40)"

        if [[ "$DRY_RUN" == "true" ]]; then
            log_action "[DRY RUN] Would dispatch $branch for $task_id: $title"
        else
            log_action "Dispatching $branch for task $task_id"
            if ./scripts/spawn-agent.sh "$task_id" "$branch" "$desc" 2>&1; then
                AGENT_SPAWN_TIME[$branch]=$(date +%s)
                AGENT_TASK_MAP[$branch]=$task_id
                TASK_DESCRIPTION_MAP[$task_id]="$desc"
                TOTAL_DISPATCHED=$((TOTAL_DISPATCHED + 1))
                dispatched=$((dispatched + 1))
            else
                log_error "Failed to spawn $branch"
            fi
        fi
    done
}

# --- Check if there's still work ---
has_open_work() {
    local open
    open=$(bd list --status open --json 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
    local in_progress
    in_progress=$(bd list --status in_progress --json 2>/dev/null | jq 'length' 2>/dev/null || echo 0)

    # Also check for active agent worktrees
    local active=0
    local worktree
    for worktree in "$SWARM_DIR"/agent-*; do
        [ -d "$worktree" ] && active=$((active + 1))
    done

    (( open + in_progress + active > 0 ))
}

# =============================================================================
# MAIN LOOP
# =============================================================================

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║           🤖 SWARM AUTOPILOT — $PROJECT_NAME"
echo "║                                                               ║"
echo "║  Poll: ${POLL_INTERVAL}s  Max agents: $MAX_AGENTS  Timeout: ${AGENT_TIMEOUT}s      ║"
echo "║  Quality gate: $QUALITY_GATE"
echo "║  Dry run: $DRY_RUN                                           ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

if [[ -n "$DASHBOARD_FILE" ]]; then
    log_status "Dashboard: tail -f $DASHBOARD_FILE"
fi

# Initial dispatch
dispatch_ready

# Main loop
_loop_branch=""
_loop_task_id=""
while has_open_work; do
    sleep "$POLL_INTERVAL"

    # --- Check each active agent ---
    for _loop_wt in "$SWARM_DIR"/agent-*; do
        [ -d "$_loop_wt" ] || continue
        _loop_branch=$(basename "$_loop_wt")
        _loop_task_id="${AGENT_TASK_MAP[$_loop_branch]:-}"

        # If we don't know the task ID, skip
        if [[ -z "$_loop_task_id" ]]; then
            continue
        fi

        # Is this agent done?
        if agent_is_complete "$_loop_branch" "$_loop_task_id"; then
            if agent_succeeded "$_loop_branch" "$_loop_task_id"; then
                # Run quality gate
                if [[ "$NO_MERGE" == "true" ]]; then
                    log_status "$_loop_branch complete (no-merge mode, skipping)"
                elif run_quality_gate "$_loop_branch" "$_loop_task_id"; then
                    merge_agent "$_loop_branch" "$_loop_task_id"
                else
                    retry_agent "$_loop_branch" "$_loop_task_id" || true
                fi
            else
                log_error "$_loop_branch completed without success (no commits or task not closed)"
                retry_agent "$_loop_branch" "$_loop_task_id" || true
            fi
        fi
    done

    # --- Dispatch newly ready tasks ---
    dispatch_ready

    # --- Update dashboard ---
    write_dashboard

done

# =============================================================================
# COMPLETION
# =============================================================================

ELAPSED=$(( $(date +%s) - START_TIME ))
ELAPSED_MIN=$(( ELAPSED / 60 ))

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║           ✅ SWARM COMPLETE                                   ║"
echo "║                                                               ║"
echo "║  Waves: $WAVE   Merged: $TOTAL_MERGED   Runtime: ${ELAPSED_MIN}m              ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Run notification command if set
if [[ -n "$NOTIFY_CMD" ]]; then
    eval "$NOTIFY_CMD" 2>/dev/null || true
fi

# Final dashboard
write_dashboard
