#!/bin/bash
set -euo pipefail

# Cron-compatible standup runner
# Add to crontab: 0 9 * * 1-5 /path/to/voronoi/scripts/cron-standup.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

REPORT_DIR="standup-reports"
mkdir -p "$REPORT_DIR"

REPORT_FILE="$REPORT_DIR/standup-$(date +%Y-%m-%d).md"

./scripts/standup.sh > "$REPORT_FILE" 2>&1

echo "Standup report written to $REPORT_FILE"

# Optionally post to GitHub Issues
if command -v gh >/dev/null 2>&1; then
    gh issue create \
        --title "Agent Standup — $(date +%Y-%m-%d)" \
        --body-file "$REPORT_FILE" \
        --label "standup,automated" 2>/dev/null || true
fi
