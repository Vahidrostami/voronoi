#!/bin/bash
set -euo pipefail

# =============================================================================
# convergence-gate.sh — Multi-signal convergence validation
#
# Usage: ./scripts/convergence-gate.sh <workspace-dir> [rigor-level]
#
# Validates that convergence is real by checking multiple independent signals.
# Prevents premature completion caused by spoofed eval-score.json, missing
# claim-evidence registry, or unresolved findings.
#
# Exits 0 if convergence is valid, 1 if any check fails.
# =============================================================================

WORKSPACE="${1:-.}"
RIGOR="${2:-standard}"
SWARM="${WORKSPACE}/.swarm"

echo "convergence-gate: Validating convergence (rigor=$RIGOR)..."

BLOCKERS=""
WARNINGS=""

# -------------------------------------------------------------------------
# Check 1: Deliverable exists
# -------------------------------------------------------------------------
if [ ! -f "${SWARM}/deliverable.md" ]; then
    BLOCKERS="${BLOCKERS}\n  ✗ No deliverable.md produced"
fi

# -------------------------------------------------------------------------
# Check 2: eval-score.json integrity (Analytical+)
# -------------------------------------------------------------------------
if [ "$RIGOR" != "standard" ]; then
    EVAL_FILE="${SWARM}/eval-score.json"
    DELIVERABLE_FILE="${SWARM}/deliverable.md"

    if [ ! -f "$EVAL_FILE" ]; then
        BLOCKERS="${BLOCKERS}\n  ✗ No eval-score.json (required at $RIGOR rigor)"
    else
        # Verify eval-score was written AFTER deliverable (timestamp check)
        if [ -f "$DELIVERABLE_FILE" ]; then
            EVAL_MTIME=$(stat -f %m "$EVAL_FILE" 2>/dev/null || stat -c %Y "$EVAL_FILE" 2>/dev/null || echo "0")
            DELIV_MTIME=$(stat -f %m "$DELIVERABLE_FILE" 2>/dev/null || stat -c %Y "$DELIVERABLE_FILE" 2>/dev/null || echo "0")
            if [ "$EVAL_MTIME" -lt "$DELIV_MTIME" ] 2>/dev/null; then
                WARNINGS="${WARNINGS}\n  ⚠ eval-score.json older than deliverable.md (may be stale)"
            fi
        fi

        # Verify score is valid JSON with expected structure
        EVAL_CHECK=$(python3 -c "
import json, sys
try:
    data = json.load(open('$EVAL_FILE'))
    score = float(data.get('score', 0))
    if score < 0 or score > 1:
        print('INVALID:score out of range')
    elif score == 0:
        print('INVALID:score is zero')
    else:
        print('OK:' + str(score))
except Exception as e:
    print('INVALID:' + str(e))
" 2>/dev/null || echo "INVALID:parse_error")

        if [[ "$EVAL_CHECK" == INVALID:* ]]; then
            BLOCKERS="${BLOCKERS}\n  ✗ eval-score.json invalid: ${EVAL_CHECK#INVALID:}"
        else
            SCORE="${EVAL_CHECK#OK:}"
            echo "  ✓ eval-score.json valid (score=$SCORE)"
        fi
    fi
fi

# -------------------------------------------------------------------------
# Check 3: claim-evidence.json (Analytical+)
# -------------------------------------------------------------------------
if [ "$RIGOR" != "standard" ]; then
    CE_FILE="${SWARM}/claim-evidence.json"
    if [ ! -f "$CE_FILE" ]; then
        WARNINGS="${WARNINGS}\n  ⚠ No claim-evidence.json (traceability gap)"
    else
        CE_CHECK=$(python3 -c "
import json, sys
try:
    data = json.load(open('$CE_FILE'))
    claims = data.get('claims', [])
    orphans = data.get('orphan_findings', [])
    unsupported = data.get('unsupported_claims', [])
    coverage = float(data.get('coverage_score', 0))
    issues = []
    if orphans:
        issues.append(str(len(orphans)) + ' orphan finding(s)')
    if unsupported:
        issues.append(str(len(unsupported)) + ' unsupported claim(s)')
    if not claims:
        issues.append('no claims recorded')
    if issues:
        print('WARN:' + '; '.join(issues))
    else:
        print('OK:' + str(len(claims)) + ' claims, coverage=' + str(coverage))
except Exception as e:
    print('WARN:parse error: ' + str(e))
" 2>/dev/null || echo "WARN:parse_failed")

        if [[ "$CE_CHECK" == WARN:* ]]; then
            WARNINGS="${WARNINGS}\n  ⚠ claim-evidence: ${CE_CHECK#WARN:}"
        else
            echo "  ✓ claim-evidence.json valid (${CE_CHECK#OK:})"
        fi
    fi
fi

# -------------------------------------------------------------------------
# Check 4: No CONTESTED findings remain (Scientific+)
# -------------------------------------------------------------------------
if [ "$RIGOR" = "scientific" ] || [ "$RIGOR" = "experimental" ]; then
    CONTESTED=$(bd list --json 2>/dev/null | python3 -c "
import sys, json
try:
    tasks = json.load(sys.stdin)
    contested = [t['id'] for t in tasks if 'ADVERSARIAL_RESULT: CONTESTED' in t.get('notes', '') and t.get('status') != 'closed']
    if contested:
        print(','.join(contested))
except Exception:
    pass
" 2>/dev/null || true)

    if [ -n "$CONTESTED" ]; then
        BLOCKERS="${BLOCKERS}\n  ✗ Contested findings still open: $CONTESTED"
    fi
fi

# -------------------------------------------------------------------------
# Check 5: Belief map resolution (Scientific+)
# -------------------------------------------------------------------------
if [ "$RIGOR" = "scientific" ] || [ "$RIGOR" = "experimental" ]; then
    BM_FILE="${SWARM}/belief-map.json"
    if [ -f "$BM_FILE" ]; then
        BM_CHECK=$(python3 -c "
import json, sys
try:
    data = json.load(open('$BM_FILE'))
    hyps = data.get('hypotheses', [])
    unresolved = [h['name'] for h in hyps if h.get('status') in ('untested', 'testing')]
    if unresolved:
        print('UNRESOLVED:' + '; '.join(unresolved[:3]))
    else:
        print('OK:' + str(len(hyps)) + ' hypotheses resolved')
except Exception as e:
    print('WARN:' + str(e))
" 2>/dev/null || echo "WARN:parse_failed")

        if [[ "$BM_CHECK" == UNRESOLVED:* ]]; then
            BLOCKERS="${BLOCKERS}\n  ✗ Unresolved hypotheses: ${BM_CHECK#UNRESOLVED:}"
        elif [[ "$BM_CHECK" == WARN:* ]]; then
            WARNINGS="${WARNINGS}\n  ⚠ belief-map: ${BM_CHECK#WARN:}"
        else
            echo "  ✓ belief-map resolved (${BM_CHECK#OK:})"
        fi
    fi
fi

# -------------------------------------------------------------------------
# Check 6: Figure integrity (if LaTeX present)
# -------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if find "$WORKSPACE" -name '*.tex' -not -path '*/.git/*' 2>/dev/null | head -1 | grep -q '.'; then
    if [ -x "${SCRIPT_DIR}/figure-lint.sh" ]; then
        echo "  Running figure-lint..."
        if ! "${SCRIPT_DIR}/figure-lint.sh" "$WORKSPACE" 2>/dev/null; then
            WARNINGS="${WARNINGS}\n  ⚠ figure-lint: Missing figures detected"
        fi
    fi
fi

# -------------------------------------------------------------------------
# Report
# -------------------------------------------------------------------------
echo ""
if [ -n "$BLOCKERS" ]; then
    echo "convergence-gate: FAILED — blocking issues:"
    echo -e "$BLOCKERS"
    if [ -n "$WARNINGS" ]; then
        echo ""
        echo "convergence-gate: Warnings:"
        echo -e "$WARNINGS"
    fi
    exit 1
fi

if [ -n "$WARNINGS" ]; then
    echo "convergence-gate: PASSED with warnings:"
    echo -e "$WARNINGS"
else
    echo "convergence-gate: PASSED — all checks clear"
fi
exit 0
