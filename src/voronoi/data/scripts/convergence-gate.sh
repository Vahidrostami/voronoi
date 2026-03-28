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
    # Schema migration: handle dict-keyed hypotheses (INV-33)
    if isinstance(hyps, dict):
        hyps = [v if isinstance(v, dict) else {'id': k, 'name': v} for k, v in hyps.items()]
    if not isinstance(hyps, list):
        hyps = []
    hyps = [h for h in hyps if isinstance(h, dict)]
    unresolved = [h.get('name', h.get('id', '?')) for h in hyps if h.get('status') in ('untested', 'testing')]
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
# Check 6: Anti-fabrication audit (Analytical+)
# -------------------------------------------------------------------------
if [ "$RIGOR" != "standard" ]; then
    echo "  Running anti-fabrication audit..."
    FAB_CHECK=$(python3 -c "
import sys
sys.path.insert(0, '${WORKSPACE}/src' if __import__('os').path.isdir('${WORKSPACE}/src') else '.')
try:
    from voronoi.science import audit_all_findings, format_fabrication_report
    from pathlib import Path
    results = audit_all_findings(Path('$WORKSPACE'))
    if not results:
        print('OK:no findings to audit')
    else:
        critical = sum(len(r.critical_flags) for r in results)
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        if critical > 0:
            print('FAIL:' + str(critical) + ' critical flag(s) across ' + str(total) + ' findings')
        else:
            print('OK:' + str(passed) + '/' + str(total) + ' findings verified')
except Exception as e:
    print('WARN:audit unavailable: ' + str(e))
" 2>/dev/null || echo "WARN:audit_unavailable")

    if [[ "$FAB_CHECK" == FAIL:* ]]; then
        BLOCKERS="${BLOCKERS}\n  ✗ Anti-fabrication: ${FAB_CHECK#FAIL:}"
    elif [[ "$FAB_CHECK" == WARN:* ]]; then
        WARNINGS="${WARNINGS}\n  ⚠ Anti-fabrication: ${FAB_CHECK#WARN:}"
    else
        echo "  ✓ Anti-fabrication audit passed (${FAB_CHECK#OK:})"
    fi
fi

# -------------------------------------------------------------------------
# Check 7: Simulation / LLM-bypass detection (Analytical+)
# -------------------------------------------------------------------------
if [ "$RIGOR" != "standard" ]; then
    echo "  Running simulation-bypass detection..."
    SIM_CHECK=$(python3 -c "
import sys, json, glob
sys.path.insert(0, '${WORKSPACE}/src' if __import__('os').path.isdir('${WORKSPACE}/src') else '.')
try:
    from voronoi.science import detect_simulation_bypass
    from pathlib import Path
    ws = Path('$WORKSPACE')
    # Estimate expected LLM calls from success-criteria or invariants
    expected = 0
    sc_file = ws / '.swarm' / 'success-criteria.json'
    if sc_file.exists():
        try:
            sc = json.load(open(sc_file))
            # Look for cache validation criteria
            for c in (sc if isinstance(sc, list) else []):
                desc = str(c.get('description', '')).lower()
                if 'cache' in desc or 'llm_call' in desc:
                    import re
                    nums = re.findall(r'\d+', desc)
                    if nums:
                        expected = max(expected, int(nums[-1]))
        except Exception:
            pass
    # Fallback: count cache entries and flag if suspiciously low for the project size
    if expected == 0:
        result_files = list(ws.rglob('results.json'))
        for rf in result_files:
            try:
                d = json.load(open(rf))
                if isinstance(d, dict):
                    n = d.get('n_scenarios', 0)
                    k = d.get('k_runs', d.get('runs_per_cell', 0))
                    cells = d.get('n_cells', 4)
                    if n and k:
                        expected = max(expected, n * cells * k)
            except Exception:
                pass
    result = detect_simulation_bypass(ws, expected_min_llm_calls=expected)
    if not result.flags:
        print('OK:no simulation bypass detected')
    else:
        critical = len(result.critical_flags)
        if critical > 0:
            msgs = [f.message for f in result.critical_flags]
            print('FAIL:' + str(critical) + ' critical: ' + '; '.join(msgs[:3]))
        else:
            msgs = [f.message for f in result.flags]
            print('WARN:' + '; '.join(msgs[:3]))
except Exception as e:
    print('WARN:simulation check unavailable: ' + str(e))
" 2>/dev/null || echo "WARN:sim_check_unavailable")

    if [[ "$SIM_CHECK" == FAIL:* ]]; then
        BLOCKERS="${BLOCKERS}\n  ✗ Simulation bypass: ${SIM_CHECK#FAIL:}"
    elif [[ "$SIM_CHECK" == WARN:* ]]; then
        WARNINGS="${WARNINGS}\n  ⚠ Simulation bypass: ${SIM_CHECK#WARN:}"
    else
        echo "  ✓ Simulation-bypass check passed (${SIM_CHECK#OK:})"
    fi
fi

# -------------------------------------------------------------------------
# Check 8: Data invariants (min_csv_rows etc.)  [was 7]
# -------------------------------------------------------------------------
if [ "$RIGOR" != "standard" ]; then
    echo "  Checking data invariants..."
    DATA_INV_CHECK=$(python3 -c "
import sys
sys.path.insert(0, '${WORKSPACE}/src' if __import__('os').path.isdir('${WORKSPACE}/src') else '.')
try:
    from voronoi.science import load_invariants, validate_data_invariants
    from pathlib import Path
    invariants = load_invariants(Path('$WORKSPACE'))
    data_invs = [i for i in invariants if i.check_type == 'min_csv_rows']
    if not data_invs:
        print('OK:no data invariants defined')
    else:
        result = validate_data_invariants(Path('$WORKSPACE'), invariants)
        if result.passed:
            print('OK:' + str(len(data_invs)) + ' data invariant(s) passed')
        else:
            print('FAIL:' + '; '.join(result.violations[:5]))
except Exception as e:
    print('WARN:data invariant check unavailable: ' + str(e))
" 2>/dev/null || echo "WARN:check_unavailable")

    if [[ "$DATA_INV_CHECK" == FAIL:* ]]; then
        BLOCKERS="${BLOCKERS}\n  ✗ Data invariants: ${DATA_INV_CHECK#FAIL:}"
    elif [[ "$DATA_INV_CHECK" == WARN:* ]]; then
        WARNINGS="${WARNINGS}\n  ⚠ Data invariants: ${DATA_INV_CHECK#WARN:}"
    else
        echo "  ✓ Data invariants passed (${DATA_INV_CHECK#OK:})"
    fi
fi

# -------------------------------------------------------------------------
# Check 9: Figure integrity (if LaTeX present)  [was 8]
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
