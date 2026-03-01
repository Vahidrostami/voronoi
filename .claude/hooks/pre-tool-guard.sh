#!/bin/bash
# PreToolUse hook: guard against destructive commands in agent worktrees
# Receives tool context as JSON via stdin

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

# Block rm -rf on critical paths
if echo "$COMMAND" | grep -qE 'rm\s+-rf\s+(/|~|\.\.)'; then
  echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Destructive command blocked: rm -rf on critical path"}}' >&2
  exit 2
fi

# Allow everything else
exit 0
