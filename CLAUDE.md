# Agent Instructions

## Task Tracking — MANDATORY
This project uses Beads (bd) for ALL planning and task tracking.
- Run `bd prime` at session start to get context
- Check `bd ready` for available work
- Claim work: `bd update <id> --claim`
- Log progress: `bd update <id> --notes "what you did"`
- Close work: `bd close <id> --reason "summary of what was built"`
- NEVER create markdown plan files. Beads is the plan.
- NEVER use `bd edit` (opens interactive editor). Use `bd update` with flags.

## Git Discipline — MANDATORY
- ALWAYS push before ending a session. Unpushed work = lost work.
- NEVER say "ready to push when you are." YOU push. NOW.
- Commit early and often with clear messages.
- If push fails, rebase and retry until it succeeds.

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

## Evidence Standards (Analytical+ Rigor)

When working on investigation or exploration tasks at Analytical rigor or above:

- Every quantitative claim MUST include: effect size, confidence interval, sample size, and statistical test.
- Raw data files MUST be committed to `data/raw/` in your worktree — never summarize without preserving the source.
- Compute SHA-256 hash of all raw data files immediately after collection and record in finding metadata.
- Negative results are equally valuable as positive results. Report them with the same rigor.
- Findings MUST pass Statistician review before entering the knowledge store.

## Rigor Gates

Gates activate based on the rigor level classified by the orchestrator:

| Gate | Standard | Analytical | Scientific | Experimental |
|------|----------|------------|------------|--------------|
| Critic code review | ✅ | ✅ | ✅ | ✅ |
| Statistician review | — | ✅ | ✅ | ✅ |
| Methodologist design review | — | — | ✅ (advisory) | ✅ (mandatory) |
| Pre-registration | — | — | ✅ | ✅ |
| Power analysis | — | — | ✅ | ✅ |
| Partial blinding for Critic | — | — | ✅ | ✅ |
| Adversarial review loop | — | — | ✅ | ✅ |
| Replication of high-impact findings | — | — | — | ✅ |

Do NOT skip gates — they cannot be added retroactively.

## Investigation Protocol (Scientific+ Rigor)

When assigned an investigation task:

1. **Pre-register** your hypothesis, method, controls, expected result, confounds, statistical test, and sample size BEFORE running any experiment.
2. **Wait for Methodologist approval** (Scientific+) before executing.
3. **Run the experiment** per the pre-registered design.
4. **Commit raw data** with SHA-256 hash to `data/raw/`.
5. **Run sensitivity analysis** — test at least 2 parameter variations.
6. **Create a FINDING entry** in Beads with full evidence trail (effect size, CI, N, p-value, data hash).
7. **Await review gates** — Statistician, then Critic (partially blinded at Scientific+).

## Scientific Integrity

- NEVER adjust your analysis after seeing results without documenting the deviation as `PRE_REG_DEVIATION`.
- NEVER report only the results that support your hypothesis — report ALL results.
- If you discover something unexpected, flag it as `SERENDIPITY:HIGH` — do not quietly incorporate it.
- If your findings contradict the working theory, report them clearly. Paradigm stress is valuable information.

## Epic Scoping

- Work ONLY on tasks under your assigned epic.
- If you discover work for a different epic, file it under that epic — do NOT do it yourself:
  ```bash
  bd create "Discovered: [description]" -t task -p 2 --notes "Found while working on [your task]"
  ```
