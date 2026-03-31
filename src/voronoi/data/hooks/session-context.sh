#!/usr/bin/env bash
# SessionStart hook: inject Beads status and project context at agent session start.
# Gives the agent immediate task awareness without needing to run discovery commands.

set -euo pipefail

INPUT=$(cat)

# Gather project context
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
HAS_REMOTE=$(git remote -v 2>/dev/null | head -1 || echo "")
BEADS_STATUS=""

if command -v bd &>/dev/null && [[ -d ".beads" ]]; then
  READY=$(bd ready 2>/dev/null | head -5 || echo "(no ready tasks)")
  BLOCKED=$(bd list --blocked 2>/dev/null | head -3 || echo "(none blocked)")
  BEADS_STATUS="Ready tasks:\n${READY}\n\nBlocked tasks:\n${BLOCKED}"
else
  BEADS_STATUS="Beads not initialized in this workspace."
fi

REMOTE_NOTE="Remote: configured"
if [[ -z "$HAS_REMOTE" ]]; then
  REMOTE_NOTE="NO_REMOTE: local-only workspace, all commits stay local"
fi

cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "PROJECT CONTEXT AT SESSION START:\nBranch: ${BRANCH}\n${REMOTE_NOTE}\n\n${BEADS_STATUS}\n\nReminder: run 'bd prime' to load full context. Read CLAUDE.md for mandatory rules."
  }
}
EOF
