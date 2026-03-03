#!/bin/bash
set -euo pipefail

# =============================================================================
# plan-tasks.sh — LLM-powered task decomposition
#
# Reads a prompt file, calls the agent CLI to decompose it into a structured
# task graph, then creates Beads epic + tasks + dependencies automatically.
#
# Usage:
#   ./scripts/plan-tasks.sh <prompt-file> [--epic-name "name"] [--dry-run]
#
# Output: Creates Beads epic with subtasks and dependency graph.
# =============================================================================

PROMPT_FILE="${1:-}"
EPIC_NAME=""
DRY_RUN=false
OUTPUT_DIR=""

shift || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --epic-name)   EPIC_NAME="$2"; shift 2 ;;
        --dry-run)     DRY_RUN=true; shift ;;
        --output-dir)  OUTPUT_DIR="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$PROMPT_FILE" || ! -f "$PROMPT_FILE" ]]; then
    echo "Usage: ./scripts/plan-tasks.sh <prompt-file> [--epic-name \"name\"] [--dry-run]"
    exit 1
fi

CONFIG=$(cat .swarm-config.json)
AGENT_CMD=$(echo "$CONFIG" | jq -r '.agent_command // "copilot"')
AGENT_FLAGS=$(echo "$CONFIG" | jq -r '.agent_flags // "--allow-all"')
PROJECT_DIR=$(echo "$CONFIG" | jq -r '.project_dir')

cd "$PROJECT_DIR"

PROMPT_CONTENT=$(cat "$PROMPT_FILE")

# --- Generate task decomposition via LLM ---
# Write the planner instructions to a temp file first (avoids bash 3.2 heredoc-in-subshell issues)
PLANNER_TMP=$(mktemp)
cat > "$PLANNER_TMP" <<'PLAN_EOF'
You are a task planner. Read the project description below and decompose it into a structured task graph.

OUTPUT FORMAT — respond with ONLY valid JSON, no markdown fences, no explanation:

{
  "epic_name": "Short epic title",
  "tasks": [
    {
      "id": "task-1",
      "title": "Short task title",
      "description": "Detailed description of what to build. Include file paths this agent owns.",
      "priority": 2,
      "depends_on": [],
      "file_scope": ["src/path/to/files"],
      "produces": ["path/to/output/file.json"],
      "requires": [],
      "gate": null
    }
  ]
}

RULES:
1. Each task must have a clear file_scope — no overlapping files between tasks
2. depends_on references other task ids from this list
3. Priority: 1=critical (foundations), 2=normal, 3=nice-to-have
4. Tasks that can run in parallel should NOT depend on each other
5. Include a description detailed enough for an AI agent to implement independently
6. Keep tasks focused — each should be completable in under 30 minutes
7. Order tasks so foundations come first (shared interfaces, base classes, config)
8. CRITICAL — Artifact contracts:
   a. "produces" lists files/directories this task MUST create before it can be considered done
   b. "requires" lists files/directories that MUST exist before this task can start
   c. If task B uses output from task A, task B "requires" must list the file and task A "produces" must list it
   d. If the project description specifies a validation gate -- such as "X must pass before Y begins" --
      set "gate" on the downstream task to the path of the validation artifact, like "output/validation_report.json",
      AND add a gate check description in the task description, like "GATE: output/validation_report.json must contain all PASS verdicts"
9. Never let a task that consumes results -- such as paper writing or reporting -- start before the task that produces those results
10. Data-generation and experiment tasks MUST list their output data files in "produces"
11. CRITICAL — OUTPUT DIRECTORY: If an output directory is specified below, ALL file_scope paths,
    produces paths, and requires paths MUST be relative to the repository root and scoped to that directory.
    For example, if the output directory is "demos/coupled-decisions", then file_scope should be like
    "demos/coupled-decisions/src/module.py", NOT "src/module.py".
    Never put files in the repository root unless the project description explicitly says to.

PROJECT DESCRIPTION:
PLAN_EOF

# Append output directory constraint if specified
if [[ -n "$OUTPUT_DIR" ]]; then
    cat >> "$PLANNER_TMP" <<OUTDIR_EOF

IMPORTANT CONSTRAINT — OUTPUT DIRECTORY:
All work for this project MUST be scoped under: $OUTPUT_DIR/
- Source code: $OUTPUT_DIR/src/
- Output/results: $OUTPUT_DIR/output/
- All file_scope, produces, and requires paths must be relative to the repo root and start with "$OUTPUT_DIR/".
- Do NOT use the repository root for any output files.
OUTDIR_EOF
fi

PLANNER_PROMPT=$(cat "$PLANNER_TMP")
rm -f "$PLANNER_TMP"

FULL_PROMPT="$PLANNER_PROMPT

$PROMPT_CONTENT"

echo "🧠 Planning tasks from: $PROMPT_FILE"
echo "   Using: $AGENT_CMD"
echo ""

# Write the planner prompt to a temp file to avoid quoting issues
PLAN_TMP=$(mktemp)
echo "$FULL_PROMPT" > "$PLAN_TMP"

# Call the agent CLI to generate the plan
PLAN_JSON_FILE=$(mktemp)

# copilot CLI doesn't support --output-text; it outputs markdown-fenced JSON
# plus a usage summary footer. We capture everything and extract JSON below.
if $AGENT_CMD $AGENT_FLAGS --no-color -p "$(cat "$PLAN_TMP")" 2>/dev/null > "$PLAN_JSON_FILE"; then
    echo "  ✓ LLM responded"
else
    echo "✗ LLM planning failed (exit code $?)."
    # Try without --no-color in case that flag isn't supported
    if $AGENT_CMD $AGENT_FLAGS -p "$(cat "$PLAN_TMP")" 2>/dev/null > "$PLAN_JSON_FILE"; then
        echo "  ✓ LLM responded (fallback)"
    else
        echo "✗ Could not get LLM plan. Check that '$AGENT_CMD' works with '-p' flag."
        rm -f "$PLAN_TMP" "$PLAN_JSON_FILE"
        exit 1
    fi
fi
rm -f "$PLAN_TMP"

# Extract JSON from copilot output:
# 1. Strip markdown code fences (```json ... ```)
# 2. Strip the usage/stats footer that copilot appends
# 3. Extract the JSON object using sed to grab from first { to last }
RAW_OUTPUT=$(cat "$PLAN_JSON_FILE")
rm -f "$PLAN_JSON_FILE"

# Try to extract JSON between first { and last }
PLAN_JSON=$(echo "$RAW_OUTPUT" | sed -n '/^[[:space:]]*{/,/^[[:space:]]*}/p' | head -n "$(echo "$RAW_OUTPUT" | grep -c '')")

# If that didn't work, try stripping markdown fences first
if ! echo "$PLAN_JSON" | jq . >/dev/null 2>&1; then
    PLAN_JSON=$(echo "$RAW_OUTPUT" | sed '/^```/d' | sed -n '/^[[:space:]]*{/,/^[[:space:]]*}/p')
fi

# Last resort: use python to extract JSON
if ! echo "$PLAN_JSON" | jq . >/dev/null 2>&1; then
    PLAN_JSON=$(echo "$RAW_OUTPUT" | python3 -c "
import sys, json, re
text = sys.stdin.read()
# Find the first { and last } to extract JSON
start = text.find('{')
end = text.rfind('}')
if start >= 0 and end > start:
    candidate = text[start:end+1]
    try:
        obj = json.loads(candidate)
        print(json.dumps(obj))
    except json.JSONDecodeError:
        sys.exit(1)
else:
    sys.exit(1)
" 2>/dev/null) || {
        echo "✗ Could not extract valid JSON from LLM output."
        echo "Raw output:"
        echo "$RAW_OUTPUT" | head -50
        exit 1
    }
fi

# Validate JSON
if ! echo "$PLAN_JSON" | jq . >/dev/null 2>&1; then
    echo "✗ Invalid JSON from LLM. Raw output:"
    echo "$PLAN_JSON"
    exit 1
fi

# --- Parse and display the plan ---
EPIC=$(echo "$PLAN_JSON" | jq -r '.epic_name // "Untitled Epic"')
[[ -n "$EPIC_NAME" ]] && EPIC="$EPIC_NAME"
TASK_COUNT=$(echo "$PLAN_JSON" | jq '.tasks | length')

echo "📋 Plan: $EPIC ($TASK_COUNT tasks)"
echo "─────────────────────────────────────"
echo "$PLAN_JSON" | jq -r '.tasks[] | "  [\(.id)] P\(.priority) \(.title)\n    Scope: \(.file_scope | join(", "))\n    Deps: \(.depends_on | if length == 0 then "none" else join(", ") end)\n"'

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] Would create $TASK_COUNT tasks in Beads. Exiting."
    echo ""
    echo "Raw JSON:"
    echo "$PLAN_JSON" | jq .
    exit 0
fi

# --- Create Beads structure ---
echo "Creating Beads epic and tasks..."

# Create epic
EPIC_ID=$(bd create "$EPIC" -t epic -p 1 --json 2>&1 | jq -r '.id // empty' || \
          bd create "$EPIC" -t epic -p 1 2>&1 | grep -oP 'Created issue: \K\S+')
echo "  ✓ Epic: $EPIC_ID — $EPIC"

# Create tasks and build ID mapping
declare -A TASK_ID_MAP  # plan-id -> beads-id
for i in $(seq 0 $((TASK_COUNT - 1))); do
    PLAN_ID=$(echo "$PLAN_JSON" | jq -r ".tasks[$i].id")
    TITLE=$(echo "$PLAN_JSON" | jq -r ".tasks[$i].title")
    DESC=$(echo "$PLAN_JSON" | jq -r ".tasks[$i].description")
    PRIORITY=$(echo "$PLAN_JSON" | jq -r ".tasks[$i].priority")
    SCOPE=$(echo "$PLAN_JSON" | jq -r ".tasks[$i].file_scope | join(\", \")")

    PRODUCES=$(echo "$PLAN_JSON" | jq -r ".tasks[$i].produces // [] | join(\", \")")
    REQUIRES=$(echo "$PLAN_JSON" | jq -r ".tasks[$i].requires // [] | join(\", \")")
    GATE=$(echo "$PLAN_JSON" | jq -r ".tasks[$i].gate // empty")

    FULL_DESC="$DESC

File scope: $SCOPE"

    BEADS_ID=$(bd create "$TITLE" -t task -p "$PRIORITY" --parent "$EPIC_ID" \
        --description "$FULL_DESC" --json 2>&1 | jq -r '.id // empty' || \
        bd create "$TITLE" -t task -p "$PRIORITY" --parent "$EPIC_ID" \
        --description "$FULL_DESC" 2>&1 | grep -oP 'Created issue: \K\S+')

    # Store artifact contracts in Beads notes
    if [[ -n "$PRODUCES" ]]; then
        bd update "$BEADS_ID" --notes "PRODUCES:$PRODUCES" 2>/dev/null || true
    fi
    if [[ -n "$REQUIRES" ]]; then
        bd update "$BEADS_ID" --notes "REQUIRES:$REQUIRES" 2>/dev/null || true
    fi
    if [[ -n "$GATE" ]]; then
        bd update "$BEADS_ID" --notes "GATE:$GATE" 2>/dev/null || true
    fi

    TASK_ID_MAP[$PLAN_ID]="$BEADS_ID"
    echo "  ✓ Task: $BEADS_ID — $TITLE (P$PRIORITY, scope: $SCOPE)"
    [[ -n "$PRODUCES" ]] && echo "    produces: $PRODUCES"
    [[ -n "$REQUIRES" ]] && echo "    requires: $REQUIRES"
    [[ -n "$GATE" ]]     && echo "    gate: $GATE"
done

# Set dependencies
echo ""
echo "Setting dependencies..."
for i in $(seq 0 $((TASK_COUNT - 1))); do
    PLAN_ID=$(echo "$PLAN_JSON" | jq -r ".tasks[$i].id")
    BEADS_ID="${TASK_ID_MAP[$PLAN_ID]}"

    DEPS=$(echo "$PLAN_JSON" | jq -r ".tasks[$i].depends_on[]" 2>/dev/null || true)
    for DEP_PLAN_ID in $DEPS; do
        DEP_BEADS_ID="${TASK_ID_MAP[$DEP_PLAN_ID]:-}"
        if [[ -n "$DEP_BEADS_ID" ]]; then
            bd dep add "$BEADS_ID" "$DEP_BEADS_ID" 2>&1 | grep -v '^$' || true
            echo "  ✓ $BEADS_ID depends on $DEP_BEADS_ID"
        else
            echo "  ⚠ Unknown dependency: $DEP_PLAN_ID (skipping)"
        fi
    done
done

# --- Detect scientific/exploratory prompts and add convergence checkpoint ---
IS_SCIENTIFIC=false
SCIENTIFIC_KEYWORDS="experiment|validate|planted.ground.truth|hypothesis|prove|ablation|statistical|reproducib|cross.domain|generalization|scientific"
if echo "$PROMPT_CONTENT" | grep -qiE "$SCIENTIFIC_KEYWORDS"; then
    IS_SCIENTIFIC=true
fi

if [[ "$IS_SCIENTIFIC" == "true" ]]; then
    echo ""
    echo "🔬 Scientific prompt detected — adding convergence checkpoint"

    # Find the validation task (looks for tasks with validation/validate in title)
    VALIDATION_TASK_ID=""
    for plan_id in "${!TASK_ID_MAP[@]}"; do
        beads_id="${TASK_ID_MAP[$plan_id]}"
        task_title=$(echo "$PLAN_JSON" | jq -r ".tasks[] | select(.id==\"$plan_id\") | .title" 2>/dev/null || true)
        if echo "$task_title" | grep -qiE "validat"; then
            VALIDATION_TASK_ID="$beads_id"
            break
        fi
    done

    # Find the paper/report task (should depend on convergence)
    PAPER_TASK_ID=""
    for plan_id in "${!TASK_ID_MAP[@]}"; do
        beads_id="${TASK_ID_MAP[$plan_id]}"
        task_title=$(echo "$PLAN_JSON" | jq -r ".tasks[] | select(.id==\"$plan_id\") | .title" 2>/dev/null || true)
        if echo "$task_title" | grep -qiE "paper|report|write.up|latex|deliverable"; then
            PAPER_TASK_ID="$beads_id"
            break
        fi
    done

    # Determine convergence gate path
    CONV_GATE_PATH="output/convergence.json"
    [[ -n "$OUTPUT_DIR" ]] && CONV_GATE_PATH="${OUTPUT_DIR}/output/convergence.json"

    # Mark validation task with convergence metadata
    if [[ -n "$VALIDATION_TASK_ID" ]]; then
        bd update "$VALIDATION_TASK_ID" --notes "CONVERGENCE_CHECKPOINT | TRIGGERS_JUDGE:true" 2>/dev/null || true
        echo "  ✓ Marked $VALIDATION_TASK_ID as convergence checkpoint"
    fi

    # If there's a paper task, add convergence.json as its GATE
    if [[ -n "$PAPER_TASK_ID" ]]; then
        bd update "$PAPER_TASK_ID" --notes "GATE:$CONV_GATE_PATH" 2>/dev/null || true
        echo "  ✓ Paper task $PAPER_TASK_ID gated on convergence"
    fi

    echo "  Convergence gate: $CONV_GATE_PATH"
    echo "  Autopilot will run convergence-judge.sh after validation completes"
fi

echo ""
echo "═══════════════════════════════════════"
echo "✅ Plan created: $EPIC_ID with $TASK_COUNT tasks"
[[ "$IS_SCIENTIFIC" == "true" ]] && echo "   🔬 Scientific mode: convergence loop enabled"
echo ""
echo "Next steps:"
echo "  bd list                    # Review the plan"
echo "  bd ready                   # See what's unblocked"
echo "  ./scripts/autopilot.sh     # Run it autonomously"
echo "═══════════════════════════════════════"
