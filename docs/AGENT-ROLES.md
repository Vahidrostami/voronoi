# Agent Roles Specification

> 12 agent roles, activation rules, verify loops, role interactions.

**TL;DR**: 12 roles: Orchestrator (always), Builder+Critic (Standard+), Scout+Investigator+Explorer+Statistician+Synthesizer+Evaluator (Analytical+), Theorist+Methodologist (Scientific+), Scribe (LaTeX compilation). Each worker has a verify loop (test→retry→escalate). Roles defined in `src/voronoi/data/agents/*.agent.md`, never in Python.

## 1. Role Registry

| # | Role | File | Activation | Key Responsibility |
|---|------|------|-----------|-------------------|
| 1 | Orchestrator | `swarm-orchestrator.agent.md` | Always | OODA loop, convergence, paradigm checks |
| 2 | Builder | `worker-agent.agent.md` | Standard+ | Implements code in isolated worktree |
| 3 | Scout | `scout.agent.md` | Analytical+ | Prior knowledge research, SOTA anchoring |
| 4 | Investigator | `investigator.agent.md` | Analytical+ | Pre-registered experiments, raw data + SHA-256 |
| 5 | Explorer | `explorer.agent.md` | Analytical+ | Option evaluation with comparison matrices |
| 6 | Statistician | `statistician.agent.md` | Analytical+ | CI, effect sizes, data integrity, p-hacking flags |
| 7 | Critic | `critic.agent.md` | Standard+ | Adversarial review; partially blinded at Scientific+ |
| 8 | Synthesizer | `synthesizer.agent.md` | Analytical+ | Consistency checks, claim-evidence registry, deliverable |
| 9 | Evaluator | `evaluator.agent.md` | Analytical+ | Scores deliverable: CCSA formula |
| 10 | Theorist | `theorist.agent.md` | Scientific+ | Causal models, competing theories, paradigm stress |
| 11 | Methodologist | `methodologist.agent.md` | Scientific+ | Experimental design review, power analysis |
| 12 | Scribe | `scribe.agent.md` | Analytical+ | LaTeX paper compilation |

## 2. Activation Rules

```
Standard      → Builder, Critic, Worker
Analytical    → + Scout, Investigator, Explorer, Statistician, Synthesizer, Evaluator
Scientific    → + Theorist, Methodologist
Experimental  → (all roles active + replication)
```

The orchestrator selects roles based on the classified rigor level. Roles CANNOT be added after investigation start — only skipped.

## 3. Role Details

### 3.1 Orchestrator

**File**: `src/voronoi/data/agents/swarm-orchestrator.agent.md`

**Always active.** The orchestrator is the only agent that runs in the main workspace. All other agents run in git worktrees.

**Responsibilities**:
- Run the OODA loop (Observe → Orient → Decide → Act)
- Maintain `.swarm/` state files (belief map, journal, strategic context)
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

**Analytical+ activation.** Researches existing knowledge and SOTA before investigation begins.

**Outputs**:
- Knowledge brief with cited sources
- SOTA anchoring (what's the current best?)
- Identification of gaps in existing knowledge

**Deep Research**: The scout uses the `deep-research` skill for literature review and prior-art search. This skill leverages Copilot CLI's `/research` command to search GitHub repos + live web sources, providing citation-backed evidence instead of relying on LLM training data. See `.github/skills/deep-research/SKILL.md`.

**Verify Loop**:
- Knowledge brief written + sources cited
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

**Analytical+ activation.** Scores the deliverable using CCSA formula.

**CCSA Formula**:
- **C**ompleteness — Are all questions addressed?
- **C**oherence — Does the narrative flow logically?
- **S**trength — Is every claim backed by evidence?
- **A**ctionability — Can someone act on the conclusions?

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
