---
name: debugging-runbook
description: >
  Use for debugging failed Voronoi worker tasks, broken verification loops,
  failing scripts, unexpected experiment outputs, and reproducible runtime errors.
  Emphasizes evidence-first reproduction before fixes.
user-invocable: true
disable-model-invocation: false
---

# Debugging Runbook

Use this skill when a task, script, experiment, or verification loop fails and the root cause is not yet proven.

## Procedure

1. Reproduce the failure with the narrowest command available.
2. Capture the exact command, exit code, and the smallest useful output excerpt.
3. Identify the expected behavior from the task notes, acceptance criteria, or relevant spec.
4. Localize the failure to input data, environment, code path, dependency, or stale state.
5. Add or tighten a focused regression check before changing source files when the failure is behavioral.
6. Apply the smallest fix that makes the repro pass.
7. Re-run the repro and the relevant verification command.

## Output

Record:

- failing command
- failing output summary
- root cause
- fix applied or proposed
- verification command and result
