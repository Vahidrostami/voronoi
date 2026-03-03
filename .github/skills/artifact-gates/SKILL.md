---
name: artifact-gates
description: >
  Skill for working with artifact contracts — the file-level dependency system that
  prevents pipeline failures by ensuring tasks produce expected outputs and only start
  when required inputs exist.
---

# Artifact Gates — File-Level Pipeline Enforcement

Use this skill when you need to understand or work with the artifact contract system
that enforces file-level dependencies between tasks.

## What Problem This Solves

Beads task dependencies (`bd dep add`) ensure tasks start in order, but they don't
verify that a task **actually produced its expected output files**. This causes two
classes of pipeline failure:

1. **Phantom completion**: Task closes in Beads but didn't create expected output files.
   Downstream tasks launch, find no input, and fail.
2. **Premature dispatch**: A task that consumes results starts before those results exist
   because Beads considers it "ready" (all task-level deps closed).

## The Three Artifact Properties

Each task can have these properties stored in Beads notes:

| Property | Format | Meaning |
|----------|--------|---------|
| `PRODUCES:file1, file2` | Comma-separated paths | Files the task **MUST create** |
| `REQUIRES:file1, file2` | Comma-separated paths | Files that **MUST exist** before dispatch |
| `GATE:path/to/report.json` | Single file path | Validation artifact that must exist AND pass |

## How to Set Artifact Contracts

### During Planning (plan-tasks.sh)

The planner LLM generates `produces`, `requires`, and `gate` fields per task.
These are automatically stored as Beads notes:

```bash
bd update <task-id> --notes "PRODUCES:output/results.json, output/figures/"
bd update <task-id> --notes "REQUIRES:output/data.csv"
bd update <task-id> --notes "GATE:output/validation_report.json"
```

### Manually (for existing tasks)

```bash
# Add output contract
bd update bd-42 --notes "PRODUCES:demos/coupled-decisions/output/results.json"

# Add input requirement
bd update bd-43 --notes "REQUIRES:demos/coupled-decisions/output/results.json"

# Add validation gate
bd update bd-44 --notes "GATE:demos/coupled-decisions/output/validation_report.json"
```

## Enforcement Points

### 1. Pre-Flight Check (autopilot.sh)

Before dispatching any task, `autopilot.sh` runs `preflight_check()`:

- Verifies all `REQUIRES` files exist on disk
- Verifies `GATE` file exists AND contains PASS verdicts
- If either fails, the task is **skipped** and tried again next poll cycle

### 2. Quality Gate (quality-gate.sh)

Before merging any branch, Gate 5 checks:

- Reads `PRODUCES` from Beads notes
- Verifies each listed file exists in the worktree or project root
- If any `PRODUCES` file is missing, the quality gate **FAILS** and the agent retries

### 3. Agent Prompt (spawn-agent.sh)

When spawning an agent, the artifact contract is injected into the prompt:

- Agent is told which files it MUST create (`PRODUCES`)
- Agent is told which files must exist (`REQUIRES`) — and to report BLOCKED if missing
- Agent is told about any `GATE` validation check to perform before starting

## Working With Artifact Contracts as an Agent

### At Startup

1. Read your task notes: `bd show <your-task-id>`
2. Check for `REQUIRES:` — verify each file exists
3. Check for `GATE:` — verify the file exists and contains passing verdicts
4. If anything is missing, report blocked:
   ```bash
   bd update <your-task-id> --notes "BLOCKED: Required artifact missing: <path>"
   ```

### During Work

- Keep track of which `PRODUCES` files you need to create
- Create output files **before** closing the task
- Commit output files to your branch

### Before Closing

1. Verify all `PRODUCES` files exist:
   ```bash
   ls -la path/to/expected/output.json
   ```
2. Only close the task after all artifacts are created
3. If you cannot create a required output, document why and do NOT close the task

## Gate File Formats

A `GATE` file is a JSON validation report. The pre-flight check recognizes these formats:

```json
// Format 1: Top-level verdict
{"verdict": "PASS"}

// Format 2: Per-stage verdicts
{
  "stage_1": {"verdict": "PASS"},
  "stage_2": {"verdict": "PASS"},
  "stage_3": {"verdict": "PASS"}
}

// Format 3: Array of experiment verdicts
{
  "experiments": [
    {"name": "encoding", "verdict": "PASS"},
    {"name": "ablation", "verdict": "PASS"}
  ]
}
```

If **any** verdict is not `PASS`, the gated task remains blocked.

## Example: Multi-Phase Pipeline

```
Task 1: Generate Data
  PRODUCES: output/data.csv, output/policies.json
  REQUIRES: (none)

Task 2: Run Experiments
  PRODUCES: output/results.json
  REQUIRES: output/data.csv

Task 3: Validate Results
  PRODUCES: output/validation_report.json
  REQUIRES: output/results.json

Task 4: Write Paper            ← This is the common failure point!
  PRODUCES: output/paper.pdf
  REQUIRES: output/results.json
  GATE: output/validation_report.json

Task 5: Build Webapp
  PRODUCES: output/webapp.html
  REQUIRES: output/results.json
```

Without artifact contracts, Task 4 would start as soon as Task 3 closes in Beads —
even if `validation_report.json` doesn't exist or contains FAIL verdicts.
With artifact contracts, Task 4 is held until the file exists and passes.
