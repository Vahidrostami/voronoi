#!/usr/bin/env bash
# PostToolUse hook: remind agent of spec-first + test rules after source edits.
# Receives JSON on stdin from VS Code. Fires once per session, only for source file edits.
#
# VS Code hook field names (snake_case): tool_name, tool_input, tool_input.filePath
# See: https://code.visualstudio.com/docs/copilot/customization/hooks

set -euo pipefail

INPUT=$(cat)

# Extract tool name — only trigger for file-edit tools
TOOL=$(echo "$INPUT" | python3 -c "
import sys, json
print(json.load(sys.stdin).get('tool_name', ''))
" 2>/dev/null || true)

case "$TOOL" in
  replace_string_in_file|multi_replace_string_in_file|create_file) ;;
  *) exit 0 ;;
esac

# Extract file path from tool input
FILE=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ti = d.get('tool_input', {})
print(ti.get('filePath', '') or ti.get('file', ''))
" 2>/dev/null || true)

# Only trigger for voronoi source files
case "$FILE" in
  */src/voronoi/*.py) ;;
  *) exit 0 ;;
esac

# Fire on EVERY source-file edit — spec drift happens on the 2nd edit, not the 1st.
# Inject context into the agent's conversation
cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "MANDATORY CHECKLIST — you just edited voronoi source code:\n1. Did you read the relevant spec section BEFORE this edit? If not, read it now (check the scoped .instructions.md for this module).\n2. If behavior changed: update the spec in docs/ in the same commit.\n3. Before committing: run `python -m pytest tests/ -x -q` and update tests if behavior changed.\nDo NOT skip these steps."
  }
}
EOF
