#!/bin/bash
# =============================================================================
# notify-telegram.sh — Telegram notification helper for Voronoi swarm events
#
# Sends milestone notifications to a Telegram chat via either:
#   1. Direct Telegram Bot API (standalone, no MVCHA required)
#   2. MVCHA gateway (richer formatting, live-edit, requires MVCHA running)
#
# Usage (sourced by other scripts):
#   source ./scripts/notify-telegram.sh
#   notify_telegram "swarm_start" "🚀 Swarm started: 12 tasks planned"
#
# Usage (standalone):
#   ./scripts/notify-telegram.sh <event> <message> [--details "extra info"]
#
# Configuration via .swarm-config.json:
#   "notifications": {
#     "telegram": {
#       "enabled": true,
#       "bot_token": "123456:ABC...",
#       "chat_id": "-1001234567890",
#       "events": ["swarm_start", "wave_dispatch", "merge", "quality_gate_fail",
#                  "convergence", "swarm_complete", "agent_timeout", "agent_retry"],
#       "mvcha_gateway_url": "http://localhost:3000",
#       "mvcha_api_secret": "",
#       "prefer_mvcha": false
#     }
#   }
#
# Environment variables (override config):
#   VORONOI_TG_BOT_TOKEN    — Telegram bot token
#   VORONOI_TG_CHAT_ID      — Telegram chat ID
#   VORONOI_TG_EVENTS       — Comma-separated event filter (empty = all)
#   VORONOI_TG_MVCHA_URL    — MVCHA gateway URL (enables MVCHA mode)
#   VORONOI_TG_MVCHA_SECRET — MVCHA API secret
#   VORONOI_TG_PREFER_MVCHA — "true" to prefer MVCHA gateway over direct API
# =============================================================================

# Guard against double-sourcing
[[ -n "${_NOTIFY_TELEGRAM_LOADED:-}" ]] && return 0 2>/dev/null || true
_NOTIFY_TELEGRAM_LOADED=1

# --- Load .env file ---
_ntg_load_dotenv() {
    local env_file="${PROJECT_DIR:-.}/.env"
    if [[ -f "$env_file" ]]; then
        # Source .env, only exporting lines that look like KEY=VALUE (skip comments/blanks)
        while IFS= read -r line; do
            # Skip empty lines and comments
            [[ -z "$line" || "$line" == \#* ]] && continue
            # Only process lines with = that aren't already set
            if [[ "$line" == *=* ]]; then
                local key="${line%%=*}"
                key=$(echo "$key" | xargs)  # trim whitespace
                local val="${line#*=}"
                val=$(echo "$val" | xargs)  # trim whitespace
                # Only set if not already in environment
                local existing=""
                existing=$(eval "echo \"\${${key}:-}\"" 2>/dev/null) || true
                if [[ -z "$existing" ]]; then
                    export "${key}=${val}" 2>/dev/null || true
                fi
            fi
        done < "$env_file"
    fi
}

# --- Load config ---
_ntg_load_config() {
    # Load .env first (environment vars take precedence over .swarm-config.json)
    _ntg_load_dotenv

    local config_file="${PROJECT_DIR:-.}/.swarm-config.json"
    if [[ ! -f "$config_file" ]]; then
        # No config file — fall back to env vars only
        _NTG_ENABLED="false"
        _NTG_BOT_TOKEN="${VORONOI_TG_BOT_TOKEN:-}"
        _NTG_CHAT_ID="${VORONOI_TG_CHAT_ID:-}"
        _NTG_EVENTS="${VORONOI_TG_EVENTS:-}"
        _NTG_MVCHA_URL="${VORONOI_TG_MVCHA_URL:-}"
        _NTG_MVCHA_SECRET="${VORONOI_TG_MVCHA_SECRET:-}"
        _NTG_PREFER_MVCHA="${VORONOI_TG_PREFER_MVCHA:-false}"
        _NTG_PROJECT_NAME="voronoi"
        # Auto-enable if token and chat_id are set
        if [[ -n "$_NTG_BOT_TOKEN" && -n "$_NTG_CHAT_ID" ]]; then
            _NTG_ENABLED="true"
        fi
        return 0
    fi

    # Read telegram notification config
    _NTG_ENABLED=$(jq -r '.notifications.telegram.enabled // false' "$config_file" 2>/dev/null || echo "false")
    _NTG_BOT_TOKEN="${VORONOI_TG_BOT_TOKEN:-$(jq -r '.notifications.telegram.bot_token // empty' "$config_file" 2>/dev/null || true)}"
    _NTG_CHAT_ID="${VORONOI_TG_CHAT_ID:-$(jq -r '.notifications.telegram.chat_id // empty' "$config_file" 2>/dev/null || true)}"
    _NTG_EVENTS="${VORONOI_TG_EVENTS:-$(jq -r '.notifications.telegram.events // [] | join(",")' "$config_file" 2>/dev/null || true)}"
    _NTG_MVCHA_URL="${VORONOI_TG_MVCHA_URL:-$(jq -r '.notifications.telegram.mvcha_gateway_url // empty' "$config_file" 2>/dev/null || true)}"
    _NTG_MVCHA_SECRET="${VORONOI_TG_MVCHA_SECRET:-$(jq -r '.notifications.telegram.mvcha_api_secret // empty' "$config_file" 2>/dev/null || true)}"
    _NTG_PREFER_MVCHA="${VORONOI_TG_PREFER_MVCHA:-$(jq -r '.notifications.telegram.prefer_mvcha // false' "$config_file" 2>/dev/null || echo "false")}"
    _NTG_PROJECT_NAME=$(jq -r '.project_name // "voronoi"' "$config_file" 2>/dev/null || echo "voronoi")

    # Environment variables override config "enabled"
    if [[ -n "$_NTG_BOT_TOKEN" && -n "$_NTG_CHAT_ID" ]]; then
        _NTG_ENABLED="true"
    fi

    return 0
}

# --- Event filter check ---
_ntg_event_allowed() {
    local event="$1"
    # Empty filter = all events allowed
    [[ -z "$_NTG_EVENTS" ]] && return 0
    echo ",$_NTG_EVENTS," | grep -q ",$event," && return 0
    return 1
}

# --- Send via direct Telegram Bot API ---
_ntg_send_direct() {
    local text="$1"

    if [[ -z "$_NTG_BOT_TOKEN" || -z "$_NTG_CHAT_ID" ]]; then
        return 1
    fi

    local response
    response=$(curl -s --max-time 10 \
        "https://api.telegram.org/bot${_NTG_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${_NTG_CHAT_ID}" \
        -d "parse_mode=Markdown" \
        -d "text=${text}" \
        -d "disable_web_page_preview=true" 2>/dev/null)

    # Check for Markdown parse failure, retry as plain text
    if echo "$response" | grep -q '"ok":false' 2>/dev/null; then
        curl -s --max-time 10 \
            "https://api.telegram.org/bot${_NTG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${_NTG_CHAT_ID}" \
            -d "text=${text}" \
            -d "disable_web_page_preview=true" 2>/dev/null >/dev/null
    fi

    return 0
}

# --- Send via MVCHA gateway ---
_ntg_send_mvcha() {
    local text="$1"
    local event="$2"

    if [[ -z "$_NTG_MVCHA_URL" ]]; then
        return 1
    fi

    # Check if MVCHA gateway is alive
    local health
    health=$(curl -s --max-time 3 "${_NTG_MVCHA_URL}/health" 2>/dev/null || echo "")
    if ! echo "$health" | grep -q '"ok"' 2>/dev/null; then
        return 1
    fi

    # Use a synthetic task ID for routing
    local task_id="voronoi-${_NTG_PROJECT_NAME}-$(date +%s)"

    # First register the task source so MVCHA knows where to send
    # We create a task-update with a "response" step (always sends new message)
    local headers=(-H "Content-Type: application/json")
    if [[ -n "$_NTG_MVCHA_SECRET" ]]; then
        headers+=(-H "X-API-Secret: $_NTG_MVCHA_SECRET")
    fi

    curl -s --max-time 5 \
        "${_NTG_MVCHA_URL}/api/task-update" \
        "${headers[@]}" \
        -d "{
            \"taskId\": \"$task_id\",
            \"step\": \"response\",
            \"status\": \"completed\",
            \"details\": $(echo "$text" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"$text\""),
            \"progress\": 1.0
        }" 2>/dev/null >/dev/null

    return $?
}

# --- Main notification function ---
# Usage: notify_telegram <event> <message> [--progress 0.5] [--details "extra"]
notify_telegram() {
    local event="${1:-}"
    local message="${2:-}"
    local progress=""
    local details=""

    shift 2 || true
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --progress) progress="$2"; shift 2 ;;
            --details)  details="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    # Load config if not already loaded
    if [[ -z "${_NTG_ENABLED:-}" ]]; then
        _ntg_load_config || return 0
    fi

    # Bail if disabled
    [[ "$_NTG_ENABLED" != "true" ]] && return 0

    # Check event filter
    _ntg_event_allowed "$event" || return 0

    # Format the message
    local formatted="🔷 *Voronoi — ${_NTG_PROJECT_NAME}*\n\n${message}"
    if [[ -n "$details" ]]; then
        formatted+="\n\n_${details}_"
    fi

    # Try preferred method first, fall back to other
    if [[ "$_NTG_PREFER_MVCHA" == "true" ]]; then
        _ntg_send_mvcha "$formatted" "$event" 2>/dev/null || \
        _ntg_send_direct "$formatted" 2>/dev/null || true
    else
        _ntg_send_direct "$formatted" 2>/dev/null || \
        _ntg_send_mvcha "$formatted" "$event" 2>/dev/null || true
    fi
}

# --- Convenience functions for common events ---

notify_swarm_start() {
    local task_count="${1:-?}"
    local domain="${2:-code}"
    notify_telegram "swarm_start" \
        "🚀 *Swarm started*\n📋 ${task_count} tasks planned\n🏷 Domain: ${domain}"
}

notify_wave_dispatch() {
    local wave="${1:-?}"
    local agent_count="${2:-?}"
    local ready_count="${3:-?}"
    notify_telegram "wave_dispatch" \
        "📦 *Wave ${wave}*: dispatched ${agent_count} agents\n⏳ ${ready_count} tasks still ready"
}

notify_merge() {
    local branch="${1:-?}"
    local task_id="${2:-?}"
    local total_merged="${3:-?}"
    notify_telegram "merge" \
        "🔀 *Merged* \`${branch}\`\n🎫 Task: ${task_id}\n📊 Total merged: ${total_merged}"
}

notify_quality_gate() {
    local branch="${1:-?}"
    local result="${2:-?}"  # "pass" or "fail"
    local task_id="${3:-?}"
    if [[ "$result" == "pass" ]]; then
        notify_telegram "quality_gate_pass" \
            "✅ *QG passed*: \`${branch}\` (${task_id})"
    else
        notify_telegram "quality_gate_fail" \
            "❌ *QG failed*: \`${branch}\` (${task_id})"
    fi
}

notify_convergence() {
    local verdict="${1:-?}"
    local iteration="${2:-?}"
    local max_iter="${3:-?}"
    case "$verdict" in
        CONVERGED)
            notify_telegram "convergence" \
                "🎯 *CONVERGED* after ${iteration}/${max_iter} iterations\nAll validation stages passed!" ;;
        ITERATE)
            notify_telegram "convergence" \
                "🔄 *ITERATE* — iteration ${iteration}/${max_iter}\nImprovement tasks created, re-running" ;;
        EXHAUSTED|DIMINISHING_RETURNS)
            notify_telegram "convergence" \
                "⚠️ *${verdict}* — iteration ${iteration}/${max_iter}\nProceeding with limitations disclosure" ;;
    esac
}

notify_agent_timeout() {
    local branch="${1:-?}"
    local task_id="${2:-?}"
    local timeout="${3:-?}"
    notify_telegram "agent_timeout" \
        "⏰ *Agent timed out*: \`${branch}\` (${task_id}) after ${timeout}s"
}

notify_agent_retry() {
    local branch="${1:-?}"
    local attempt="${2:-?}"
    local max_retries="${3:-?}"
    notify_telegram "agent_retry" \
        "🔄 *Retry* \`${branch}\`: attempt ${attempt}/${max_retries}"
}

notify_swarm_complete() {
    local waves="${1:-?}"
    local merged="${2:-?}"
    local runtime_min="${3:-?}"
    notify_telegram "swarm_complete" \
        "🏁 *Swarm complete!*\n\n📊 Waves: ${waves}\n✅ Merged: ${merged}\n⏱ Runtime: ${runtime_min}m"
}

notify_inbox_command() {
    local action="${1:-?}"
    local detail="${2:-}"
    notify_telegram "inbox_command" \
        "📨 *Operator command received*\nAction: \`${action}\`" \
        --details "$detail"
}

# --- If called directly (not sourced), run the notification ---
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    _ntg_load_config
    event="${1:-test}"
    message="${2:-Test notification from Voronoi}"
    shift 2 || true
    notify_telegram "$event" "$message" "$@"
fi
