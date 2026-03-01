#!/bin/bash
set -euo pipefail

# =============================================================================
# notify-telegram.sh — Send swarm notifications to Telegram
#
# Sends standup reports, completion alerts, or custom messages to a Telegram
# chat via the Bot API.
#
# Setup:
#   1. Create a bot with @BotFather on Telegram → get your BOT_TOKEN
#   2. Get your chat ID (send /start to your bot, then visit:
#      https://api.telegram.org/bot<TOKEN>/getUpdates)
#   3. Export env vars or write to .swarm-telegram.env:
#        TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
#        TELEGRAM_CHAT_ID=-100123456789
#
# Usage:
#   # Send a custom message:
#   ./scripts/notify-telegram.sh "Swarm complete! 🎉"
#
#   # Pipe standup report:
#   ./scripts/standup.sh | ./scripts/notify-telegram.sh --stdin
#
#   # Send standup automatically:
#   ./scripts/notify-telegram.sh --standup
#
#   # Use as autopilot notify hook:
#   ./scripts/autopilot.sh --notify "./scripts/notify-telegram.sh 'All tasks done!'"
#
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# --- Load credentials ---
# Priority: env vars > .swarm-telegram.env > .env
load_credentials() {
    local env_file

    # Try .swarm-telegram.env first
    for env_file in "$PROJECT_DIR/.swarm-telegram.env" "$PROJECT_DIR/.env"; do
        if [[ -f "$env_file" ]]; then
            # Source only TELEGRAM_ vars (safe subset)
            while IFS='=' read -r key value; do
                [[ "$key" =~ ^TELEGRAM_ ]] || continue
                [[ -z "$value" ]] && continue
                # Strip surrounding quotes
                value="${value%\"}"
                value="${value#\"}"
                value="${value%\'}"
                value="${value#\'}"
                export "$key=$value"
            done < "$env_file"
            break
        fi
    done

    if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
        echo "✗ TELEGRAM_BOT_TOKEN not set."
        echo "  Export it or create .swarm-telegram.env with:"
        echo "    TELEGRAM_BOT_TOKEN=your-bot-token"
        echo "    TELEGRAM_CHAT_ID=your-chat-id"
        exit 1
    fi

    if [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
        echo "✗ TELEGRAM_CHAT_ID not set."
        echo "  Export it or add to .swarm-telegram.env"
        exit 1
    fi
}

# --- Send message via Telegram Bot API ---
send_telegram() {
    local message="$1"
    local parse_mode="${2:-Markdown}"

    # Telegram has a 4096 char limit per message — split if needed
    local max_len=4000
    local total=${#message}

    if (( total <= max_len )); then
        _send_chunk "$message" "$parse_mode"
    else
        # Split into chunks at newline boundaries
        local chunk=""
        local part=1
        while IFS= read -r line; do
            if (( ${#chunk} + ${#line} + 1 > max_len )); then
                _send_chunk "$chunk" "$parse_mode"
                chunk=""
                part=$((part + 1))
                sleep 1  # Rate limit
            fi
            chunk="${chunk:+$chunk
}$line"
        done <<< "$message"
        # Send remaining
        [[ -n "$chunk" ]] && _send_chunk "$chunk" "$parse_mode"
    fi
}

_send_chunk() {
    local text="$1"
    local parse_mode="$2"

    local response
    response=$(curl -s -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "parse_mode=${parse_mode}" \
        -d "text=${text}" \
        --data-urlencode "text=${text}" \
        2>/dev/null) || true

    # Check for errors
    if echo "$response" | jq -e '.ok == true' >/dev/null 2>&1; then
        return 0
    else
        # Retry without parse_mode (in case markdown is invalid)
        curl -s -X POST \
            "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
            --data-urlencode "text=${text}" \
            >/dev/null 2>&1 || true
    fi
}

# --- Format standup for Telegram ---
generate_standup_message() {
    local project_name
    if [[ -f "$PROJECT_DIR/.swarm-config.json" ]]; then
        project_name=$(jq -r '.project_name // "unknown"' "$PROJECT_DIR/.swarm-config.json")
    else
        project_name=$(basename "$PROJECT_DIR")
    fi

    local header="🤖 *Agent Swarm Standup*
📁 Project: \`${project_name}\`
🕐 $(date '+%Y-%m-%d %H:%M')"

    # Task counts from Beads
    local open_count in_progress_count ready_count closed_count
    open_count=$(bd list --status open --json 2>/dev/null | jq 'length' 2>/dev/null || echo "?")
    in_progress_count=$(bd list --status in_progress --json 2>/dev/null | jq 'length' 2>/dev/null || echo "?")
    ready_count=$(bd ready --json 2>/dev/null | jq 'length' 2>/dev/null || echo "?")
    closed_count=$(bd list --status closed --json 2>/dev/null | jq 'length' 2>/dev/null || echo "?")

    local summary="
📊 *Task Summary*
  Open: ${open_count}
  In Progress: ${in_progress_count}
  Ready (unblocked): ${ready_count}
  Closed: ${closed_count}"

    # In-progress details
    local in_progress_details=""
    local tasks_json
    tasks_json=$(bd list --status in_progress --json 2>/dev/null || echo "[]")
    if [[ "$tasks_json" != "[]" ]]; then
        in_progress_details="
🔧 *In Progress*"
        while IFS= read -r line; do
            in_progress_details="${in_progress_details}
  • ${line}"
        done < <(echo "$tasks_json" | jq -r '.[] | "[\(.id)] \(.title)"' 2>/dev/null)
    fi

    # Agent branch activity
    local agent_status=""
    local swarm_dir
    swarm_dir=$(jq -r '.swarm_dir // ""' "$PROJECT_DIR/.swarm-config.json" 2>/dev/null)

    if [[ -n "$swarm_dir" ]]; then
        for worktree in "$swarm_dir"/agent-*; do
            [ -d "$worktree" ] || continue
            local branch
            branch=$(basename "$worktree")
            local commits last_activity
            commits=$(git -C "$PROJECT_DIR" log "main..$branch" --oneline 2>/dev/null | wc -l | tr -d ' ')
            last_activity=$(git -C "$PROJECT_DIR" log "$branch" -1 --format="%ar" 2>/dev/null || echo "unknown")
            agent_status="${agent_status}
  🔹 \`${branch}\` — ${commits} commits, last: ${last_activity}"
        done
    fi

    if [[ -n "$agent_status" ]]; then
        agent_status="
🏗 *Active Agents*${agent_status}"
    fi

    echo "${header}${summary}${in_progress_details}${agent_status}"
}

# --- Main ---
main() {
    load_credentials

    local mode="message"
    local message=""

    # Parse args
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --standup)
                mode="standup"
                shift
                ;;
            --stdin)
                mode="stdin"
                shift
                ;;
            *)
                message="$1"
                shift
                ;;
        esac
    done

    cd "$PROJECT_DIR"

    case "$mode" in
        standup)
            local standup_msg
            standup_msg=$(generate_standup_message)
            send_telegram "$standup_msg"
            echo "✓ Standup sent to Telegram"
            ;;
        stdin)
            local stdin_content
            stdin_content=$(cat)
            # Wrap in code block for readability
            send_telegram "📋 *Swarm Report*

\`\`\`
${stdin_content}
\`\`\`" "Markdown"
            echo "✓ Report sent to Telegram"
            ;;
        message)
            if [[ -z "$message" ]]; then
                echo "Usage: $0 <message> | --standup | --stdin"
                exit 1
            fi
            send_telegram "🤖 *Agent Swarm*: ${message}"
            echo "✓ Message sent to Telegram"
            ;;
    esac
}

main "$@"
