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
#   --prompt FILE        Auto-plan tasks from prompt file using LLM
#   --domain DOMAIN      code (default), research, or generic
#   --poll-interval N    Seconds between polls (default: 30)
#   --max-retries N      Max retries for failed agents (default: 3)
#   --quality-gate CMD   Custom quality gate command (default: scripts/quality-gate.sh)
#   --no-merge           Skip auto-merge (just monitor and dispatch)
#   --dry-run            Show what would happen without acting
#   --quiet              Suppress live status output
#   --dashboard FILE     Write live dashboard to file (tail -f to watch)
#   --timeout N          Max seconds per agent before killing (default: 600)
#   --notify CMD         Command to run on completion (e.g., "say done")
#   --safe               Use granular tool permissions (no curl, ssh, sudo, rm -rf)
#   --output-dir DIR      Set the output directory for demo-scoped work (auto-detected from --prompt path)
#   --resume              Resume from a crashed/interrupted autopilot session
#
# Examples:
#   # Full autopilot from prompt file:
#   ./scripts/autopilot.sh --prompt PROMPT.md --dashboard /tmp/swarm.txt
#
#   # Research domain (plain dirs, no git worktrees):
#   ./scripts/autopilot.sh --prompt research-brief.md --domain research
#
#   # Resume after crash:
#   ./scripts/autopilot.sh --resume
#
#   # Pre-planned tasks (just run the autopilot loop):
#   ./scripts/autopilot.sh --notify "say 'done'"
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
PROMPT_FILE=""
DOMAIN="code"
SAFE_MODE=false
OUTPUT_DIR=""        # Demo-scoped output directory (auto-detected from --prompt path)
RESUME=false          # If true, skip planning and resume from saved state
MAX_ITERATIONS=3      # Max convergence iterations for scientific workflows

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
        --prompt)        PROMPT_FILE="$2"; shift 2 ;;
        --domain)        DOMAIN="$2"; shift 2 ;;
        --safe)          SAFE_MODE=true; shift ;;
        --output-dir)    OUTPUT_DIR="$2"; shift 2 ;;
        --max-iterations) MAX_ITERATIONS="$2"; shift 2 ;;
        --resume)        RESUME=true; shift ;;
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

# --- Source Telegram notification helper ---
NOTIFY_SCRIPT="$PROJECT_DIR/scripts/notify-telegram.sh"
if [[ -f "$NOTIFY_SCRIPT" ]]; then
    source "$NOTIFY_SCRIPT"
fi

# --- Initialize lab notebook for scientific tracking ---
"$PROJECT_DIR/scripts/lab-notebook.sh" init 2>/dev/null || true

# --- State persistence file (survives crashes) ---
STATE_FILE="${PROJECT_DIR}/.swarm/autopilot-state.json"
mkdir -p "${PROJECT_DIR}/.swarm"

save_state() {
    local _state_tmp
    _state_tmp=$(mktemp)
    # Build JSON from bash arrays
    local _agents_json="{"
    local _first=true
    local _b _t
    for _b in "${!AGENT_TASK_MAP[@]}"; do
        _t="${AGENT_TASK_MAP[$_b]}"
        local _spawn="${AGENT_SPAWN_TIME[$_b]:-0}"
        local _retries="${AGENT_RETRIES[$_b]:-0}"
        local _desc="${TASK_DESCRIPTION_MAP[$_t]:-}"
        _desc=$(echo "$_desc" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo '""')
        if [[ "$_first" == "true" ]]; then _first=false; else _agents_json+=","; fi
        _agents_json+="\"$_b\":{\"task_id\":\"$_t\",\"spawn_time\":$_spawn,\"retries\":$_retries,\"description\":$_desc}"
    done
    _agents_json+="}"
    cat > "$_state_tmp" <<STATEJSON
{
  "wave": $WAVE,
  "total_merged": $TOTAL_MERGED,
  "total_dispatched": $TOTAL_DISPATCHED,
  "start_time": $START_TIME,
  "prompt_file": "${PROMPT_FILE:-}",
  "output_dir": "${OUTPUT_DIR:-}",
  "agents": $_agents_json,
  "updated": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
STATEJSON
    mv "$_state_tmp" "$STATE_FILE" 2>/dev/null || true
}

load_state() {
    [[ -f "$STATE_FILE" ]] || return 1
    echo "[$(date '+%H:%M:%S')] [RECOVERY] Found autopilot state, restoring..."
    local _agents
    _agents=$(jq -r '.agents // {} | to_entries[] | "\(.key)|\(.value.task_id)|\(.value.spawn_time)|\(.value.retries)|\(.value.description)"' "$STATE_FILE" 2>/dev/null || true)
    while IFS='|' read -r _b _t _s _r _d; do
        [[ -z "$_b" ]] && continue
        # Only restore if the worktree still exists or the branch exists on remote
        if [[ -d "$SWARM_DIR/$_b" ]] || git branch -r --list "origin/$_b" 2>/dev/null | grep -q .; then
            AGENT_TASK_MAP[$_b]="$_t"
            AGENT_SPAWN_TIME[$_b]="${_s:-$(date +%s)}"
            AGENT_RETRIES[$_b]="${_r:-0}"
            TASK_DESCRIPTION_MAP[$_t]="${_d:-Recovered task $_t}"
            echo "  Restored agent: $_b → task $_t"
        fi
    done <<< "$_agents"
    WAVE=$(jq -r '.wave // 0' "$STATE_FILE" 2>/dev/null || echo 0)
    TOTAL_MERGED=$(jq -r '.total_merged // 0' "$STATE_FILE" 2>/dev/null || echo 0)
    TOTAL_DISPATCHED=$(jq -r '.total_dispatched // 0' "$STATE_FILE" 2>/dev/null || echo 0)
    return 0
}

# --- Safe cleanup trap: merge completed agents FIRST, then clean up only merged ones ---
cleanup_on_exit() {
    local exit_code=$?
    echo ""
    echo "[$(date '+%H:%M:%S')] [CLEANUP] Autopilot exiting (code=$exit_code)..."

    # SAFETY: Try to merge any completed-but-unmerged agents before cleanup
    local _branch _tid
    for _wt in "$SWARM_DIR"/agent-*; do
        [ -d "$_wt" ] || continue
        _branch=$(basename "$_wt")
        _tid="${AGENT_TASK_MAP[$_branch]:-}"
        [[ -z "$_tid" ]] && continue

        if agent_succeeded "$_branch" "$_tid" 2>/dev/null; then
            echo "[CLEANUP] Attempting emergency merge of completed agent: $_branch"
            merge_agent "$_branch" "$_tid" 2>/dev/null || {
                echo "[CLEANUP] ⚠ Could not merge $_branch — branch preserved on remote"
                # Ensure branch is pushed to remote so code isn't lost
                (cd "$SWARM_DIR/$_branch" && git push origin "$_branch" 2>/dev/null) || true
            }
        else
            # Agent didn't finish — push whatever it has to remote so code isn't lost
            echo "[CLEANUP] Preserving unfinished agent $_branch (pushing to remote)"
            (cd "$SWARM_DIR/$_branch" && git add -A && git commit -m "autopilot: preserve unfinished work" 2>/dev/null && git push origin "$_branch" 2>/dev/null) || true
        fi
    done

    # Save state so a restart can resume
    save_state 2>/dev/null || true

    # Only clean up worktrees/branches that were SUCCESSFULLY merged
    # (teardown.sh is too aggressive — it kills everything)
    echo "[CLEANUP] Cleaning merged worktrees only..."
    for _wt in "$SWARM_DIR"/agent-*; do
        [ -d "$_wt" ] || continue
        _branch=$(basename "$_wt")
        # Check if this branch has been merged to main
        if git branch --merged main 2>/dev/null | grep -q "$_branch"; then
            git worktree remove "$_wt" --force 2>/dev/null || rm -rf "$_wt"
            git branch -d "$_branch" 2>/dev/null || true
            git push origin --delete "$_branch" 2>/dev/null || true
            echo "  Cleaned merged branch: $_branch"
        else
            echo "  Preserved unmerged branch: $_branch (code safe on remote)"
        fi
    done

    # Kill tmux session (agents are done or preserved)
    tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
    git worktree prune 2>/dev/null || true

    echo "[CLEANUP] Done. Unmerged branches preserved on remote."
    echo "  To resume: ./scripts/autopilot.sh (will restore state automatically)"
    exit $exit_code
}
trap cleanup_on_exit EXIT

# --- Pre-flight artifact check ---
# Returns 0 if all REQUIRES and GATE artifacts exist, 1 if any are missing
preflight_check() {
    local task_id="$1"
    local task_json
    task_json=$(bd show "$task_id" --json 2>/dev/null || echo "{}")
    local notes
    notes=$(echo "$task_json" | jq -r '.notes // ""')

    # Check REQUIRES artifacts
    local requires
    requires=$(echo "$notes" | sed -n 's/.*REQUIRES:\(.*\)/\1/p' | head -1)
    if [[ -n "$requires" ]]; then
        IFS=',' read -ra REQ_ARTIFACTS <<< "$requires"
        for artifact in "${REQ_ARTIFACTS[@]}"; do
            artifact=$(echo "$artifact" | xargs)  # trim whitespace
            if [[ ! -e "$PROJECT_DIR/$artifact" ]]; then
                log_status "  ⏳ $task_id waiting on required artifact: $artifact"
                return 1
            fi
        done
    fi

    # Check GATE artifact and its content
    local gate
    gate=$(echo "$notes" | sed -n 's/.*GATE:\(.*\)/\1/p' | head -1)
    if [[ -n "$gate" ]]; then
        gate=$(echo "$gate" | xargs)
        if [[ ! -e "$PROJECT_DIR/$gate" ]]; then
            log_status "  🚫 $task_id blocked by gate: $gate (file missing)"
            return 1
        fi
        # If the gate file is JSON, check for PASS verdicts
        if [[ "$gate" == *.json ]]; then
            local all_pass
            all_pass=$(python3 -c "
import json, sys
try:
    data = json.load(open('$PROJECT_DIR/$gate'))
    # Check various common validation report formats
    if isinstance(data, dict):
        # Format: {\"experiments\": [{\"verdict\": \"PASS\"}, ...]}
        if 'experiments' in data:
            verdicts = [e.get('verdict','').upper() for e in data['experiments']]
            sys.exit(0 if all(v == 'PASS' for v in verdicts) else 1)
        # Format: {\"stage_1\": {\"verdict\": \"PASS\"}, ...}
        verdicts = []
        for k, v in data.items():
            if isinstance(v, dict) and 'verdict' in v:
                verdicts.append(v['verdict'].upper())
        if verdicts:
            sys.exit(0 if all(v == 'PASS' for v in verdicts) else 1)
        # Format: {\"verdict\": \"PASS\"}
        if 'verdict' in data:
            sys.exit(0 if data['verdict'].upper() == 'PASS' else 1)
    # If we can't determine structure, just check the file exists (already done above)
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null)
            if [[ $? -ne 0 ]]; then
                log_status "  🚫 $task_id blocked by gate: $gate (validation not PASS)"
                return 1
            fi
        fi
    fi

    return 0
}

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
        notify_agent_timeout "$branch" "$task_id" "$AGENT_TIMEOUT" 2>/dev/null || true
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
    notify_agent_retry "$branch" "$retry_count" "$MAX_RETRIES" 2>/dev/null || true

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
        local spawn_args=()
        if [[ "$SAFE_MODE" == "true" ]]; then
            spawn_args+=("--safe")
        fi
        spawn_args+=("$task_id" "$branch" "$retry_desc")
        ./scripts/spawn-agent.sh "${spawn_args[@]}"
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
    local merge_script="./scripts/merge-agent.sh"
    if [[ "$DOMAIN" != "code" ]]; then
        merge_script="./scripts/merge-agent-generic.sh"
    fi
    if $merge_script "$branch" "$task_id" 2>&1; then
        TOTAL_MERGED=$((TOTAL_MERGED + 1))
        # Remove from tracking
        unset "AGENT_RETRIES[$branch]"
        unset "AGENT_SPAWN_TIME[$branch]"
        unset "AGENT_TASK_MAP[$branch]"
        log_status "✅ Merged $branch successfully"
        notify_merge "$branch" "$task_id" "$TOTAL_MERGED" 2>/dev/null || true
        return 0
    else
        log_error "Merge failed for $branch — may need manual conflict resolution"
        return 1
    fi
}

# --- Check for convergence checkpoint after validation completes ---
# Scans recently-merged tasks for CONVERGENCE_CHECKPOINT notes and runs
# the convergence judge if a validation report exists.
check_convergence() {
    # Find validation report — look in OUTPUT_DIR first, then common paths
    local vr=""
    local rd=""
    for candidate in \
        "${OUTPUT_DIR:-__none__}/output/validation_report.json" \
        "${OUTPUT_DIR:-__none__}/validation_report.json" \
        "output/validation_report.json" \
        ".swarm/validation_report.json"; do
        if [[ -f "$candidate" ]]; then
            vr="$candidate"
            rd="$(dirname "$candidate")"
            break
        fi
    done
    [[ -z "$vr" ]] && return 0  # No validation report yet

    # Check if convergence already decided
    local conv_marker="${rd}/convergence.json"
    if [[ -f "$conv_marker" ]]; then
        local already
        already=$(python3 -c "import json; print(json.load(open('$conv_marker')).get('converged',False))" 2>/dev/null || echo "False")
        if [[ "$already" == "True" ]]; then
            return 0  # Already converged
        fi
    fi

    # Check if validation report is newer than last convergence check
    local vr_mtime
    vr_mtime=$(stat -f %m "$vr" 2>/dev/null || stat -c %Y "$vr" 2>/dev/null || echo 0)
    local last_check="${PROJECT_DIR}/.swarm/.last_convergence_check"
    local last_mtime=0
    if [[ -f "$last_check" ]]; then
        last_mtime=$(cat "$last_check")
    fi
    if [[ "$vr_mtime" -le "$last_mtime" ]]; then
        return 0  # Already checked this version
    fi

    log_status "🔬 Validation report detected — running convergence judge"

    # Find results.json
    local results_json=""
    for rcandidate in \
        "${OUTPUT_DIR:-__none__}/output/results.json" \
        "${rd}/results.json" \
        "output/results.json"; do
        if [[ -f "$rcandidate" ]]; then
            results_json="$rcandidate"
            break
        fi
    done

    # Run convergence judge
    local judge_args=("$vr" "${results_json:-/dev/null}")
    judge_args+=("--max-iterations" "$MAX_ITERATIONS")
    [[ -n "$OUTPUT_DIR" ]] && judge_args+=("--output-dir" "$OUTPUT_DIR")
    [[ -n "$PROMPT_FILE" ]] && judge_args+=("--prompt-file" "$PROMPT_FILE")

    local judge_exit=0
    "$PROJECT_DIR/scripts/convergence-judge.sh" "${judge_args[@]}" || judge_exit=$?

    # Record check time
    echo "$vr_mtime" > "$last_check"

    # Get iteration info for notification
    local _conv_iter
    _conv_iter=$("$PROJECT_DIR/scripts/lab-notebook.sh" get-iteration 2>/dev/null || echo "?")

    case $judge_exit in
        0)
            log_status "✅ Convergence judge: CONVERGED"
            notify_convergence "CONVERGED" "$_conv_iter" "$MAX_ITERATIONS" 2>/dev/null || true
            ;;
        1)
            log_status "🔄 Convergence judge: ITERATE — new improvement tasks created"
            notify_convergence "ITERATE" "$_conv_iter" "$MAX_ITERATIONS" 2>/dev/null || true
            ;;
        2)
            log_status "⚠ Convergence judge: EXHAUSTED/DIMINISHING — proceeding with limitations"
            notify_convergence "EXHAUSTED" "$_conv_iter" "$MAX_ITERATIONS" 2>/dev/null || true
            ;;
    esac
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
    notify_wave_dispatch "$WAVE" "$slots" "$ready_count" 2>/dev/null || true

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

        # Pre-flight artifact check: verify REQUIRES and GATE artifacts exist
        if ! preflight_check "$task_id"; then
            continue  # Skip this task — it's not truly ready (missing artifacts)
        fi

        # Generate branch name from title
        local branch
        branch="agent-$(echo "$title" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | cut -c1-40)"

        if [[ "$DRY_RUN" == "true" ]]; then
            log_action "[DRY RUN] Would dispatch $branch for $task_id: $title"
        else
            log_action "Dispatching $branch for task $task_id"
            local spawn_script="./scripts/spawn-agent.sh"
            if [[ "$DOMAIN" != "code" ]]; then
                spawn_script="./scripts/spawn-agent-generic.sh"
            fi
            local spawn_args=()
            if [[ "$SAFE_MODE" == "true" ]]; then
                spawn_args+=("--safe")
            fi
            spawn_args+=("$task_id" "$branch" "$desc")
            if $spawn_script "${spawn_args[@]}" 2>&1; then
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

# --- Process operator inbox (commands from Telegram bridge) ---
INBOX_DIR="${PROJECT_DIR}/.swarm/inbox"
INBOX_PROCESSED_DIR="${PROJECT_DIR}/.swarm/inbox/processed"
ABORT_REQUESTED=false

process_inbox() {
    [[ -d "$INBOX_DIR" ]] || return 0
    mkdir -p "$INBOX_PROCESSED_DIR"

    local cmd_file
    for cmd_file in "$INBOX_DIR"/*.json; do
        [[ -f "$cmd_file" ]] || continue

        local action params message target
        action=$(jq -r '.action // ""' "$cmd_file" 2>/dev/null || echo "")
        params=$(jq -r '.params // {}' "$cmd_file" 2>/dev/null || echo "{}")
        message=$(jq -r '.message // ""' "$cmd_file" 2>/dev/null || echo "")

        [[ -z "$action" ]] && { mv "$cmd_file" "$INBOX_PROCESSED_DIR/" 2>/dev/null; continue; }

        log_status "📨 Inbox command: $action"
        notify_inbox_command "$action" "$message" 2>/dev/null || true

        case "$action" in
            reprioritize)
                target=$(echo "$params" | jq -r '.target // ""')
                local priority
                priority=$(echo "$params" | jq -r '.priority // 2')
                if [[ -n "$target" ]]; then
                    bd update "$target" --priority "$priority" 2>/dev/null || true
                    log_action "Reprioritized $target to P$priority"
                fi
                ;;
            pause)
                target=$(echo "$params" | jq -r '.target // ""')
                if [[ -n "$target" ]]; then
                    bd update "$target" --notes "BLOCKED: Paused by operator" 2>/dev/null || true
                    log_action "Paused $target"
                fi
                ;;
            resume)
                target=$(echo "$params" | jq -r '.target // ""')
                if [[ -n "$target" ]]; then
                    bd update "$target" --status open 2>/dev/null || true
                    log_action "Resumed $target"
                fi
                ;;
            add_task)
                local title
                title=$(echo "$params" | jq -r '.title // "Operator task"')
                if [[ -n "$title" ]]; then
                    log_action "New operator task: $title"
                fi
                # Task was already created by telegram-bridge via bd create
                ;;
            abort)
                log_status "🛑 Abort requested by operator"
                ABORT_REQUESTED=true
                ;;
            pivot)
                log_action "🔀 Strategic pivot received: $(echo "$message" | head -c 100)"
                # Guidance file already written by telegram-bridge
                ;;
            guide)
                log_action "📝 Operator guidance: $(echo "$message" | head -c 100)"
                # Guidance file already written by telegram-bridge
                ;;
            *)
                log_status "Unknown inbox command: $action"
                ;;
        esac

        # Move to processed
        mv "$cmd_file" "$INBOX_PROCESSED_DIR/" 2>/dev/null || true
    done

    # Handle abort by breaking out of the main loop
    if [[ "$ABORT_REQUESTED" == "true" ]]; then
        log_status "🛑 Aborting swarm (operator request)..."
        notify_telegram "swarm_abort" "🛑 Swarm aborted by operator" 2>/dev/null || true
        # Let the cleanup trap handle the rest
        exit 0
    fi
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
echo "║  Domain: $DOMAIN  Quality gate: $QUALITY_GATE"
echo "║  Dry run: $DRY_RUN  Safe mode: $SAFE_MODE                     ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# --- Phase -1: Try to resume from saved state ---
if [[ "$RESUME" == "true" ]] || [[ -z "$PROMPT_FILE" && -f "$STATE_FILE" ]]; then
    if load_state; then
        log_status "Resumed from saved state (wave $WAVE, $TOTAL_MERGED merged, $TOTAL_DISPATCHED dispatched)"
        # Recover OUTPUT_DIR from state if not specified
        if [[ -z "$OUTPUT_DIR" ]]; then
            OUTPUT_DIR=$(jq -r '.output_dir // empty' "$STATE_FILE" 2>/dev/null || true)
        fi
        if [[ -z "$PROMPT_FILE" ]]; then
            PROMPT_FILE=$(jq -r '.prompt_file // empty' "$STATE_FILE" 2>/dev/null || true)
        fi
    fi
fi

# --- Phase 0: Auto-plan if --prompt given (skip if resuming with existing tasks) ---
if [[ -n "$PROMPT_FILE" && "$RESUME" != "true" ]]; then
    if [[ ! -f "$PROMPT_FILE" ]]; then
        log_error "Prompt file not found: $PROMPT_FILE"
        exit 1
    fi

    # Auto-detect OUTPUT_DIR from prompt path (e.g., demos/coupled-decisions/PROMPT.md → demos/coupled-decisions)
    if [[ -z "$OUTPUT_DIR" ]]; then
        PROMPT_DIR=$(dirname "$PROMPT_FILE")
        if [[ "$PROMPT_DIR" == demos/* ]]; then
            OUTPUT_DIR="$PROMPT_DIR"
            log_status "Auto-detected demo output directory: $OUTPUT_DIR"
        fi
    fi

    # Check if there are already open tasks (avoid re-planning on accidental restart)
    EXISTING_TASKS=$(bd list --status open --json 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
    EXISTING_PROGRESS=$(bd list --status in_progress --json 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
    if (( EXISTING_TASKS + EXISTING_PROGRESS > 0 )); then
        log_status "⚠ Found $((EXISTING_TASKS + EXISTING_PROGRESS)) existing open/in-progress tasks."
        log_status "  Skipping re-planning. Use --resume or clear Beads first."
    else
        log_action "Auto-planning from: $PROMPT_FILE"
        PLAN_ARGS=("$PROMPT_FILE")
        [[ -n "$OUTPUT_DIR" ]] && PLAN_ARGS+=("--output-dir" "$OUTPUT_DIR")
        if [[ "$DRY_RUN" == "true" ]]; then
            PLAN_ARGS+=("--dry-run")
        fi
        ./scripts/plan-tasks.sh "${PLAN_ARGS[@]}"
    fi

    # Set epic to in_progress
    EPIC_ID=$(bd list --json 2>/dev/null | jq -r '[.[] | select(.issue_type == "epic" and .status == "open")] | last | .id // empty')
    if [[ -n "$EPIC_ID" ]]; then
        bd update "$EPIC_ID" --status in_progress 2>/dev/null || true
    fi
    log_status "Planning complete. Starting autopilot loop."

    # Notify: swarm starting
    PLANNED_COUNT=$(bd list --json 2>/dev/null | jq '[.[] | select(.issue_type != "epic")] | length' 2>/dev/null || echo "?")
    notify_swarm_start "$PLANNED_COUNT" "$DOMAIN" 2>/dev/null || true
fi

# Export OUTPUT_DIR so spawn scripts can access it
export SWARM_OUTPUT_DIR="${OUTPUT_DIR:-}"
export SWARM_PROMPT_FILE="${PROMPT_FILE:-}"

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

    # --- Check convergence after merges ---
    check_convergence

    # --- Process operator inbox commands (from Telegram bridge) ---
    process_inbox

    # --- Dispatch newly ready tasks ---
    dispatch_ready

    # --- Save state (crash recovery) ---
    save_state

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

# Send Telegram notification
notify_swarm_complete "$WAVE" "$TOTAL_MERGED" "$ELAPSED_MIN" 2>/dev/null || true

# Final dashboard
write_dashboard

# --- Auto-cleanup: safe cleanup of successfully completed work ---
log_action "Running safe automatic cleanup (merged branches only)..."

# Clean up remote branches that have been merged
for _remote_branch in $(git branch -r --list 'origin/agent-*' 2>/dev/null); do
    _local_name="${_remote_branch#origin/}"
    if git branch --merged main 2>/dev/null | grep -q "$_local_name"; then
        git push origin --delete "$_local_name" 2>/dev/null || true
        log_status "  Cleaned remote: $_local_name"
    fi
done
git remote prune origin 2>/dev/null || true
git worktree prune 2>/dev/null || true

# Remove the state file on successful completion
rm -f "$STATE_FILE" 2>/dev/null || true

log_status "Cleanup complete. Verify: git branch -a | grep agent  (should be empty)"
