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

## Anti-Fabrication — MANDATORY
LLMs can unintentionally fabricate plausible-looking results. These rules prevent that:
- NEVER report numbers you didn't compute from actual data using actual code.
- ALWAYS commit experiment scripts to `experiments/` alongside raw data in `data/raw/`.
- ALWAYS compute statistics programmatically — write a script that reads the raw data and outputs the numbers.
- If an experiment fails, report honestly. NEVER re-run until you get a "nice" result.
- The merge gate runs `verify_finding_against_data()` which cross-checks reported N against data file rows, verifies data hashes, and flags suspiciously clean patterns.
- The convergence gate runs `audit_all_findings()` which blocks convergence if any finding has critical fabrication flags.
- The Statistician MUST independently recompute statistics from raw data — never trust agent-reported numbers alone.

## Anti-Simulation — MANDATORY
NEVER substitute real experiment execution with simulation. This is the most dangerous form of fabrication:
- NEVER create files named `*sim*`, `*mock*`, `*fake*` that replace real LLM/tool calls with `np.random` sampling.
- NEVER hardcode detection probabilities, scores, or effect sizes that the experiment is supposed to *measure*.
- NEVER create alternative runner scripts (e.g. `run_sim.py`) that bypass the mandated entry point.
- NEVER write `results.json` with model fields containing "simulated", "mock", or "fake".
- If the experiment requires too many LLM calls, reduce sample size — do NOT simulate. Fewer real data points are infinitely more valuable than any number of fake ones.
- The convergence gate runs `detect_simulation_bypass()` which scans for simulation code and blocks completion.
- A dry-run mode for debugging is acceptable ONLY if it writes NO output to `output/` and is clearly gated behind a `--dry-run` flag.

## Artifact Contracts — MANDATORY
Tasks may declare file-level dependencies in Beads notes. You MUST respect them:
- `PRODUCES:file1, file2` — Files you MUST create before closing the task. The quality gate rejects merges with missing outputs.
- `REQUIRES:file1, file2` — Files that must exist before you start. If missing, report BLOCKED and STOP.
- `GATE:path/to/validation.json` — Validation file that must exist AND contain PASS verdicts before you begin.
- NEVER close a task without verifying all PRODUCES artifacts exist.
- NEVER start work if REQUIRES or GATE artifacts are missing — report BLOCKED instead.
- When planning tasks, ALWAYS declare PRODUCES and REQUIRES for tasks that create or consume files.

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
| **Final Evaluation** | — | ✅ | ✅ | ✅ |
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

## Strategic Context — MANDATORY

Every agent receives strategic context explaining how their work fits the whole:

- **Read your `STRATEGIC_CONTEXT`** field in task notes at startup. It explains:
  - HOW your piece fits the overall investigation/project
  - WHY this task was prioritized
  - WHAT a strong or weak result means for the whole
  - Which DEAD ENDS to avoid
- **Do NOT re-explore dead ends** unless your approach is materially different from what was already tried.
- **Flag strategic misalignment** if your task's assumptions no longer hold:
  ```bash
  bd update <id> --notes "STRATEGIC_MISALIGNMENT: [what you found] contradicts [assumption]"
  ```
- The orchestrator maintains `.swarm/strategic-context.md` — read it for full context on the investigation's strategic direction.

## Final Evaluation (Analytical+ Rigor)

Before convergence is declared, the output is evaluated against the original abstract:

- The Synthesizer produces a final deliverable (`.swarm/deliverable.md`)
- The Evaluator scores it on: **Completeness**, **Coherence**, **Strength**, **Actionability**
- If below threshold: targeted improvement tasks are created and 1-2 more OODA cycles run
- **Max 2 improvement rounds** — then deliver with honest quality disclosure
- If last 2 rounds improved by < 5% each: **DIMINISHING_RETURNS** — deliver as-is with disclosure
- Process completion ≠ output quality. Gates passing does not mean the answer is good.
