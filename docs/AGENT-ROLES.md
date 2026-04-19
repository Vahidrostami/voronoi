# Agent Roles Specification

> 12 core roles + 4 paper-track roles, activation rules, verify loops, role interactions.

**TL;DR**: 12 core roles: Orchestrator (always), Builder+Critic (Standard+), Scout+Investigator+Explorer+Statistician+Synthesizer+Evaluator (Analytical+), Theorist+Methodologist (Scientific+), Scribe (LaTeX compilation). Plus **4 paper-track roles** (Outliner, Lit-Synthesizer, Figure-Critic, Refiner) activated only when producing a submission-ready manuscript via `/voronoi paper <codename>`. Each worker has a verify loop (test→retry→escalate). Roles defined in `src/voronoi/data/agents/*.agent.md`, never in Python.

## 1. Role Registry

| # | Role | File | Activation | Key Responsibility |
|---|------|------|-----------|-------------------|
| 1 | Orchestrator | `swarm-orchestrator.agent.md` | Always | OODA loop, convergence, paradigm checks |
| 2 | Builder | `worker-agent.agent.md` | Standard+ | Implements code in isolated worktree |
| 3 | Scout | `scout.agent.md` | Analytical+ | Prior knowledge research, SOTA anchoring |
| 4 | Investigator | `investigator.agent.md` | Analytical+ | Pre-registered experiments, raw data + SHA-256, directional classification |
| 5 | Explorer | `explorer.agent.md` | Analytical+ | Option evaluation with comparison matrices |
| 6 | Statistician | `statistician.agent.md` | Analytical+ | CI, effect sizes, data integrity, p-hacking flags, direction verification |
| 7 | Critic | `critic.agent.md` | Standard+ | Adversarial review; partially blinded at Scientific+ |
| 8 | Synthesizer | `synthesizer.agent.md` | Analytical+ | Consistency checks, claim-evidence registry, deliverable |
| 9 | Evaluator | `evaluator.agent.md` | Analytical+ | Scores deliverable: CCSAN formula (+ MS_QUALITY rubric on paper-track) |
| 10 | Theorist | `theorist.agent.md` | Scientific+ | Causal models, competing theories, paradigm stress, triviality screening, explanation audit |
| 11 | Methodologist | `methodologist.agent.md` | Scientific+ | Experimental design review, power analysis |
| 12 | Scribe | `scribe.agent.md` | Analytical+ | LaTeX paper compilation; enforces citation-coverage gate on paper-track |
| 13 | Outliner | `outliner.agent.md` | Paper-track | Produces `.swarm/manuscript/outline.json` (sections, figures, citation slots) |
| 14 | Lit-Synthesizer | `lit-synthesizer.agent.md` | Paper-track | Fills every citation slot with a Semantic Scholar-verified entry (Levenshtein ≥0.70) |
| 15 | Figure-Critic | `figure-critic.agent.md` | Paper-track | Text-only rubric over plotting script + `.meta.json` sidecar — no VLM needed |
| 16 | Refiner | `refiner.agent.md` | Paper-track + Scientific+ | Simulated peer review with safety halt rules; max 3 rounds |

## 2. Activation Rules

```
Standard      → Builder, Critic, Worker
Analytical    → + Scout, Investigator, Explorer, Statistician, Synthesizer, Evaluator
Scientific    → + Theorist, Methodologist
Experimental  → (all roles active + replication)

Paper-track (orthogonal — activated by `/voronoi paper <codename>`)
              → + Outliner, Lit-Synthesizer, Figure-Critic  (always)
              → + Refiner                                   (Scientific+ only)
```

The orchestrator selects roles based on the classified rigor level. Roles CANNOT be added after investigation start — only skipped.

**Paper-track is orthogonal to rigor.** It is activated when the enqueued investigation's question begins with `[PAPER-TRACK]` (produced by `handle_paper()` in `handlers_workflow.py`). Paper-track presupposes a completed parent investigation whose `.swarm/deliverable.md` + `.swarm/claim-evidence.json` are the inputs. The Refiner only joins at Scientific+ because its simulated peer-review loop requires the full science-gate audit trail to enforce its halt rules safely.

## 3. Role Details

### 3.1 Orchestrator

**File**: `src/voronoi/data/agents/swarm-orchestrator.agent.md`

**Always active.** The orchestrator is the only agent that runs in the main workspace. All other agents run in git worktrees.

**Responsibilities**:
- Run the OODA loop (Observe → Orient → Decide → Act)
- Maintain `.swarm/` state files (belief map, strategic context)
- Dispatch workers via `spawn-agent.sh`
- Merge completed work via `merge-agent.sh`
- Monitor convergence and paradigm stress
- Never enter a worker's worktree — dispatch, don't fix

**OODA Cycle**:
1. **Observe**: `bd ready`, findings, belief map, experiment ledger
2. **Orient**: Classify events, update strategic context, check convergence + paradigm stress
3. **Decide**: Information-gain priority, review gates, replication needs
4. **Act**: Spawn agents, merge work, accept findings, update belief map

### 3.2 Builder

**File**: `src/voronoi/data/agents/worker-agent.agent.md`

**Standard+ activation.** Implements code in isolated git worktree.

**Verify Loop**:
- Tests pass + lint clean + `PRODUCES` artifacts exist
- Max iterations: **5**
- Completion promise: `BUILD_COMPLETE`

**Artifact Contracts**:
- Checks `REQUIRES` at startup — reports BLOCKED if missing
- Verifies `PRODUCES` before closing task
- Respects `GATE` validation files

### 3.3 Scout

**File**: `src/voronoi/data/agents/scout.agent.md`

**Analytical+ activation.** Researches existing knowledge, SOTA, and research landscape positioning before investigation begins.

**Problem Positioning (Phase 0 — MANDATORY):**
Before any other research, the Scout:
1. Extracts the FIELD and sub-problem from the prompt
2. Runs `/research` queries to find the frontier, closest prior work, and specific gap
3. Performs deep methodology comparison with the closest published paper
4. Assesses novelty: NOVEL (proceed) / INCREMENTAL (proceed with framing) / REDUNDANT (halt)
5. If REDUNDANT: writes `.swarm/novelty-gate.json` and flags `NOVELTY_BLOCKED`

**Cross-Investigation Recall:** Before external search, queries prior Voronoi investigation findings to avoid re-testing confirmed claims.

**Outputs**:
- Knowledge brief with Problem Positioning section (field context, gap, closest work comparison)
- SOTA anchoring (what's the current best?)
- Identification of gaps in existing knowledge
- Novelty assessment grounded in live `/research` results

**Deep Research**: The scout uses the `deep-research` skill for literature review, prior-art search, and problem positioning queries. This skill leverages Copilot CLI's `/research` command to search GitHub repos + live web sources, providing citation-backed evidence instead of relying on LLM training data. See `.github/skills/deep-research/SKILL.md`.

**Verify Loop**:
- Knowledge brief written + Problem Positioning section complete + sources cited + novelty assessed
- Max iterations: **3**
- Completion promise: `SCOUT_COMPLETE`

### 3.4 Investigator

**File**: `src/voronoi/data/agents/investigator.agent.md`

**Analytical+ activation.** Runs pre-registered experiments with raw data preservation.

**Workflow**:
1. Pre-register hypothesis, method, controls, stat test
2. Wait for Methodologist approval (Scientific+)
3. Execute experiment per pre-registered design
4. Commit raw data with SHA-256 hash to `data/raw/`
5. Run sensitivity analysis (2+ parameter variations)
6. Submit to EVA (Experimental Validity Audit)
7. Create FINDING in Beads with full evidence trail

**Verify Loop**:
- Experiment runs without crash + metric extracted + EVA passed + raw data committed
- Max iterations: **3 per variant**
- Completion promise: `EXPERIMENT_COMPLETE`

### 3.5 Explorer

**File**: `src/voronoi/data/agents/explorer.agent.md`

**Analytical+ activation.** Evaluates options systematically.

**Outputs**:
- Comparison matrices
- Pros/cons with evidence
- Recommended option with justification

### 3.6 Statistician

**File**: `src/voronoi/data/agents/statistician.agent.md`

**Analytical+ activation.** Reviews all quantitative claims.

**Responsibilities**:
- Independently recompute statistics from raw data (NEVER trust agent-reported numbers)
- Verify confidence intervals, effect sizes, sample sizes
- Flag p-hacking, multiple comparisons, data dredging
- Add interpretation metadata to findings:

| Field | Description |
|-------|-------------|
| `INTERPRETATION` | Practical meaning in domain context |
| `PRACTICAL_SIGNIFICANCE` | Cohen's d category (negligible/small/medium/large/very large) |
| `SUPPORTS_HYPOTHESIS` | Which hypothesis this evidence tests |

### 3.7 Critic

**File**: `src/voronoi/data/agents/critic.agent.md`

**Standard+ activation.** Adversarial review with 5-check checklist.

**Plan Review Mode (Analytical+):** When dispatched with `TYPE:plan-review` in task notes, the Critic reviews the orchestrator's task decomposition instead of a finding. Uses a 6-point plan review checklist (coverage, granularity, dependencies, completeness, baseline anchoring, artifact chains). Writes verdict to `.swarm/plan-review.json`. At Scientific+, the Theorist also reviews; at Experimental, the Methodologist joins.

**At Scientific+**: Partially blinded — receives findings without knowing which agent produced them.

**Verify Loop**:
- All 5 checklist items evaluated
- Max iterations: **2**
- Completion promise: `REVIEW_COMPLETE`

### 3.8 Synthesizer

**File**: `src/voronoi/data/agents/synthesizer.agent.md`

**Analytical+ activation.** Assembles final deliverable.

**Outputs**:
- `.swarm/claim-evidence.json` — traceability registry
- `.swarm/deliverable.md` — final report or manuscript

**Verify Loop**:
- Claim-evidence registry complete + no orphan findings
- Max iterations: **3**
- Completion promise: `SYNTHESIS_COMPLETE`

### 3.9 Evaluator

**File**: `src/voronoi/data/agents/evaluator.agent.md`

**Analytical+ activation.** Scores the deliverable using CCSAN formula.

**CCSAN Formula**:
- **C**ompleteness — Are all questions addressed?
- **C**oherence — Does the narrative flow logically?
- **S**trength — Is every claim backed by evidence?
- **A**ctionability — Can someone act on the conclusions?
- **N**on-triviality — Are the findings informative vs trivially expected?

Score output: `.swarm/eval-score.json`

**Scoring Thresholds**:
- ≥ 0.75 → Converge
- 0.50 – 0.74 → Improvement round (max 2)
- < 0.50 → Deliver with quality disclosure

### 3.10 Theorist

**File**: `src/voronoi/data/agents/theorist.agent.md`

**Scientific+ activation.** Maintains causal models and competing theories.

**Responsibilities**:
- Build causal models from evidence
- Propose competing theories
- Detect paradigm stress (findings contradict working theory)
- Flag serendipitous discoveries
- **Triviality screening**: Classify hypotheses as NOVEL/EXPECTED/TRIVIAL during plan review
- **Explanation audit**: When findings are `refuted_reversed`, generate 2-3 competing explanations with discriminating experiments (Tribunal)
- **DAG revision**: After surprising findings, revise the causal DAG and document changes
- **Pre-convergence synthesis**: Verify the final narrative makes causal sense

### 3.11 Methodologist

**File**: `src/voronoi/data/agents/methodologist.agent.md`

**Scientific+ activation.** Reviews experimental designs.

**Gate power**:
- **Experimental**: Mandatory — no investigation proceeds without approval
- **Scientific**: Advisory — orchestrator can override with documented note

**Responsibilities**:
- Review pre-registrations before execution
- Conduct power analysis
- Post-mortem review of `DESIGN_INVALID` experiments
- Prescribe specific redesigns with validation steps
- **Tribunal participation**: Check for design artifacts and confounds when findings are surprising

### 3.12 Judgment Tribunal (Coordination Pattern)

**Not a role** — a coordination pattern involving Theorist + Statistician + Methodologist (+ Critic at pre-convergence).

**Triggers**: `refuted_reversed` hypothesis, contradiction between findings, `SURPRISING` flag, pre-convergence review (mandatory at Analytical+).

**Process**: Each participant evaluates the surprising finding from their perspective:
- Theorist: Explain vs causal model → competing explanations
- Statistician: Robustness check → sensitivity analysis + direction verification
- Methodologist: Design artifact check → confound analysis
- Critic (pre-convergence only): Adversarially challenge the tribunal's own explanations

**Output**: `.swarm/tribunal-verdicts.json` — verdict per finding.

**Verdicts**: EXPLAINED | ANOMALY_UNRESOLVED (blocks convergence) | ARTIFACT (DESIGN_INVALID) | TRIVIAL

### 3.13 Continuation Proposals

Generated automatically at review time by `generate_continuation_proposals()` from:
1. Tribunal verdicts with untested explanations (highest priority, information_gain=0.9)
2. Challenged claims with pending objections (information_gain=0.7)
3. Single-evidence claims needing replication (information_gain=0.5)

Ranked by information gain. Shown to PI during `/voronoi review` and `/voronoi deliberate`.

---

### 3.14 Outliner (Paper-track)

**File**: `src/voronoi/data/agents/outliner.agent.md`

**Paper-track activation.** First agent in the manuscript pipeline. Runs ONCE after the investigation converges and the user runs `/voronoi paper <codename>`.

**Responsibilities**:
- Decompose the original question + synthesizer's deliverable into a target abstract
- Assign section structure (Abstract / Intro / Related Work / Methods / Results / Discussion / Conclusion)
- Plan figures and tables from ROBUST findings in `.swarm/claim-evidence.json`
- Declare citation slots (`claim`, `kind`, `needs_n`) — the contract Lit-Synthesizer must fill

**Output**: `.swarm/manuscript/outline.json`

**Verify Loop**:
- `outline.json` validates as JSON; every `supports_claim` references a real claim-evidence entry
- Max iterations: **2**
- Completion promise: `OUTLINE_COMPLETE`

### 3.15 Lit-Synthesizer (Paper-track)

**File**: `src/voronoi/data/agents/lit-synthesizer.agent.md`

**Paper-track activation.** Distinct from the Scout: Scout grounds the *investigation*; Lit-Synthesizer grounds the *manuscript*. Runs after the Outliner, parallel with Figure-Critic.

**Responsibilities**:
- For every `citation_slot` in `outline.json`, generate queries and run Copilot CLI `/research`
- Verify each candidate via `literature.py` Semantic Scholar (free, unauthenticated) gated by `citation_coverage.fuzzy_match_title()` (Levenshtein ≥0.70)
- Write `.swarm/manuscript/citation-ledger.json` + `references.bib`
- Never fabricate: slots without verifiable candidates stay `"status": "unfilled"`

**Verify Loop**:
- ≥90% of citation slots filled with `verified: true` entries
- Every `bibtex_key` in the ledger appears in `references.bib`
- Max iterations: **3**
- Completion promise: `LIT_SYNTHESIS_COMPLETE`

### 3.16 Figure-Critic (Paper-track)

**File**: `src/voronoi/data/agents/figure-critic.agent.md`

**Paper-track activation.** Text-only figure quality rubric (no VLM needed — works with Copilot CLI alone). Reads the plotting script + mandatory `<fig>.meta.json` sidecar emitted by the producing agent.

**Rubric** (8 checks, per-figure): axes labeled, units present, caption self-contained, baseline shown, uncertainty shown, scale defensible, effect-size/N annotated, colour-blind-safe palette.

**Output**: `.swarm/manuscript/figure-ledger.json` with per-figure verdict ∈ {`accept`, `revise`, `reject`} and `required_fixes` list.

**Verify Loop**:
- Every figure in `outline.json` has a ledger entry
- Max iterations: **2**
- Completion promise: `FIGURE_CRITIC_COMPLETE`

### 3.17 Refiner (Paper-track + Scientific+)

**File**: `src/voronoi/data/agents/refiner.agent.md`

**Paper-track activation, Scientific+ only.** Runs LAST, after Scribe emits `paper.tex` and citation-coverage passes.

**Responsibilities**:
- Simulate an adversarial peer review
- For each proposed fix, screen against 5 safety halt rules (citation integrity, number integrity, claim consistency, evaluator-gaming, scope creep) before applying
- Re-run citation-coverage gate after each round; revert the round if coverage regresses
- Max **3 rounds total**

**Output**: `.swarm/manuscript/review-rounds/${N}.json` per round

**Verify Loop**:
- Paper still compiles, coverage audit still passes, every claim-evidence claim still appears
- Max iterations: **2 per round**
- Completion promise: `REFINEMENT_COMPLETE`

---

## 4. Verify Loop Protocol

Every worker agent runs an internal verify loop before declaring success or failure to the orchestrator.

### General Pattern

```
Execute task
     │
     ▼
Run verification (tests, lint, artifacts, metrics)
     │
     ├── PASS → [EVA for investigators] → Emit completion promise
     │
     └── FAIL → Pipe error context back → Retry (up to max)
                                              │
                                              └── EXHAUSTED → Escalate to orchestrator
```

### Context Management

- Error output summarized before re-injection (last 50 lines, not full output)
- Previous attempt logs referenced by file path, not pasted inline
- On final iteration: write `VERIFY_EXHAUSTED` note to Beads

### Verify Log Format

Each iteration appends to `.swarm/verify-log-<task-id>.jsonl`:

```json
{"iteration": 1, "status": "fail", "error_type": "test_failure", "summary": "3/12 tests failed", "timestamp": "..."}
{"iteration": 2, "status": "fail", "error_type": "lint", "summary": "unused import", "timestamp": "..."}
{"iteration": 3, "status": "pass", "summary": "all pass, PRODUCES verified", "timestamp": "..."}
```

### Per-Role Summary

| Role | Verification | Promise | Max Iter |
|------|-------------|---------|----------|
| Builder | Tests + lint + PRODUCES | `BUILD_COMPLETE` | 5 |
| Investigator | Experiment + metric + EVA + data | `EXPERIMENT_COMPLETE` | 3/variant |
| Scout | Brief written + sources cited | `SCOUT_COMPLETE` | 3 |
| Critic | 5-check list evaluated | `REVIEW_COMPLETE` | 2 |
| Synthesizer | Registry complete + no orphans | `SYNTHESIS_COMPLETE` | 3 |

---

## 5. Role Interactions

```
Orchestrator
     │
     ├── decomposes tasks (Plan phase)
     │
     ├── [Analytical+] dispatches → Critic for plan review
     │       [Scientific+] also → Theorist
     │       [Experimental] also → Methodologist
     │       └── verdict in .swarm/plan-review.json → Orchestrator revises if needed
     │
     ├── dispatches → Scout (first, for prior knowledge)
     │
     ├── dispatches → Investigator(s) / Builder(s) / Explorer(s) (in parallel)
     │                    │
     │                    └── [Scientific+] pre-reg reviewed by → Methodologist
     │
     ├── after workers complete:
     │       │
     │       ├── Statistician reviews findings
     │       ├── Critic reviews work (partially blinded at Scientific+)
     │       └── Theorist updates causal model
     │
     ├── Synthesizer assembles deliverable
     │
     └── Evaluator scores deliverable → convergence decision
```

---

## 6. Worker Prompt Construction

When the orchestrator dispatches a worker, the prompt includes:

1. Role file content from `src/voronoi/data/agents/<role>.agent.md` (copied to `src/voronoi/data/agents/` in investigation workspaces)
2. Task description from Beads
3. Metric contract (if investigation)
4. Strategic context
5. Artifact contracts (`PRODUCES`, `REQUIRES`, `GATE`)
6. Baseline finding value (if available)

The prompt builder (`prompt.py`) tells the orchestrator to prepend role file content to every worker prompt.
