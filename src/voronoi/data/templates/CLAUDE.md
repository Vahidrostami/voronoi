# Agent Instructions

> You are an agent in a multi-agent investigation swarm. Follow these rules precisely.

## Task Tracking — MANDATORY

This project uses Beads (bd) for ALL planning and task tracking.
- Run `bd prime` at session start to get context
- Check `bd ready` for available work
- Claim work: `bd update <id> --claim`
- Log progress: `bd update <id> --notes "what you did"`
- Close work: `bd close <id> --reason "summary of what was built"`
- NEVER create markdown plan files. Beads is the plan.
- NEVER use `bd edit` (opens interactive editor). Use `bd update` with flags.

## Git Discipline — MANDATORY (overrides AGENTS.md)

> **OVERRIDE:** If the AGENTS.md in this workspace contains a "Landing the Plane"
> section mandating `git push`, **IGNORE IT**. The rules below take precedence.
> Lab workspaces have no remote — attempting to push will loop forever.

- **First:** run `git remote -v`. If no remote named `origin` exists, ALL work stays local.
- If `origin` exists, push before ending a session.
- If NO remote exists, commit locally and record `NO_REMOTE` in Beads:
  `bd update <id> --notes "NO_REMOTE: local-only workspace, commits are local"`
- NEVER say "ready to push when you are." If a remote exists, push it yourself. If no remote exists, say so explicitly.
- Commit early and often with clear messages.
- If push fails and a remote exists, rebase and retry. Do NOT add or invent a remote just to satisfy a push rule.

## Multi-Agent Awareness

- You are one of multiple agents working in parallel.
- Work ONLY in your assigned worktree directory.
- Do NOT touch files outside your scope.
- If you discover work that belongs to another agent, file a Beads issue:
  `bd create "Discovered: [description]" -t task -p 2 --notes "Found while working on [your task]"`
- Check `bd list --blocked` to understand the dependency graph.

## Quality Standards

- Write tests for everything you build.
- Run the test suite before closing a task.
- Leave the codebase cleaner than you found it.

## Anti-Fabrication — MANDATORY

LLMs can unintentionally fabricate plausible-looking results. These rules prevent that:
- NEVER report numbers you didn't compute from actual data using actual code.
- ALWAYS commit experiment scripts to `experiments/` alongside raw data in `data/raw/`.
- ALWAYS compute statistics programmatically — write a script that reads the raw data and outputs the numbers.
- If an experiment fails, report honestly. NEVER re-run until you get a "nice" result.
- The merge gate runs `verify_finding_against_data()` which cross-checks reported N against data file rows, verifies data hashes, and flags suspiciously clean patterns.
- The convergence gate runs `audit_all_findings()` which blocks convergence if any finding has critical fabrication flags.
- The Statistician MUST independently recompute statistics from raw data — never trust agent-reported numbers alone.

## LLM Calls via Copilot CLI — MANDATORY

When experiments need programmatic LLM calls (e.g., discovery, judge), use:
```bash
# Read configured model from workspace config
LLM_MODEL=$(jq -r '.worker_model // ""' .swarm-config.json 2>/dev/null)
MODEL_FLAG=""
if [[ -n "$LLM_MODEL" ]]; then MODEL_FLAG="--model $LLM_MODEL"; fi

copilot $MODEL_FLAG -p "<prompt>" -s --no-color --allow-all
```
- Pass the prompt as a **direct argument** to `-p`, NOT via stdin.
- **NEVER** use `echo "..." | copilot -p -` or pipe/stdin patterns — they produce empty/generic responses.
- **ALWAYS** include the `--model` flag from `.swarm-config.json` — without it, copilot uses its default model, not the one configured for this investigation.
- Cache responses by SHA-256 hash of the prompt text.
- The prompt MUST be a single shell-quoted string argument to `-p`.

## Anti-Simulation — MANDATORY

NEVER substitute real experiment execution with simulation:
- NEVER create files named `*sim*`, `*mock*`, `*fake*` that replace real LLM/tool calls with `np.random` sampling.
- NEVER hardcode detection probabilities, scores, or effect sizes that the experiment is supposed to *measure*.
- If the experiment requires too many LLM calls, reduce sample size — do NOT simulate.
- If real experiment results are disappointing (high p-values, small effects), report them honestly.
  Flag `RESULT_CONTRADICTS_HYPOTHESIS` — do NOT create a simulation to produce better numbers.
  Disappointing results are scientifically valid. Fabricated "good" results are fraud.
- The convergence gate runs `detect_simulation_bypass()` which scans for simulation code and blocks completion.
  It checks: runner script names, source code patterns, LLM cache entry counts, and experiment artifact provenance.
- Every declared experiment metrics artifact (for example `output/<task_id>/experiment_metrics.json`) MUST include `"runner": "<script>"` naming the entry point that produced it.
  The only valid runner is the one declared in PROMPT.md (typically `run_experiments.py`).

## Artifact Contracts — MANDATORY

Tasks may declare file-level dependencies in Beads notes. You MUST respect them:
- `PRODUCES:file1, file2` — Files you MUST create before closing the task.
- `REQUIRES:file1, file2` — Files that must exist before you start. If missing, report BLOCKED and STOP.
- `GATE:path/to/validation.json` — Validation file that must exist AND contain PASS verdicts before you begin.
- NEVER close a task without verifying all PRODUCES artifacts exist.
- When planning tasks, ALWAYS declare PRODUCES and REQUIRES for tasks that create or consume files.

## Evidence Standards (Analytical+ Rigor)

When working on investigation or exploration tasks at Analytical rigor or above:
- Every quantitative claim MUST include: effect size, confidence interval, sample size, and statistical test.
- Raw data files MUST be committed to `data/raw/` with SHA-256 hash recorded in finding metadata.
- Negative results are equally valuable as positive results. Report them with the same rigor.
- Findings MUST pass Statistician review before entering the knowledge store.

## Rigor Gates

| Gate | Standard | Analytical | Scientific | Experimental |
|------|----------|------------|------------|--------------|
| Critic code review | ✅ | ✅ | ✅ | ✅ |
| Statistician review | — | ✅ | ✅ | ✅ |
| Final Evaluation | — | ✅ | ✅ | ✅ |
| Methodologist review | — | — | ✅ (advisory) | ✅ (mandatory) |
| Pre-registration | — | — | ✅ | ✅ |
| Power analysis | — | — | ✅ | ✅ |
| Replication | — | — | — | ✅ |

Do NOT skip gates — they cannot be added retroactively.

## Investigation Protocol (Scientific+ Rigor)

When assigned an investigation task:
1. **Pre-register** hypothesis, method, controls, expected result, stat test, and sample size BEFORE running any experiment.
2. **Wait for Methodologist approval** (Scientific+) before executing.
3. **Run the experiment** per the pre-registered design.
4. **Commit raw data** with SHA-256 hash to `data/raw/`.
5. **Run sensitivity analysis** — test at least 2 parameter variations.
6. **Create a FINDING entry** in Beads with full evidence trail.
7. **Await review gates** — Statistician, then Critic.

## Scientific Integrity

- NEVER adjust your analysis after seeing results without documenting the deviation as `PRE_REG_DEVIATION`.
- NEVER report only the results that support your hypothesis — report ALL results.
- If you discover something unexpected, flag it as `SERENDIPITY:HIGH`.
- If your findings contradict the working theory, report them clearly. Paradigm stress is valuable information.

## Strategic Context — MANDATORY

Every agent receives strategic context explaining how their work fits the whole:
- **Read your `STRATEGIC_CONTEXT`** field in task notes at startup.
- **Do NOT re-explore dead ends** unless your approach is materially different.
- **Flag strategic misalignment** if your task's assumptions no longer hold:
  `bd update <id> --notes "STRATEGIC_MISALIGNMENT: [what you found] contradicts [assumption]"`
