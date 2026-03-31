#!/usr/bin/env bash
# PreToolUse hook: protect raw data and prevent destructive commands.
# Blocks rm -rf on data/raw/, git reset --hard, and DROP TABLE commands.

set -euo pipefail

INPUT=$(cat)

TOOL=$(echo "$INPUT" | python3 -c "
import sys, json
print(json.load(sys.stdin).get('tool_name', ''))
" 2>/dev/null || true)

# Only check terminal/execute tools
case "$TOOL" in
  execute|run_in_terminal|terminal) ;;
  *) exit 0 ;;
esac

# Extract the command being run
CMD=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ti = d.get('tool_input', {})
print(ti.get('command', '') or ti.get('input', ''))
" 2>/dev/null || true)

# Block destructive patterns on raw data
if echo "$CMD" | grep -qiE '(rm\s+(-rf?|--recursive)\s+.*data/raw|rm\s+data/raw)'; then
  cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "BLOCKED: Deleting raw data is forbidden. Move unwanted data to data/archived/ instead."
  }
}
EOF
  exit 0
fi

# Block git reset --hard (destroys uncommitted work)
if echo "$CMD" | grep -qiE 'git\s+reset\s+--hard'; then
  cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask",
    "permissionDecisionReason": "WARNING: git reset --hard destroys uncommitted work. Are you sure?"
  }
}
EOF
  exit 0
fi

# Block DROP TABLE (data destruction)
if echo "$CMD" | grep -qiE 'DROP\s+TABLE'; then
  cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "BLOCKED: DROP TABLE commands are forbidden in investigation workspaces."
  }
}
EOF
  exit 0
fi
