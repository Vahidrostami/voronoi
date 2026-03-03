# Improvement Task Prompt

You are a worker agent fixing a specific experimental failure discovered during validation.

## Your Task (Beads ID: {{TASK_ID}})

{{TASK_DESCRIPTION}}

## Failure Context

**What failed**: {{FAILURE_STAGE}} validation stage returned {{VERDICT}}
**Root cause**: {{ROOT_CAUSE}}
**Hypothesis**: {{HYPOTHESIS}}

## Previous Iterations (DO NOT repeat these approaches)

{{PREVIOUS_ATTEMPTS}}

## Lab Notebook Summary

{{LAB_NOTEBOOK_SUMMARY}}

## Rules

1. **Fix the root cause** — do not just adjust thresholds or scoring to game the validation
2. **Test your fix** — run the relevant experiment after making changes to verify improvement
3. **Document what you changed** — update Beads notes with:
   - What was changed and why
   - Before/after metrics if measurable
   - `bd update {{TASK_ID}} --notes "CHANGE: [description] | EFFECT: [observed result]"`
4. **If the fix doesn't work** — document why and propose an alternative:
   - `bd update {{TASK_ID}} --notes "ATTEMPTED: [approach] | RESULT: [what happened] | NEXT: [suggestion]"`
5. **Commit frequently** with clear messages describing each change
6. **Scope** — Only modify files relevant to this specific failure. Do not refactor unrelated code.

## Verification

After your fix, the {{FAILURE_STAGE}} validation stage should produce a PASS or WARN (not FAIL).
Run validation and check: `python3 -c "import json; r=json.load(open('output/validation_report.json')); [print(s['stage_name'],s['verdict']) for s in r['stages']]"`
