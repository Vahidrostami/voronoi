---
name: revise-calibration
description: >
  Skill for iterative experiment design using REVISE tasks and calibration
  workflows. Use when a pilot experiment fails calibration or results are
  unexpected and need systematic revision with full context carry-forward.
---

# REVISE & Calibration Protocol Skill

Use this skill when a pilot experiment fails calibration or produces unexpected
results. REVISE tasks carry forward context from the previous attempt so the next
worker doesn't repeat the same mistakes.

## REVISE Task Protocol

When a pilot experiment fails calibration or results are unexpected, create a
REVISE task instead of a fresh task:

```bash
bd create "REVISE: <description>" -t task -p 1 --json
bd update <id> --notes "REVISE_OF:<previous-task-id>"
bd update <id> --notes "PRIOR_RESULT:<what happened>"
bd update <id> --notes "FAILURE_DIAGNOSIS:<why it failed>"
bd update <id> --notes "REVISED_PARAMS:<what changed>"
```

The worker receiving a REVISE task gets the full context of what was tried and
why it failed. Include ALL revise context in the worker prompt.

## Calibration Workflow

1. Dispatch a PILOT task (small N, quick run)
2. Read pilot results — check CALIBRATION_TARGET vs CALIBRATION_ACTUAL
3. If calibration fails, create a REVISE task with diagnosis
4. Only dispatch the full experiment after calibration passes

## Calibration Iteration Cap — HARD LIMIT

- Track calibration iteration count: `CALIBRATION_ITER:N` in Beads notes
- After **3 failed iterations**: STOP tweaking parameters. Write a root-cause
  diagnosis that explains WHY the calibration is failing (not just what failed).
  Common root causes:
  - LLMs use training priors, not statistics — varying noise/SNR may have no
    effect if the model relies on semantic priors rather than quantitative
    features in the input. Solution: scale the **signal** (e.g., coefficients,
    feature values), not just the noise.
  - Effect sizes too small relative to LLM output variance
  - Encoding/prompt design doesn't expose the manipulation to the model
  - Wrong metric — measuring something orthogonal to the manipulation
- After **5 failed iterations**: dispatch Methodologist for post-mortem.
  Flag `CALIBRATION_ESCALATED` in Beads. Do NOT continue tweaking.
- NEVER make >5 calibration attempts on the same design. Either the
  Methodologist redesigns the experiment or you report the calibration failure
  as a finding (it IS informative data).
