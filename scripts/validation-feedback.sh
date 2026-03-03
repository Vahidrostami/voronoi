#!/bin/bash
set -euo pipefail

# =============================================================================
# validation-feedback.sh — Parse validation failures → create improvement tasks
#
# Reads validation_report.json, diagnoses failures via LLM, creates Beads tasks.
#
# Usage:
#   ./scripts/validation-feedback.sh <validation-report> <parent-task-id> [--output-dir DIR]
# =============================================================================

VALIDATION_REPORT="$1"
PARENT_TASK="${2:-}"
OUTPUT_DIR=""

shift 2 || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        *) shift ;;
    esac
done

if [[ ! -f "$VALIDATION_REPORT" ]]; then
    echo "✗ Validation report not found: $VALIDATION_REPORT"
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

CONFIG=$(cat .swarm-config.json)
AGENT_CMD=$(echo "$CONFIG" | jq -r '.agent_command // "copilot"')
AGENT_FLAGS=$(echo "$CONFIG" | jq -r '.agent_flags // "--allow-all"')

# --- Extract failures from validation report ---
FAILURES_JSON=$(python3 -c "
import json, sys
with open('$VALIDATION_REPORT') as f:
    report = json.load(f)

failures = []
for stage in report.get('stages', []):
    if stage.get('verdict') in ('FAIL', 'WARN'):
        failures.append({
            'stage': stage.get('stage_name', ''),
            'verdict': stage.get('verdict', ''),
            'issues': stage.get('issues_found', []),
        })

# Include unresolved concerns
for concern in report.get('unresolved_concerns', []):
    failures.append({
        'stage': 'unresolved',
        'verdict': 'CONCERN',
        'issues': [concern],
    })

print(json.dumps(failures))
")

FAILURE_COUNT=$(echo "$FAILURES_JSON" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")

if [[ "$FAILURE_COUNT" -eq 0 ]]; then
    echo "✓ No failures to address"
    exit 0
fi

echo "Found $FAILURE_COUNT failure categories to address"

# --- Read lab notebook for context on previous attempts ---
NOTEBOOK="${PROJECT_DIR}/.swarm/lab-notebook.json"
PREV_ATTEMPTS="[]"
if [[ -f "$NOTEBOOK" ]]; then
    PREV_ATTEMPTS=$(python3 -c "
import json
with open('$NOTEBOOK') as f: nb = json.load(f)
# Summarize previous iterations
summaries = []
for it in nb.get('iterations', []):
    summaries.append({
        'iteration': it.get('iteration'),
        'verdict': it.get('verdict'),
        'failures': [f.get('issue','') if isinstance(f,dict) else str(f) for f in it.get('failures', [])[:5]],
        'next_steps': it.get('next_steps', [])[:3],
    })
print(json.dumps(summaries))
" 2>/dev/null || echo "[]")
fi

# --- Build LLM prompt for diagnosis ---
DIAG_PROMPT_FILE=$(mktemp)
cat > "$DIAG_PROMPT_FILE" <<DIAGEOF
You are a scientific reviewer diagnosing experimental failures. Analyze these validation failures and propose concrete improvements.

VALIDATION FAILURES:
$FAILURES_JSON

PREVIOUS ATTEMPTS (avoid repeating these):
$PREV_ATTEMPTS

For each failure, propose ONE focused improvement task. Output ONLY valid JSON:

{
  "improvements": [
    {
      "failure_stage": "stage name",
      "root_cause": "1-2 sentence diagnosis",
      "hypothesis": "what we think will fix it",
      "task_title": "short actionable title",
      "task_description": "detailed description of what the agent should do, including specific files and changes",
      "files_to_modify": ["path/to/file.py"],
      "expected_effect": "what metric should improve",
      "priority": 1
    }
  ]
}

RULES:
- Be specific: name exact functions, files, parameters to change
- Each task must be independently actionable by an AI agent
- Do NOT repeat approaches from previous attempts
- Focus on the root cause, not symptoms
- Max 5 improvement tasks (prioritize highest-impact)
DIAGEOF

# --- Call LLM for diagnosis ---
echo "🧠 Diagnosing failures..."
DIAG_RESULT_FILE=$(mktemp)

if $AGENT_CMD $AGENT_FLAGS --no-color -p "$(cat "$DIAG_PROMPT_FILE")" 2>/dev/null > "$DIAG_RESULT_FILE"; then
    echo "  ✓ LLM diagnosis received"
else
    # Fallback: create generic improvement tasks from failures directly
    echo "  ⚠ LLM unavailable, creating tasks from failures directly"
    python3 -c "
import json, sys
failures = json.loads('$FAILURES_JSON')
improvements = []
for f in failures[:5]:
    stage = f.get('stage', 'unknown')
    issues = f.get('issues', [])
    top_issue = issues[0] if issues else 'Unknown issue'
    improvements.append({
        'failure_stage': stage,
        'root_cause': top_issue[:200],
        'hypothesis': f'Fix {stage} validation issues',
        'task_title': f'Fix: {stage} validation failure',
        'task_description': f'The {stage} validation stage failed with: {top_issue}. Investigate and fix the root cause.',
        'files_to_modify': [],
        'expected_effect': f'{stage} stage should PASS',
        'priority': 1,
    })
print(json.dumps({'improvements': improvements}))
" > "$DIAG_RESULT_FILE"
fi

rm -f "$DIAG_PROMPT_FILE"

# --- Extract JSON from LLM response ---
IMPROVEMENTS_JSON=$(python3 -c "
import json, sys, re
text = open('$DIAG_RESULT_FILE').read()
# Find JSON object
start = text.find('{')
end = text.rfind('}')
if start >= 0 and end > start:
    try:
        obj = json.loads(text[start:end+1])
        print(json.dumps(obj))
        sys.exit(0)
    except json.JSONDecodeError:
        pass
# Fallback
print(json.dumps({'improvements': []}))
" 2>/dev/null || echo '{"improvements": []}')

rm -f "$DIAG_RESULT_FILE"

# --- Create Beads tasks for each improvement ---
TASK_COUNT=$(echo "$IMPROVEMENTS_JSON" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('improvements',[])))")

if [[ "$TASK_COUNT" -eq 0 ]]; then
    echo "⚠ No improvement tasks generated"
    exit 0
fi

echo "Creating $TASK_COUNT improvement tasks..."

CREATED_IDS=""
echo "$IMPROVEMENTS_JSON" | python3 -c "
import json, sys, subprocess

data = json.load(sys.stdin)
improvements = data.get('improvements', [])

for imp in improvements:
    title = imp.get('task_title', 'Improvement task')[:80]
    desc = imp.get('task_description', '')
    priority = imp.get('priority', 1)
    root = imp.get('root_cause', '')
    hypothesis = imp.get('hypothesis', '')
    files = imp.get('files_to_modify', [])
    expected = imp.get('expected_effect', '')

    full_desc = f'{desc}\n\nROOT CAUSE: {root}\nHYPOTHESIS: {hypothesis}\nFILES: {\", \".join(files)}\nEXPECTED: {expected}'

    args = ['bd', 'create', title, f'--description={full_desc}', '-t', 'task', '-p', str(priority), '--json']
    parent = '$PARENT_TASK'
    if parent:
        args.extend(['--deps', f'discovered-from:{parent}'])

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode == 0:
        # Extract task ID from output
        try:
            task_data = json.loads(result.stdout)
            tid = task_data.get('id', '?')
        except:
            tid = result.stdout.strip()[:20]
        print(f'  ✓ Created: {tid} — {title}')

        # Add notes with improvement metadata
        files_str = ', '.join(files) if files else 'TBD'
        notes_text = f'IMPROVEMENT_TASK | ITERATION:next | PRODUCES:{files_str}'
        subprocess.run(['bd', 'update', str(tid), '--notes', notes_text],
                      capture_output=True, text=True)
    else:
        print(f'  ✗ Failed to create: {title}', file=sys.stderr)
        print(f'    {result.stderr[:200]}', file=sys.stderr)
"

echo "✓ Feedback loop complete: $TASK_COUNT tasks created"
