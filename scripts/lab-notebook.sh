#!/bin/bash
set -euo pipefail

# =============================================================================
# lab-notebook.sh — Structured iteration tracking for scientific workflows
#
# Maintains .swarm/lab-notebook.json with what was tried, what worked/failed.
#
# Usage:
#   ./scripts/lab-notebook.sh init
#   ./scripts/lab-notebook.sh append --iteration N --phase PHASE --verdict VERDICT \
#       --metrics '{"key":"val"}' --failures '[]' --next-steps '[]'
#   ./scripts/lab-notebook.sh summary
#   ./scripts/lab-notebook.sh get-iteration
# =============================================================================

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NOTEBOOK="${PROJECT_DIR}/.swarm/lab-notebook.json"

_ensure_dir() { mkdir -p "$(dirname "$NOTEBOOK")"; }

cmd_init() {
    _ensure_dir
    if [[ -f "$NOTEBOOK" ]]; then
        echo "Lab notebook already exists: $NOTEBOOK"
        return 0
    fi
    cat > "$NOTEBOOK" <<'EOF'
{
  "created_at": "",
  "iterations": [],
  "converged": false,
  "final_verdict": null
}
EOF
    # Stamp creation time
    python3 -c "
import json, datetime
with open('$NOTEBOOK') as f: nb = json.load(f)
nb['created_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
with open('$NOTEBOOK','w') as f: json.dump(nb, f, indent=2)
"
    echo "Initialized: $NOTEBOOK"
}

cmd_append() {
    local iteration="" phase="" verdict="" metrics="{}" failures="[]" next_steps="[]"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --iteration)   iteration="$2"; shift 2 ;;
            --phase)       phase="$2"; shift 2 ;;
            --verdict)     verdict="$2"; shift 2 ;;
            --metrics)     metrics="$2"; shift 2 ;;
            --failures)    failures="$2"; shift 2 ;;
            --next-steps)  next_steps="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    _ensure_dir
    [[ -f "$NOTEBOOK" ]] || cmd_init

    python3 -c "
import json, datetime, sys
with open('$NOTEBOOK') as f: nb = json.load(f)
entry = {
    'iteration': int('${iteration:-0}'),
    'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'phase': '''${phase}''',
    'verdict': '''${verdict}''',
    'metrics': json.loads('''${metrics}'''),
    'failures': json.loads('''${failures}'''),
    'next_steps': json.loads('''${next_steps}'''),
}
nb['iterations'].append(entry)
with open('$NOTEBOOK','w') as f: json.dump(nb, f, indent=2)
print(f'Appended iteration {entry[\"iteration\"]} ({entry[\"verdict\"]})')
"
}

cmd_mark_converged() {
    local verdict="${1:-PASS}"
    python3 -c "
import json
with open('$NOTEBOOK') as f: nb = json.load(f)
nb['converged'] = True
nb['final_verdict'] = '$verdict'
with open('$NOTEBOOK','w') as f: json.dump(nb, f, indent=2)
print('Marked converged: $verdict')
"
}

cmd_get_iteration() {
    if [[ ! -f "$NOTEBOOK" ]]; then
        echo "0"
        return
    fi
    python3 -c "
import json
with open('$NOTEBOOK') as f: nb = json.load(f)
print(len(nb.get('iterations', [])))
"
}

cmd_summary() {
    if [[ ! -f "$NOTEBOOK" ]]; then
        echo "No lab notebook found."
        return 1
    fi
    python3 -c "
import json
with open('$NOTEBOOK') as f: nb = json.load(f)
iters = nb.get('iterations', [])
print(f'Iterations: {len(iters)}')
print(f'Converged: {nb.get(\"converged\", False)}')
for i, it in enumerate(iters):
    v = it.get('verdict', '?')
    p = it.get('phase', '?')
    fails = len(it.get('failures', []))
    print(f'  [{i+1}] {p}: {v} ({fails} failures)')
"
}

# --- Dispatch ---
ACTION="${1:-}"
shift || true
case "$ACTION" in
    init)           cmd_init ;;
    append)         cmd_append "$@" ;;
    mark-converged) cmd_mark_converged "$@" ;;
    get-iteration)  cmd_get_iteration ;;
    summary)        cmd_summary ;;
    *)
        echo "Usage: lab-notebook.sh {init|append|mark-converged|get-iteration|summary}"
        exit 1
        ;;
esac
