#!/bin/bash
set -euo pipefail

# =============================================================================
# convergence-judge.sh — Orchestrator's scientific mental model
#
# Reads validation results, decides whether to iterate or converge.
# Called by autopilot.sh after validation completes.
#
# Usage:
#   ./scripts/convergence-judge.sh <validation-report> <results-json> \
#       [--max-iterations N] [--parent-task ID] [--output-dir DIR] [--prompt-file FILE]
#
# Exit codes:
#   0 — CONVERGED (proceed to next phase)
#   1 — ITERATE (new tasks created, re-run needed)
#   2 — EXHAUSTED (max iterations reached, proceed with limitations)
# =============================================================================

VALIDATION_REPORT="${1:-}"
RESULTS_JSON="${2:-}"
MAX_ITERATIONS=3
PARENT_TASK=""
OUTPUT_DIR=""
PROMPT_FILE=""

shift 2 || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-iterations) MAX_ITERATIONS="$2"; shift 2 ;;
        --parent-task)    PARENT_TASK="$2"; shift 2 ;;
        --output-dir)     OUTPUT_DIR="$2"; shift 2 ;;
        --prompt-file)    PROMPT_FILE="$2"; shift 2 ;;
        *) shift ;;
    esac
done

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

SCRIPTS_DIR="$PROJECT_DIR/scripts"

# --- Validate inputs ---
if [[ ! -f "$VALIDATION_REPORT" ]]; then
    echo "✗ Validation report not found: $VALIDATION_REPORT"
    exit 1
fi

# --- Get current iteration ---
CURRENT_ITER=$("$SCRIPTS_DIR/lab-notebook.sh" get-iteration)
NEXT_ITER=$((CURRENT_ITER + 1))

echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║  🔬 CONVERGENCE JUDGE — Iteration $NEXT_ITER/$MAX_ITERATIONS"
echo "╚═══════════════════════════════════════════════╝"
echo ""

# --- Parse validation verdict ---
OVERALL_VERDICT=$(python3 -c "
import json
with open('$VALIDATION_REPORT') as f: r = json.load(f)
print(r.get('overall_verdict', 'UNKNOWN'))
")

STAGE_VERDICTS=$(python3 -c "
import json
with open('$VALIDATION_REPORT') as f: r = json.load(f)
for s in r.get('stages', []):
    print(f\"{s.get('stage_name','?')}: {s.get('verdict','?')}\")
")

FAILURE_COUNT=$(python3 -c "
import json
with open('$VALIDATION_REPORT') as f: r = json.load(f)
print(len(r.get('unresolved_concerns', [])))
")

echo "Overall verdict: $OVERALL_VERDICT"
echo "Stage verdicts:"
echo "$STAGE_VERDICTS" | sed 's/^/  /'
echo "Unresolved concerns: $FAILURE_COUNT"
echo ""

# --- Extract metrics for lab notebook ---
METRICS="{}"
if [[ -f "$RESULTS_JSON" ]]; then
    METRICS=$(python3 -c "
import json
with open('$RESULTS_JSON') as f: r = json.load(f)
s = r.get('summary', {})
print(json.dumps({
    'effects_detected': s.get('total_effects_discovered', 0),
    'encoding_gain': s.get('encoding_accuracy_gain', 0),
    'space_reduction': s.get('space_reduction_factor', 0),
    'generalization': s.get('generalization_success', False),
    'all_criteria_met': s.get('all_criteria_met', False),
}))
" 2>/dev/null || echo '{}')
fi

# --- Extract failure details for lab notebook ---
FAILURES_DETAIL=$(python3 -c "
import json
with open('$VALIDATION_REPORT') as f: r = json.load(f)
failures = []
for s in r.get('stages', []):
    if s.get('verdict') in ('FAIL', 'WARN'):
        for issue in s.get('issues_found', [])[:3]:
            failures.append({'stage': s['stage_name'], 'issue': issue[:200]})
print(json.dumps(failures))
" 2>/dev/null || echo '[]')

# --- Check for diminishing returns ---
DIMINISHING=false
if [[ "$CURRENT_ITER" -ge 2 ]]; then
    DIMINISHING=$(python3 -c "
import json
with open('${PROJECT_DIR}/.swarm/lab-notebook.json') as f: nb = json.load(f)
iters = nb.get('iterations', [])
if len(iters) >= 2:
    prev_fails = len(iters[-1].get('failures', []))
    prev_prev_fails = len(iters[-2].get('failures', []))
    # If failure count hasn't improved by >5% in last 2 iterations
    if prev_prev_fails > 0:
        improvement = (prev_prev_fails - prev_fails) / prev_prev_fails
        if improvement < 0.05:
            print('true')
        else:
            print('false')
    else:
        print('false')
else:
    print('false')
" 2>/dev/null || echo "false")
fi

# --- Decision logic ---
DECISION=""
NEXT_STEPS="[]"

if [[ "$OVERALL_VERDICT" == "PASS" ]]; then
    DECISION="CONVERGED"
    echo "✅ CONVERGED — All validation stages passed"

elif [[ "$NEXT_ITER" -gt "$MAX_ITERATIONS" ]]; then
    DECISION="EXHAUSTED"
    echo "⚠ EXHAUSTED — Max iterations ($MAX_ITERATIONS) reached"
    echo "  Proceeding with honest limitations disclosure"

elif [[ "$DIMINISHING" == "true" ]]; then
    DECISION="DIMINISHING_RETURNS"
    echo "⚠ DIMINISHING RETURNS — Last 2 iterations showed <5% improvement"
    echo "  Proceeding with quality disclosure"

else
    DECISION="ITERATE"
    echo "🔄 ITERATE — Failures found, creating improvement tasks"
fi

# --- Record in lab notebook ---
"$SCRIPTS_DIR/lab-notebook.sh" append \
    --iteration "$NEXT_ITER" \
    --phase "convergence_check" \
    --verdict "$DECISION" \
    --metrics "$METRICS" \
    --failures "$FAILURES_DETAIL" \
    --next-steps "$NEXT_STEPS"

# --- Act on decision ---
case "$DECISION" in
    CONVERGED)
        "$SCRIPTS_DIR/lab-notebook.sh" mark-converged "PASS"

        # Write convergence marker for GATE checks
        MARKER_DIR=$(dirname "$VALIDATION_REPORT")
        echo '{"converged": true, "verdict": "PASS", "iteration": '"$NEXT_ITER"'}' \
            > "$MARKER_DIR/convergence.json"

        echo "Convergence marker written to $MARKER_DIR/convergence.json"
        exit 0
        ;;

    ITERATE)
        # Create improvement tasks via validation-feedback.sh
        FEEDBACK_ARGS=("$VALIDATION_REPORT" "$PARENT_TASK")
        [[ -n "$OUTPUT_DIR" ]] && FEEDBACK_ARGS+=("--output-dir" "$OUTPUT_DIR")

        "$SCRIPTS_DIR/validation-feedback.sh" "${FEEDBACK_ARGS[@]}"

        # Also create a re-validation task that depends on improvements
        RE_VALIDATE_DESC="Re-run experiments and validation after improvements from iteration $NEXT_ITER.

Steps:
1. Re-run the failing experiments with the improvements applied
2. Re-run validation: python -m src.validation (or equivalent)
3. Check validation_report.json — all stages must PASS
4. If still failing, update Beads with detailed notes on what changed

CONTEXT — Previous failures:
$FAILURES_DETAIL

Iteration: $NEXT_ITER of $MAX_ITERATIONS"

        REVALIDATE_ID=$(bd create "Re-validate after iteration $NEXT_ITER" \
            --description="$RE_VALIDATE_DESC" \
            -t task -p 0 --json 2>/dev/null | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get('id',''))
except: print('')
" || echo "")

        if [[ -n "$REVALIDATE_ID" ]]; then
            echo "  ✓ Re-validation task created: $REVALIDATE_ID"
            # Mark with convergence metadata
            bd update "$REVALIDATE_ID" --notes \
                "CONVERGENCE_CHECKPOINT | ITERATION:$NEXT_ITER | MAX:$MAX_ITERATIONS" \
                2>/dev/null || true
        fi

        echo ""
        echo "📋 Iteration $NEXT_ITER tasks created. Autopilot will dispatch them."
        exit 1
        ;;

    EXHAUSTED|DIMINISHING_RETURNS)
        "$SCRIPTS_DIR/lab-notebook.sh" mark-converged "$DECISION"

        # Write convergence marker with limitations
        MARKER_DIR=$(dirname "$VALIDATION_REPORT")
        python3 -c "
import json
with open('$VALIDATION_REPORT') as f: r = json.load(f)
marker = {
    'converged': True,
    'verdict': '$DECISION',
    'iteration': $NEXT_ITER,
    'limitations': r.get('unresolved_concerns', []),
    'stage_verdicts': {s['stage_name']: s['verdict'] for s in r.get('stages', [])},
}
with open('$MARKER_DIR/convergence.json', 'w') as f:
    json.dump(marker, f, indent=2)
print('Convergence marker written with limitations')
"
        exit 2
        ;;
esac
