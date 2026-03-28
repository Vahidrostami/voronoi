#!/bin/bash
# =============================================================================
# health-check.sh — Lightweight liveness probe for Voronoi pipeline sessions
#
# Auto-discovers ALL voronoi-related tmux sessions (orchestrators, swarms,
# and investigation sessions) and checks every window/pane for liveness.
#
# Detection method:
#   1. Hashes pane output — if unchanged for too long → stale/stuck
#   2. Checks git commit recency on agent branches
#   3. Checks process tree — if shell has no children → exited
#
# Session discovery (no config file required):
#   - voronoi-inv-*     →  orchestrator sessions (from dispatcher)
#   - *-swarm           →  swarm sessions (from swarm-init.sh)
#   - Also reads .swarm-config.json if present
#
# Usage:
#   ./scripts/health-check.sh                  # one-shot check
#   ./scripts/health-check.sh --watch [SECS]   # continuous (default 120s)
#   ./scripts/health-check.sh --json            # machine-readable output
#   ./scripts/health-check.sh --session NAME    # check a specific session
#
# Exit codes:
#   0 — all agents healthy
#   1 — one or more agents stuck
#   2 — no voronoi sessions found
# =============================================================================
set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
WATCH=false
INTERVAL=120          # seconds between checks in watch mode
STALE_THRESHOLD=600   # seconds with no pane change → warning
DEAD_THRESHOLD=1800   # seconds with no pane change AND no commits → stuck
JSON_OUTPUT=false
SNAPSHOT_DIR="${TMPDIR:-/tmp}/voronoi-health"
NOTIFY=true
FILTER_SESSION=""     # check all discovered sessions by default

# ── Parse args ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --watch)   WATCH=true; INTERVAL="${2:-120}"; [[ "${2:-}" =~ ^[0-9]+$ ]] && shift; shift ;;
        --json)    JSON_OUTPUT=true; shift ;;
        --no-notify) NOTIFY=false; shift ;;
        --threshold) STALE_THRESHOLD="$2"; shift 2 ;;
        --dead)    DEAD_THRESHOLD="$2"; shift 2 ;;
        --session) FILTER_SESSION="$2"; shift 2 ;;
        *) echo "Unknown flag: $1"; exit 2 ;;
    esac
done

# ── Helpers ──────────────────────────────────────────────────────────────────
ts() { date +%s; }
iso() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

log() {
    if [[ "$JSON_OUTPUT" == "false" ]]; then
        echo "[$(date +%H:%M:%S)] $*"
    fi
}

die() { echo "✗ $*" >&2; exit 2; }

# ── Discover sessions ────────────────────────────────────────────────────────
# Auto-discover all voronoi-related tmux sessions. No config file required.
discover_sessions() {
    local sessions=()

    # Get all live tmux sessions
    local all_sessions
    all_sessions=$(tmux list-sessions -F '#{session_name}' 2>/dev/null || true)
    if [[ -z "$all_sessions" ]]; then
        return
    fi

    while IFS= read -r s; do
        # Match: voronoi-inv-* (orchestrator), *-swarm (agent swarms)
        if [[ "$s" == voronoi-inv-* ]] || [[ "$s" == *-swarm ]]; then
            sessions+=("$s")
        fi
    done <<< "$all_sessions"

    # Also include session from .swarm-config.json if present and not already listed
    local config_session=""
    local config_file=".swarm-config.json"
    if [[ ! -f "$config_file" ]]; then
        for parent in .. ../.. ../../..; do
            [[ -f "$parent/$config_file" ]] && { config_file="$parent/$config_file"; break; }
        done
    fi
    if [[ -f "$config_file" ]]; then
        config_session=$(jq -r '.tmux_session // empty' "$config_file" 2>/dev/null || true)
        if [[ -n "$config_session" ]]; then
            local already=false
            for s in "${sessions[@]+"${sessions[@]}"}"; do
                [[ "$s" == "$config_session" ]] && { already=true; break; }
            done
            if [[ "$already" == "false" ]] && tmux has-session -t "$config_session" 2>/dev/null; then
                sessions+=("$config_session")
            fi
        fi
    fi

    printf '%s\n' "${sessions[@]+"${sessions[@]}"}"
}

# Try to find a git project dir for commit-age checks.
# Uses .swarm-config.json if available, otherwise the workspace start_directory
# from the tmux session, otherwise cwd.
find_project_dir() {
    local session="$1"
    # From config
    local config_file=".swarm-config.json"
    if [[ ! -f "$config_file" ]]; then
        for parent in .. ../.. ../../..; do
            [[ -f "$parent/$config_file" ]] && { config_file="$parent/$config_file"; break; }
        done
    fi
    if [[ -f "$config_file" ]]; then
        local dir
        dir=$(jq -r '.project_dir // empty' "$config_file" 2>/dev/null || true)
        if [[ -n "$dir" && -d "$dir/.git" ]]; then
            echo "$dir"
            return
        fi
    fi
    # From tmux session start directory
    local tmux_dir
    tmux_dir=$(tmux display-message -t "$session" -p '#{session_path}' 2>/dev/null || true)
    if [[ -n "$tmux_dir" && -d "$tmux_dir/.git" ]]; then
        echo "$tmux_dir"
        return
    fi
    # Fallback to cwd
    pwd
}

mkdir -p "$SNAPSHOT_DIR"

# ── Core: check one window in a session ──────────────────────────────────────
check_window() {
    local session="$1"
    local window="$2"
    local project_dir="$3"
    local now
    now=$(ts)

    # Include session in snapshot key to avoid collisions across sessions
    local key="${session}__${window}"
    local snap_file="${SNAPSHOT_DIR}/${key}.snap"
    local ts_file="${SNAPSHOT_DIR}/${key}.ts"

    # Capture current pane content (last 50 lines, stripped of blanks)
    local current
    current=$(tmux capture-pane -t "${session}:${window}" -p 2>/dev/null | grep -v '^$' | tail -50 || true)

    # Hash the content for cheap comparison
    local current_hash
    current_hash=$(printf '%s' "$current" | shasum -a 256 | cut -d' ' -f1)

    local prev_hash=""
    [[ -f "$snap_file" ]] && prev_hash=$(cat "$snap_file")

    local last_change="$now"
    [[ -f "$ts_file" ]] && last_change=$(cat "$ts_file")

    # If output changed, update snapshot
    if [[ "$current_hash" != "$prev_hash" ]]; then
        printf '%s' "$current_hash" > "$snap_file"
        printf '%s' "$now" > "$ts_file"
        last_change="$now"
    fi

    local age=$(( now - last_change ))

    # Check git activity on this branch (if it's an agent branch)
    local recent_commit_age=999999
    if [[ "$window" == agent-* && -d "$project_dir/.git" ]]; then
        local commit_epoch
        commit_epoch=$(cd "$project_dir" && git log "$window" -1 --format='%ct' 2>/dev/null || echo "0")
        if [[ "$commit_epoch" -gt 0 ]]; then
            recent_commit_age=$(( now - commit_epoch ))
        fi
    fi

    # Check if pane has a running process
    local pane_pid
    pane_pid=$(tmux list-panes -t "${session}:${window}" -F '#{pane_pid}' 2>/dev/null | head -1 || echo "")
    local has_child=false
    if [[ -n "$pane_pid" ]]; then
        # Check if the shell has child processes (the actual agent)
        local children
        children=$(pgrep -P "$pane_pid" 2>/dev/null | wc -l | tr -d ' ')
        [[ "$children" -gt 0 ]] && has_child=true
    fi

    # Determine role for display
    local role="agent"
    if [[ "$window" == "orchestrator" ]] || [[ "$session" == voronoi-inv-* && $(tmux list-windows -t "$session" -F '#{window_name}' 2>/dev/null | wc -l | tr -d ' ') -eq 1 ]]; then
        role="orchestrator"
    elif [[ "$window" == "telegram" ]]; then
        role="bridge"
    fi

    # Classify health
    local status="healthy"
    local detail=""

    if [[ "$has_child" == "false" ]]; then
        status="exited"
        detail="No running process in pane"
    elif [[ "$age" -ge "$DEAD_THRESHOLD" && "$recent_commit_age" -ge "$DEAD_THRESHOLD" ]]; then
        status="stuck"
        detail="No output change for ${age}s, no commits for ${recent_commit_age}s"
    elif [[ "$age" -ge "$STALE_THRESHOLD" ]]; then
        status="stale"
        detail="No output change for ${age}s (may be working on a long operation)"
    fi

    # Get last line of output for context
    local last_line
    last_line=$(printf '%s' "$current" | tail -1 | cut -c1-100)

    # Return structured result (8 fields)
    printf '%s\t%s\t%s\t%d\t%d\t%s\t%s\t%s\t%s\n' \
        "$session" "$window" "$status" "$age" "$recent_commit_age" "$has_child" "$role" "$detail" "$last_line"
}

# ── Compute session uptime ───────────────────────────────────────────────────
session_uptime() {
    local session="$1"
    local created
    created=$(tmux display-message -t "$session" -p '#{session_created}' 2>/dev/null || echo "0")
    if [[ "$created" -gt 0 ]]; then
        local now
        now=$(ts)
        echo $(( now - created ))
    else
        echo 0
    fi
}

format_duration() {
    local secs="$1"
    if [[ "$secs" -ge 86400 ]]; then
        echo "$((secs / 86400))d$((secs % 86400 / 3600))h"
    elif [[ "$secs" -ge 3600 ]]; then
        echo "$((secs / 3600))h$((secs % 3600 / 60))m"
    elif [[ "$secs" -ge 60 ]]; then
        echo "$((secs / 60))m"
    else
        echo "${secs}s"
    fi
}

# ── Core: check all sessions ────────────────────────────────────────────────
run_check() {
    local sessions
    if [[ -n "$FILTER_SESSION" ]]; then
        tmux has-session -t "$FILTER_SESSION" 2>/dev/null || die "Tmux session '$FILTER_SESSION' not found."
        sessions="$FILTER_SESSION"
    else
        sessions=$(discover_sessions)
    fi

    if [[ -z "$sessions" ]]; then
        die "No Voronoi tmux sessions found. Is the pipeline running?"
    fi

    local all_results=()
    local any_stuck=false
    local any_exited=false
    local total_windows=0

    while IFS= read -r sess; do
        local project_dir
        project_dir=$(find_project_dir "$sess")

        local windows
        windows=$(tmux list-windows -t "$sess" -F '#{window_name}' 2>/dev/null || true)
        [[ -z "$windows" ]] && continue

        while IFS= read -r win; do
            local result
            result=$(check_window "$sess" "$win" "$project_dir")
            all_results+=("$result")
            total_windows=$(( total_windows + 1 ))

            local status
            status=$(echo "$result" | cut -f3)
            [[ "$status" == "stuck" ]] && any_stuck=true
            [[ "$status" == "exited" ]] && any_exited=true
        done <<< "$windows"
    done <<< "$sessions"

    if [[ "$JSON_OUTPUT" == "true" ]]; then
        emit_json "${all_results[@]}"
    else
        emit_table "$sessions" "${all_results[@]}"
    fi

    # Send Telegram alert if stuck agents found
    if [[ "$any_stuck" == "true" && "$NOTIFY" == "true" ]]; then
        local stuck_list=""
        for r in "${all_results[@]}"; do
            IFS=$'\t' read -r sess win status _ _ _ _ detail _ <<< "$r"
            [[ "$status" == "stuck" ]] && stuck_list="${stuck_list}\n• \`${sess}:${win}\`: ${detail}"
        done
        local script_dir
        script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        if [[ -f "${script_dir}/notify-telegram.sh" ]]; then
            source "${script_dir}/notify-telegram.sh" 2>/dev/null || true
            notify_telegram "health_alert" "🔴 Stuck agents detected:${stuck_list}" 2>/dev/null || true
        fi
    fi

    [[ "$any_stuck" == "true" ]] && return 1
    return 0
}

# ── JSON output ──────────────────────────────────────────────────────────────
emit_json() {
    local results=("$@")
    echo "["
    local first=true
    for r in "${results[@]}"; do
        IFS=$'\t' read -r sess win status age commit_age has_child role detail last_line <<< "$r"
        [[ "$first" == "true" ]] && first=false || echo ","
        cat <<EOF
  {
    "session": "$sess",
    "window": "$win",
    "role": "$role",
    "status": "$status",
    "pane_idle_secs": $age,
    "commit_idle_secs": $commit_age,
    "has_process": $has_child,
    "detail": "$(echo "$detail" | sed 's/"/\\"/g')",
    "last_output": "$(echo "$last_line" | sed 's/"/\\"/g')",
    "checked_at": "$(iso)"
  }
EOF
    done
    echo "]"
}

# ── Pretty table output ─────────────────────────────────────────────────────
emit_table() {
    local sessions="$1"; shift
    local results=("$@")

    # Summary header
    local sess_count
    sess_count=$(echo "$sessions" | wc -l | tr -d ' ')
    local healthy=0 stale=0 stuck=0 exited=0
    for r in "${results[@]}"; do
        local s
        s=$(echo "$r" | cut -f3)
        case "$s" in
            healthy) healthy=$(( healthy + 1 )) ;;
            stale)   stale=$(( stale + 1 )) ;;
            stuck)   stuck=$(( stuck + 1 )) ;;
            exited)  exited=$(( exited + 1 )) ;;
        esac
    done

    echo
    echo "═══════════════════════════════════════════════════════════════════════"
    echo " VORONOI HEALTH CHECK   $(date '+%Y-%m-%d %H:%M:%S')"
    echo " Sessions: ${sess_count}   Windows: ${#results[@]}   ✅${healthy} ⚠️${stale} 🔴${stuck} ⚫${exited}"
    echo "═══════════════════════════════════════════════════════════════════════"

    # Group by session
    local current_session=""
    for r in "${results[@]}"; do
        IFS=$'\t' read -r sess win status age commit_age has_child role detail last_line <<< "$r"

        if [[ "$sess" != "$current_session" ]]; then
            current_session="$sess"
            local uptime
            uptime=$(session_uptime "$sess")
            echo
            echo "┌─ $sess  (uptime: $(format_duration "$uptime"))"
            printf "│ %-22s %-7s %-12s %10s %10s %4s  %s\n" "WINDOW" "ROLE" "STATUS" "PANE_IDLE" "GIT_IDLE" "PROC" "DETAIL"
            printf '│%.0s' ; printf ' %.0s─' {1..55}; echo
        fi

        local icon
        case "$status" in
            healthy) icon="✅" ;;
            stale)   icon="⚠️ " ;;
            stuck)   icon="🔴" ;;
            exited)  icon="⚫" ;;
            *)       icon="?" ;;
        esac

        local age_fmt
        age_fmt=$(format_duration "$age")
        local commit_fmt
        if [[ "$commit_age" -ge 999999 ]]; then
            commit_fmt="n/a"
        else
            commit_fmt=$(format_duration "$commit_age")
        fi

        local proc_icon="🟢"
        [[ "$has_child" == "false" ]] && proc_icon="⚫"

        printf "│ %-22s %-7s %s %-10s %10s %10s %4s  %s\n" \
            "$win" "$role" "$icon" "$status" "$age_fmt" "$commit_fmt" "$proc_icon" "$detail"
    done

    echo
}

# ── Main ─────────────────────────────────────────────────────────────────────
if [[ "$WATCH" == "true" ]]; then
    log "Health check running every ${INTERVAL}s (stale=${STALE_THRESHOLD}s, dead=${DEAD_THRESHOLD}s)"
    log "Press Ctrl+C to stop"
    while true; do
        run_check || true
        sleep "$INTERVAL"
    done
else
    run_check
fi
