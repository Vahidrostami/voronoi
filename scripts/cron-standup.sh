#!/bin/bash
set -euo pipefail

# Cron-compatible standup runner
# Usage: Add to crontab: 0 9 * * 1-5 /path/to/agent-swarm-template/scripts/cron-standup.sh
#
# This script runs the standup and optionally posts results to a file or webhook.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Generate the standup report
REPORT=$("$SCRIPT_DIR/standup.sh" 2>&1)

# Write to file
REPORT_DIR="${PROJECT_DIR}/standup-reports"
mkdir -p "$REPORT_DIR"
REPORT_FILE="${REPORT_DIR}/standup-$(date +%Y-%m-%d).md"
echo "$REPORT" > "$REPORT_FILE"
echo "Standup report saved to: $REPORT_FILE"

# Optional: Post to GitHub Issue (requires gh CLI and GH_TOKEN)
if command -v gh >/dev/null 2>&1 && [ -n "${GH_TOKEN:-}" ]; then
    gh issue create \
        --title "Agent Standup — $(date +%Y-%m-%d)" \
        --body "$REPORT" \
        --label "standup,automated" 2>/dev/null || echo "⚠ Failed to create GitHub issue"
fi

# Optional: Post to webhook (set STANDUP_WEBHOOK_URL env var)
if [ -n "${STANDUP_WEBHOOK_URL:-}" ]; then
    curl -s -X POST "$STANDUP_WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"text\": $(echo "$REPORT" | jq -Rs .)}" 2>/dev/null || echo "⚠ Failed to post to webhook"
fi
