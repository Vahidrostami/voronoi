# Science Layer Specification

> Pre-registration, belief maps, convergence, paradigm stress, consistency, EVA, anti-fabrication, data integrity.

**TL;DR**: Gates activate by rigor: Standard (none) → Analytical (+statistician, eval) → Scientific (+pre-reg, methodologist, blinding) → Experimental (+replication). EVA catches experiments that run but don't test what they claim. Baseline-first is a hard gate. All raw data gets SHA-256. Organized as `src/voronoi/science/` subpackage.

## 1. Overview

The science layer (`src/voronoi/science/`) enforces the scientific rigor framework. It is split into focused submodules:

| Submodule | Responsibility |
|-----------|---------------|
| `consistency.py` | Beads queries, consistency gate, paradigm stress, heartbeat stall, finding interpretation, claim-evidence I/O, success criteria I/O |
| `convergence.py` | Belief map, orchestrator checkpoint, convergence detection |
| `fabrication.py` | Anti-fabrication verification, simulation bypass detection |
| `gates.py` | Dispatch/merge gates, pre-registration, invariants, calibration, replication |
| `claims.py` | Cross-run claim ledger, provenance, objections, self-critique |

All public symbols are re-exported from `science/__init__.py`, so `from voronoi.science import X` works as before.

The gateway and execution layers consume these; the orchestrator and review agents drive them.

## 2. Rigor Level Gate Matrix

Rigor is determined by mode: DISCOVER uses adaptive rigor (starts analytical, escalates), PROVE uses scientific or experimental from the start.

| Gate | DISCOVER (initial) | DISCOVER (escalated) | PROVE (scientific) | PROVE (experimental) |
|------|:------------------:|:-------------------:|:-----------------:|:-------------------:|
| Code review (Critic inline) | YES | YES | YES | YES |
| Statistician review | — | YES | YES | YES |
| Finding interpretation | — | YES | YES | YES |
| Claim-evidence registry | — | YES | YES | YES |
| Final evaluation (CCSAN) | — | YES | YES | YES |
| Methodologist design review | — | YES (advisory) | YES (mandatory) | YES (mandatory) |
| Pre-registration | — | YES | YES | YES |
| Pre-reg compliance audit | — | YES | YES | YES |
| Power analysis | — | YES | YES | YES |
| Partial blinding for Critic | — | YES | YES | YES |
| Adversarial review loop | — | YES | YES | YES |
| Plan review | YES (Critic) | YES (Critic + Theorist) | YES (Critic + Theorist) | YES (Critic + Theorist + Methodologist) |
| Replication | — | — | — | YES |
| Citation-coverage (paper-track only) | — | — | YES (Scribe + Refiner) | YES (Scribe + Refiner) |

Paper-track gates (Outliner, Lit-Synthesizer, Figure-Critic, Refiner) are orthogonal to rigor — see §20.

## 3. Pre-Registration

### Purpose

Locks down experimental design BEFORE execution. Prevents post-hoc rationalization.

### PreRegistration Data Structure

```python
@dataclass
class PreRegistration:
    task_id: str
    hypothesis: str
    method: str
    controls: str
    expected_result: str
    confounds: str
    stat_test: str
    sample_size: str
    power_analysis: str       # Required at Scientific+
    sensitivity_plan: str     # Required at Scientific+
    approved_by: str          # Methodologist (Scientific+)
    deviations: list[str]     # Post-hoc deviations (must be documented)
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `.is_complete` | bool | All base fields populated |
| `.is_scientific_complete` | bool | Base + power_analysis + sensitivity_plan |

### Required Fields by Rigor

| Rigor | Required Fields |
|-------|----------------|
| Scientific | hypothesis, method, controls, expected_result, confounds, stat_test, sample_size, power_analysis, sensitivity_plan |
| Experimental | Same as Scientific |
| Analytical | Not required (but validated if present) |

### Functions

```python
def parse_pre_registration(notes: str) -> PreRegistration
def validate_pre_registration(task_notes: str, rigor: str) -> tuple[bool, list[str]]
```

`validate_pre_registration` returns `(valid, list_of_missing_fields)`.

---

## 4. Belief Map

### Purpose

Tracks hypotheses across OODA cycles with evidence-linked reasoning. Drives information-gain prioritization — the orchestrator pursues hypotheses with highest expected information gain. Each hypothesis records not just a confidence level but **why** the agent believes it and **what would change their mind**.

### Confidence Tiers

Instead of raw probabilities, hypotheses use ordinal confidence tiers that LLMs can reliably distinguish:

| Tier | Meaning | Uncertainty | When to use |
|------|---------|:-----------:|-------------|
| `unknown` | No idea either way | 1.0 | Initial hypothesis, no evidence gathered |
| `hunch` | Slight lean, minimal evidence | 0.7 | After literature scan or domain reasoning |
| `supported` | Evidence points this way | 0.4 | After one or more experiments/analyses |
| `strong` | Multiple independent lines agree | 0.15 | Multiple confirmations from different methods |
| `resolved` | Confirmed or refuted | 0.0 | Final state — investigation for this hypothesis is done |

Agents MUST provide a `rationale` when changing confidence or status, explaining what evidence drove the change.

### Data Structures

```python
CONFIDENCE_TIERS: dict[str, float] = {
    "unknown": 1.0, "hunch": 0.7, "supported": 0.4, "strong": 0.15, "resolved": 0.0,
}

@dataclass
class Hypothesis:
    id: str
    name: str
    prior: float           # Initial probability [0, 1] (legacy, kept for compat)
    posterior: float        # Updated probability [0, 1] (legacy, kept for compat)
    status: str            # untested | testing | confirmed | refuted | refuted_reversed | inconclusive | merged
    evidence: list[str]    # Finding IDs supporting/refuting
    testability: float     # How easily tested [0, 1]
    impact: float          # How important if true [0, 1]
    confidence: str        # Ordinal tier: unknown | hunch | supported | strong | resolved
    rationale: str         # Why the agent believes this — evidence chain
    next_test: str         # What experiment/analysis would change confidence

    @property
    def uncertainty(self) -> float: ...        # From confidence tier (preferred) or posterior
    @property
    def information_gain(self) -> float: ...   # uncertainty × impact × testability
```

```python
class BeliefMap:
    def add_hypothesis(self, h: Hypothesis) -> None: ...
    def update_hypothesis(self, id: str, posterior: float, status: str) -> None: ...
    def get_priority_order(self) -> list[Hypothesis]: ...  # Sorted by information_gain DESC
    def all_resolved(self) -> bool: ...                     # All confirmed or rejected
    def summary(self) -> dict: ...                           # {total, by_status, cycle}
```

### File Location

`.swarm/belief-map.json` — read/written by orchestrator at each OODA cycle.

**Schema contract**: `hypotheses` MUST be a JSON array of objects (not an object map keyed by ID). Both the Python loader and the shell convergence gate validate this on load. Non-conforming data (e.g., object maps) is automatically migrated to the array format and **persisted back to disk** so subsequent reads don't re-trigger migration warnings.

Legacy data without `confidence`/`rationale`/`next_test` fields is accepted — the loader infers `confidence` from `posterior` and defaults `rationale`/`next_test` to empty strings.

### Functions

```python
def load_belief_map(workspace: Path) -> BeliefMap
def save_belief_map(workspace: Path, bm: BeliefMap) -> None
```

---

## 5. Convergence Detection

### Purpose

Determines when an investigation is complete. Criteria vary by rigor level.

### ConvergenceResult

```python
@dataclass
class ConvergenceResult:
    converged: bool
    status: str           # converged | not_converged | exhausted | negative_result
    reason: str           # Human-readable explanation
    score: float          # 0.0 – 1.0 convergence score
    blockers: list[str]   # What's preventing convergence
```

The `negative_result` status indicates a scientifically valid negative outcome: the investigation ran correctly but the hypothesis was falsified. This is a completed investigation, not a failure.

### Convergence Criteria by Rigor

| Rigor | Requirements |
|-------|-------------|
| Standard | All tasks closed, tests passing |
| Analytical | + Statistician reviewed, no contradictions, eval score ≥ 0.75 |
| Scientific | + All hypotheses resolved, competing theory ruled out, novel prediction tested, no PARADIGM_STRESS |
| Experimental | + All high-impact findings replicated, pre-reg compliance, power analysis documented |

### Convergence Gate Script (`convergence-gate.sh`)

The dispatcher runs `convergence-gate.sh` before writing `convergence.json`. It performs multi-signal validation:

| Check | Rigor | Blocks | What it validates |
|-------|-------|--------|-------------------|
| 1 | All | Yes | `deliverable.md` exists |
| 2 | Analytical+ | Yes | `eval-score.json` valid (0 < score ≤ 1) |
| 3 | Analytical+ | Warn | `claim-evidence.json` integrity |
| 4 | Scientific+ | Yes | No CONTESTED findings still open |
| 5 | Scientific+ | Yes | All hypotheses resolved in belief map |
| 6 | Analytical+ | Yes | Anti-fabrication audit |
| 7 | Analytical+ | Yes/Warn | Simulation-bypass detection |
| 8 | Analytical+ | Yes | Data invariants (min_csv_rows, etc.) |
| 9 | All | Warn | Figure integrity (figure-lint if LaTeX present) |
| 10 | All | Yes | Paper compilation: if `.tex` source or SC requires paper, `paper.pdf` must exist |

### Functions

```python
def check_convergence(
    workspace: Path,
    rigor: str,
    eval_score: float = 0.0,
    improvement_rounds: int = 0
) -> ConvergenceResult

def write_convergence(workspace: Path, result: ConvergenceResult) -> Path
```

### Evaluator Score Thresholds

| Score | Action |
|-------|--------|
| ≥ 0.75 | Converge |
| 0.50 – 0.74 | Improvement round (max 2) |
| < 0.50 | Deliver with quality disclosure |

### Structured Evaluator Feedback

The evaluator produces section-level scores and concrete remediations:

```json
{
  "score": 0.82, "rounds": 1,
  "dimensions": {
    "completeness": {"score": 0.85, "note": "Missing sensitivity analysis"},
    "coherence": {"score": 0.75, "note": "Section 3 contradicts Section 5"},
    "strength": {"score": 0.70, "note": "Finding bd-43 N=12, too small"},
    "actionability": {"score": 0.90, "note": "Good parameter ranges"}
  },
  "remediations": [
    "Run sensitivity analysis varying K from 0.1 to 1.0",
    "Resolve Section 3 vs Section 5 contradiction"
  ]
}
```

The `remediations` list drives improvement rounds — the orchestrator creates targeted tasks from these instead of guessing what needs to improve.

### Human Review Gates (Scientific+ Rigor)

At Scientific and Experimental rigor, the investigation pauses for human approval:

| Gate | When | Mechanism |
|------|------|-----------|
| Pre-registration | After pre-reg, before experiments | Write `.swarm/human-gate.json` with `status: "pending"` |
| Convergence | Before finalizing deliverable | Same file, new gate entry |

The dispatcher detects pending gates and sends a Telegram message. The human replies `/approve <id>` or `/revise <id> <feedback>`. The orchestrator **parks and exits** at the gate (writes the gate file, writes a checkpoint with `active_workers: []` and `phase: "awaiting-human-gate"`, terminates); it must not sleep or poll the gate file in-session. The dispatcher kills any still-alive session, and on approval/revision restarts the agent with a resume prompt that reads the updated gate status.

This prevents the system from spending hours on a flawed methodology that a human would catch in minutes.

### Plan Review Gate (Analytical+ Rigor)

At Analytical rigor and above, the orchestrator's task decomposition is reviewed before workers are dispatched. This is the most consequential quality gate — it catches flawed plans before any compute is spent.

**Activation by rigor:**

| Rigor | Reviewers | Mode |
|-------|-----------|------|
| Standard | — (skipped) | Build tasks use verify loop |
| Analytical+ | Critic | Single reviewer |
| Scientific+ | Critic + Theorist | Two reviewers |
| Experimental | Critic + Theorist + Methodologist | Full panel |

**Flow:** Orchestrator decomposes → dispatches reviewer(s) with `TYPE:plan-review` → reviewer writes `.swarm/plan-review.json` → orchestrator revises plan if needed → dispatch workers.

**One round only** — propose → review → revise → dispatch. No iterative loops.

**Review checklist (used by Critic in plan-review mode):**

1. Does the plan answer the original question?
2. Are tasks properly scoped (30-min rule)?
3. Are dependencies correct and non-circular?
4. Is anything missing? Redundant?
5. Can baseline anchor all experiments?
6. Do PRODUCES/REQUIRES chains connect?

**Review output** (`.swarm/plan-review.json`):

```json
{
  "reviewer": "critic-bd-05",
  "verdict": "APPROVED|REVISE|RESTRUCTURE",
  "coverage": "assessment of whether plan answers original question",
  "granularity": ["task X is too large — split..."],
  "dependencies": ["task Y should depend on task Z"],
  "missing": ["need a negative control task"],
  "redundant": ["tasks A and B test the same thing"],
  "strategic": "overall strategic assessment"
}
```

**Verdicts:**
- **APPROVED** — Plan is sound, proceed to dispatch
- **REVISE** — Minor issues, orchestrator adjusts tasks and proceeds
- **RESTRUCTURE** — Major issues, orchestrator must re-decompose before dispatching

### Diminishing Returns Rule

If the last 2 improvement rounds improved by < 5% each → `DIMINISHING_RETURNS` — deliver as-is with disclosure.

---

## 6. Paradigm Stress Detection

### Purpose

Detects when findings contradict the working theory. Paradigm stress is valuable information — it means the investigation's mental model needs revision.

### ParadigmStressResult

```python
@dataclass
class ParadigmStressResult:
    stressed: bool
    contradiction_count: int
    contradicting_findings: list[str]    # Finding IDs
    message: str
```

### Function

```python
def check_paradigm_stress(workspace: Path) -> ParadigmStressResult
```

### Invariant

At Scientific+ rigor, convergence MUST NOT be declared while paradigm stress is active. The orchestrator must either resolve contradictions or revise the working theory.

---

## 7. Consistency Checking

### Purpose

Detects contradictions between findings within an investigation.

### ConsistencyConflict

```python
@dataclass
class ConsistencyConflict:
    finding_a: str
    finding_b: str
    conflict_type: str     # direction | magnitude | interpretation
    description: str
```

### Function

```python
def check_consistency(findings: list[dict]) -> list[ConsistencyConflict]
```

---

## 8. Experimental Validity Audit (EVA)

### Purpose

Catches experiments that run successfully and produce numbers, but **don't actually test what they claim**. This happens when practical constraints (context window limits, memory ceilings, caching) silently collapse the independent variable.

### The Problem It Solves

Example: An encoding ablation study with 4 levels. The encoder produces 33K chars at Level 1, but the LLM context window truncates everything to 6K chars. All four levels present identical content. The experiment "runs" — produces F1 scores — but measured nothing.

### Three Mandatory Checks

| Check | Question | Catches |
|-------|----------|--------|
| Manipulation check | Was the independent variable actually varied? | Truncation collapse, identical configs, caching, shared state |
| Artifact check | Did practical constraints nullify the manipulation? | Context window limits, memory ceilings, rate limiting, overflow |
| Sanity check | Is the effect size plausible given the design? | Genuine null results vs. broken manipulations |

### Decision Tree

```
Experiment produces a number
  │
  ├─ Check 1: Were conditions actually different? ── NO → DESIGN_INVALID
  │
  ├─ Check 2: Any practical artifacts? ── YES → DESIGN_INVALID
  │
  ├─ Check 3: Effect size ≈ 0?
  │     ├─ Manipulation verified? YES → Valid null result (report as negative finding)
  │     └─ Manipulation broken? → DESIGN_INVALID
  │
  └─ All pass → commit finding
```

### DESIGN_INVALID Escalation Path

1. Investigator flags `DESIGN_INVALID` with diagnosis + proposed fix
2. Orchestrator classifies as `design_invalid` event in OODA Orient
3. Orchestrator dispatches Methodologist for post-mortem review
4. Methodologist prescribes redesign with validation step
5. New experiment task: first step validates fix before running full experiment

### Key Principle

A null result from a **valid** experiment = valuable finding.
A null result from an **invalid** experiment = garbage.
EVA distinguishes the two.

---

## 9. Metric Contracts

### Purpose

Structured agreement between orchestrator and worker about what success looks like. Bridges open-ended investigations with comparable cross-agent metrics.

### Contract Structure

At dispatch (orchestrator declares shape):

```
METRIC_CONTRACT:
  PRIMARY: {name: TBD, direction: lower_is_better|higher_is_better, type: numeric|categorical|binary}
  CONSTRAINT: {name: "runtime_seconds", max: 600}
  BASELINE_TASK: bd-17
  ACCEPTANCE: {min_effect_size: 0.5, max_p_value: 0.05}
```

At pre-registration (worker fills concrete):

```
METRIC_FILLED:
  PRIMARY: {name: "accuracy_retention_pct", direction: higher_is_better, baseline_value: 45.2}
  CONSTRAINT: {name: "runtime_seconds", actual: 312}
```

### Metric Contract Flow

| Step | Who | What |
|------|-----|------|
| Dispatch | Orchestrator | Declares metric shape + baseline task reference |
| Pre-registration | Worker | Fills concrete metric name, expected value, stat test |
| Execution | Worker | Runs experiment, logs raw data |
| Self-eval | Worker | Compares result to baseline (keep/discard) |
| Finding | Worker | Reports effect size, CI, N |
| Metric review | Statistician | Validates metric choice is appropriate |
| Comparison | Orchestrator | Compares findings across agents |

### Common Metric Shapes

| Task Type | Primary Metric | Direction | Constraint |
|-----------|---------------|-----------|------------|
| Performance comparison | Accuracy, F1, loss | context-dependent | Runtime, memory |
| Ablation study | Delta from baseline | smaller = less important | None |
| Scaling experiment | Metric at different N | varies | Compute budget |
| Bug investigation | Reproduction rate | lower = better | None |
| Architecture search | val_loss | lower = better | VRAM, time |
| Build task | Tests passing | binary | None |

### Baseline-First Protocol

Every investigation epic's first subtask is ALWAYS a baseline measurement. This is a **hard gate**:

1. Baseline task created as first subtask
2. All experimental tasks blocked until baseline completes
3. Baseline finding becomes anchor in belief map
4. All agents receive baseline finding ID + value in their metric contract

---

## 10. Experiment Sentinel

### Purpose

Catches broken experiments **during execution** instead of after 30 hours of wasted compute. The Sentinel is an autonomous validation loop in the dispatcher that checks machine-readable experiment contracts against actual outputs.

### The Problem It Solves

Example: An encoding ablation study declares 4 conditions. The encoder produces L4 at 3% of L1's char count instead of the required 70–150%. The experiment runs all 36 scenarios across all 4 cells, consuming 30 hours of LLM calls, before anyone notices the manipulation collapsed. EVA (§8) would catch this — but only if the orchestrator runs it. The Sentinel catches it structurally, without relying on the orchestrator's attention.

### Architecture

```
Orchestrator writes .swarm/experiment-contract.json
  ↓
Dispatcher sentinel_audit() runs at:
  - contract file created/changed
  - required output files produced
  - phase gate crossings
  - periodic timer (every 6h)
  ↓
Checks contract against actual artifacts
  ↓
Pass → .swarm/sentinel-audit.json (timestamped)
Fail → DESIGN_INVALID + Telegram alert
```

### Experiment Contract

Written by the orchestrator after experiment design, BEFORE dispatching workers.

```python
@dataclass
class ExperimentContract:
    experiment_id: str
    independent_variable: str
    conditions: list[str]
    manipulation_checks: list[ManipulationCheck]
    required_outputs: list[dict]      # [{path, description}]
    degeneracy_checks: list[DegeneracyCheck]
    phase_gates: list[PhaseGate]
```

### Check Types

| Type | Purpose | Catches |
|------|---------|---------|
| `hash_distinct` | Field values differ across conditions | IV collapsed (identical encodings, same config) |
| `value_range` | Numeric field within [min, max] | Ratio violations, out-of-spec parameters |
| `metric_range` | Field std >= threshold | Degenerate metrics (all cells identical) |
| `not_identical` | Values not all the same | Identical outputs across conditions |
| `min_distinct_values` | At least N distinct values | Collapsed categorical variables |

### Phase Gates

Multi-phase experiments declare phase gate checks. The sentinel validates these when the orchestrator crosses phase boundaries:

```python
@dataclass
class PhaseGate:
    from_phase: str
    to_phase: str
    checks: list[dict]  # ManipulationCheck or DegeneracyCheck as dicts
```

### Audit Triggers

| Trigger | When | Why |
|---------|------|-----|
| `contract_changed` | `.swarm/experiment-contract.json` modified | Re-validate after design changes |
| `output_produced` | Any `required_outputs` file modified | Check outputs as they arrive |
| `phase_transition` | Orchestrator checkpoint phase differs from last audited phase | Validate before committing to next phase |
| `periodic` | Every N hours (default 6) | Safety net for anything missed |

### Missing Contract Detection

At Analytical+ rigor, if the orchestrator has created experiment-type tasks but no `.swarm/experiment-contract.json` exists after 1 hour, the sentinel warns and writes a directive forcing the orchestrator to write the contract. This prevents the sentinel from being silently bypassed by omission.

### Empty-Resolve Handling

When a target file exists but the declared field path resolves to no values, the sentinel distinguishes between:
- **File not yet produced** → skip (pre-execution)
- **File exists but field path resolves empty** → pass with warning (likely contract error)
- **File exists and field path resolves to non-numeric values** → pass with warning

This prevents silent false-passes when the contract's field paths don't match the actual output structure.

### Unknown-Schema Handling

`load_experiment_contract` accepts only dicts with at least one recognized top-level key (`experiment_id`, `independent_variable`, `conditions`, `manipulation_checks`, `required_outputs`, `degeneracy_checks`, `phase_gates`). A JSON object that omits all of these (e.g., a nested-by-study shape like `{"studies": {"study1": {...}}}`) is rejected with a warning log and returns `None`.

When `validate_experiment_contract` then detects the on-disk file still exists, it produces a critical-failure audit (`CONTRACT_SCHEMA: experiment-contract.json unparseable or unknown shape`) rather than silently returning `passed=True` with zero checks. This closes a false-positive path where an orchestrator's off-schema contract produced consecutive passing audits while running no validation at all.

The orchestrator prompt §Experiment Contract embeds the schema verbatim (top-level keys + a JSON skeleton) so that agents writing the contract for the first time cannot invent an off-schema shape (`studies`, `phases`, `hard_gates`, `primary_metric`, `runner` were observed in the wild). The dispatcher's `sentinel_violation` directive distinguishes `CONTRACT_SCHEMA` failures (instructs orchestrator to rewrite the file directly, no Methodologist) from genuine design failures (Methodologist + REVISE task).

To prevent log spam while the orchestrator iterates on a malformed contract, repeated rejections of the same key-set in the same workspace are demoted to DEBUG after the first WARNING — the dispatcher polls every 30s and would otherwise emit thousands of identical lines.

### Escalation Path

When the sentinel finds a critical failure:
1. Writes `.swarm/sentinel-audit.json` (persisted for orchestrator to read)
2. Writes `.swarm/dispatcher-directive.json` with `directive: sentinel_violation` and `action: stop_and_fix` (forces orchestrator to act)
3. Returns `design_invalid` event (triggers Telegram alert to PI)
4. `_is_complete()` returns False while DESIGN_INVALID exists (hard gate — cannot be bypassed)
5. **Structural dispatch block (INV-50).** `spawn-agent.sh` reads `.swarm/dispatcher-directive.json` before claiming any task. If `action == "stop_and_fix"` (or a legacy directive has `directive == "sentinel_violation"`), it refuses to spawn any task whose title does not match the methodologist/post-mortem/revise/fix-contract/sentinel pattern, and marks the task BLOCKED in Beads. This catches orchestrators that ignore the sentinel directive in their prompt: no new workers can burn hours on invalid data.

The directive explicitly states: "This IS a DESIGN_INVALID event — do NOT create a separate DESIGN_INVALID task." This prevents duplicate escalation.

### Relationship to EVA

EVA (§8) is a **semantic** check performed by the investigator agent — "was the IV actually varied?" requires understanding the domain. The Sentinel is a **structural** check performed by the dispatcher — "does this hash match? is this number in range?" requires no domain understanding. They are complementary:

| | EVA | Sentinel |
|---|---|---|
| Who runs it | Investigator agent | Dispatcher (autonomous) |
| When | After experiment completion | During execution |
| What it checks | Semantic validity | Structural contract compliance |
| Can be skipped | Only if orchestrator forgets | Never (runs automatically) |
| Domain knowledge | Required | Not required |

### Functions

```python
def load_experiment_contract(workspace: Path) -> ExperimentContract | None
def save_experiment_contract(workspace: Path, contract: ExperimentContract) -> None
def validate_experiment_contract(workspace: Path, contract: ExperimentContract | None = None, trigger: str = "periodic") -> SentinelAuditResult
def validate_phase_gate(workspace: Path, contract: ExperimentContract, from_phase: str, to_phase: str) -> SentinelAuditResult
```

### Invariant

**INV-39**: At Analytical+ rigor, experiments with a declared contract MUST pass the Sentinel audit before phase gate crossings. The dispatcher enforces this structurally — it does not rely on the orchestrator to check.

---

## 11. Anti-Fabrication

### Purpose

Prevents LLMs from fabricating plausible-looking results.

### FabricationFlag

```python
@dataclass
class FabricationFlag:
    severity: str       # critical | warning | info
    category: str       # missing_data | hash_mismatch | missing_script | suspicious_pattern
    message: str
    finding_id: str
```

### AntiFabricationResult

```python
@dataclass
class AntiFabricationResult:
    finding_id: str
    passed: bool
    flags: list[FabricationFlag]
    data_file_exists: bool
    hash_verified: bool
    experiment_script_exists: bool
    numbers_verified: bool

    @property
    def critical_flags(self) -> list[FabricationFlag]: ...
```

### Function

```python
def verify_finding_against_data(
    workspace: Path,
    finding_notes: str,
    finding_id: str = ""
) -> AntiFabricationResult
```

### Checks Performed

1. Data file referenced in finding actually exists
2. SHA-256 hash matches recorded hash
3. Experiment script exists in `experiments/`
4. Reported N matches actual data file rows
5. Flags suspiciously clean patterns (too-perfect numbers)

---

## 12. Data Integrity

### Functions

```python
def compute_data_hash(filepath: Path) -> str        # SHA-256 hex digest
def verify_data_hash(filepath: Path, expected_hash: str) -> bool
```

All raw data files MUST be hashed immediately after collection. Hash stored in finding metadata.

---

## 13. Lab Notebook

### Purpose

Preserves narrative continuity across OODA cycles.

### LabNotebookEntry

```python
@dataclass
class LabNotebookEntry:
    cycle: int
    phase: str           # observe | orient | decide | act
    verdict: str         # Summary of this phase
    metrics: dict        # Key metrics at this point
    failures: list[str]  # What went wrong
    next_steps: list[str]
    timestamp: str
```

### Functions

```python
def load_lab_notebook(workspace: Path) -> list[LabNotebookEntry]
def append_lab_notebook(workspace: Path, entry: LabNotebookEntry) -> None
```

File location: `.swarm/lab-notebook.json`

---

## 14. Experiment Ledger

### Purpose

Append-only, human-readable TSV. Quick chronological audit trail for ALL experiment attempts.

### Format

```
timestamp	task_id	branch	metric_name	metric_value	status	description
2026-03-11T08:15:00Z	bd-17	baseline	accuracy_pct	45.2	keep	Baseline
2026-03-11T08:22:00Z	bd-18	ewc	accuracy_pct	67.8	keep	EWC lambda=400
2026-03-11T08:30:00Z	bd-19	replay	accuracy_pct	0.0	crash	OOM at buffer=50000
```

### Rules

- Tab-separated (commas break in descriptions)
- Header row written at investigation start
- Each agent appends one row per experiment attempt (including crashes)
- Status: `keep` | `discard` | `crash`
- NOT committed to git — ephemeral workspace state
- File: `.swarm/experiments.tsv`

---

## 15. Claim-Evidence Traceability

### Purpose

Every claim in the deliverable MUST trace to specific finding IDs. Prevents unsupported claims.

### File: `.swarm/claim-evidence.json`

```json
[
  {
    "claim": "EWC outperforms baseline by 22%",
    "finding_ids": ["bd-18"],
    "hypothesis_ids": ["H1"],
    "strength": "robust",
    "interpretation": "..."
  }
]
```

### Strength Labels

- `robust` — replicated, large effect, narrow CI
- `provisional` — single source, moderate effect
- `weak` — small effect or wide CI
- `unsupported` — no evidence found

### Audit Flags

- **Orphan findings**: Findings not cited in any claim
- **Unsupported claims**: Claims with no evidence
- **Coverage score**: % of findings incorporated into claims

---

## 16. Anti-Simulation Enforcement

### Purpose

Prevents substituting real experiment execution with simulation.

### Prohibited Patterns

- Files named `*sim*`, `*mock*`, `*fake*` that replace real LLM/tool calls with `np.random`
- Hardcoded detection probabilities or effect sizes
- Alternative runner scripts that bypass the mandated entry point
- `results.json` with model fields containing "simulated", "mock", "fake"

### Exception

Dry-run mode for debugging is acceptable ONLY if:
- Gated behind `--dry-run` flag
- Writes NO output to `output/`

---

## 17. Claim Ledger — Cross-Run Scientific State

### Purpose

The Claim Ledger tracks paper-level assertions across multiple runs of the same investigation lineage, enabling iterative science: lock what's solid, challenge what's doubtful, carry results forward.

### Module

`src/voronoi/science/claims.py` — all public symbols re-exported from `voronoi.science`.

### Key Concepts

- **Claim**: A paper-level assertion with provenance tag (`model_prior` | `retrieved_prior` | `run_evidence`), status (`provisional` → `asserted` → `locked` | `challenged` | `replicated` | `retired`), and artifact chain.
- **Objection**: A structured doubt targeting a specific claim, with type (`confound` | `power` | `methodology` | `interpretation` | `scope`) and resolution status.
- **ClaimArtifact**: A file in the workspace that supports a claim (data, code, result, figure, model).
- **Lineage**: A chain of investigations linked by `parent_id`. Investigations in the same lineage share a Claim Ledger.

### Storage

`~/.voronoi/ledgers/<lineage_id>/claim-ledger.json`

The `lineage_id` is the ID of the root investigation in a `parent_id` chain. Set automatically on enqueue.

### Claim Lifecycle

```
Finding made → provisional → asserted → locked → replicated
                    ↓             ↓         ↓
               challenged    challenged  challenged
                    ↓             ↓         ↓
                retired       retired    retired
```

### Dispatcher Integration

During progress polling, the dispatcher syncs Beads findings to the Claim Ledger:
- Scout/literature findings → `retrieved_prior` provenance
- Investigator findings → `run_evidence` provenance
- On convergence: provisional claims promoted to `asserted`, self-critique generated

A task is treated as a finding ONLY when its title **starts with** `FINDING:`, `FINDING -`, or `FINDING —` (case-insensitive). Substring matches on "findings" in arbitrary titles (e.g. "Analyze pricing dataset for five action-changing findings") are explicitly rejected — otherwise task titles launder into provisional claims, inflating the ledger with verb-phrase ghost-claims that satisfy success criteria and mask genuine learning stalls. See INV-47.

### Claim Statement Shape

A claim is a *proposition* about the world — a statement that can be true or false given evidence. It is NOT a task directive. `ClaimLedger.add_claim` validates each incoming statement via `validate_claim_statement` and raises `ValueError` on:

- **Empty or whitespace-only** statements.
- **Bare-imperative task directives**: statements that begin with `Analyze`, `Analyse`, `Investigate`, `Run`, `Check`, `Explore`, `Examine`, `Study`, `Review`, `Assess`, `Evaluate`, `Test`, `Verify`, `Look`, `Find`, `Identify`, `Determine`, or `Survey` AND contain no relational marker. An imperative-shaped statement that carries a concrete proposition (e.g. "Test whether L4 > L1") is accepted because it includes a relational marker.
- **Exact duplicates** (after normalization — lowercase, collapsed whitespace, stripped trailing punctuation) against any existing claim in the same ledger.

Effect-size anchoring (`effect_summary`) is encouraged but **not required** — hunches without quantitative backing are still legitimate propositions in DISCOVER mode. The MCP tool surface enforces the same shape via `voronoi.mcp.validators.require_claim_statement`.

When the dispatcher's Beads-to-Ledger sync produces a statement that fails validation, it logs at INFO level and skips the task rather than crashing the poll loop — the finding task stays closed, no provisional claim is created.

### Self-Critique

At convergence, `generate_self_critique()` identifies weak claims:
- Single-finding evidence (recommends replication)
- Unverified model priors
- Low sample sizes (N < 100)

Self-critique objections have `raised_by: "self_critique"` and `status: "surfaced"`.

### Immutability

Locked claims' supporting artifacts become immutable in subsequent runs. The dispatcher writes `file_unchanged` invariants to `.swarm/invariants.json` during workspace handoff, enforced by the convergence gate.

### Warm-Start Brief

`build_warm_start_context()` in `prompt.py` reads the Claim Ledger to generate a structured context for continuation prompts, including:
- Established claims (do not re-test)
- Challenged claims (must address)
- Pending objections
- Immutable artifact paths
- PI feedback

---

## 18. Scientific Interpretation Layer

### Purpose

The interpretation layer adds *semantic judgment* to the existing structural gates (EVA, Sentinel, metric contracts). It answers: "Does this result make scientific sense?" — not just "Did the experiment run correctly?"

### Module

`src/voronoi/science/interpretation.py` — all public symbols re-exported from `voronoi.science`.

### Four Mechanisms

#### 18.1 Directional Hypothesis Verification

Every finding carries a three-state directional classification:

| State | Meaning | Trigger |
|-------|---------|---------|
| `confirmed` | Significant + correct direction | Normal flow |
| `refuted_reversed` | Significant + **opposite** direction | Triggers Judgment Tribunal |
| `inconclusive` | Not significant | No action needed |

The Investigator classifies direction at finding-commit time by comparing observed effect direction to the pre-registered `EXPECTED_DIRECTION` field. The Statistician verifies at review time.

**Convergence impact**: A `refuted_reversed` hypothesis blocks convergence at Analytical+ rigor until the finding is explained by a Tribunal verdict.

```python
def classify_direction(expected_direction: str, observed_direction: str, significant: bool) -> str
```

#### 18.2 Triviality Screening

Classifies hypotheses as NOVEL / EXPECTED / TRIVIAL during plan review. The Theorist performs this classification; `screen_triviality()` provides a structured output format.

| Classification | Action |
|---|---|
| `novel` | Full experiment |
| `expected` | Sanity check, don't headline |
| `trivial` | Skip or reframe |

```python
def screen_triviality(hypothesis_id: str, hypothesis_statement: str, ...) -> TrivialityResult
```

#### 18.3 Interpretation Requests & Judgment Tribunal

When a finding contradicts the causal model, an `InterpretationRequest` triggers the Judgment Tribunal — a multi-agent deliberation (Theorist + Statistician + Methodologist, plus Critic at pre-convergence).

**Triggers**: `refuted_reversed`, contradiction, `SURPRISING` flag, pre-convergence review.

**Tribunal output**: `.swarm/tribunal-verdicts.json` — a list of `TribunalResult` objects.

| Verdict | Action | Convergence |
|---------|--------|:-----------:|
| `explained` | Explanation tested from existing data | Allowed |
| `anomaly_unresolved` | Needs new experiment | **Blocked** |
| `artifact` | Experimental design flaw | **Blocked** (DESIGN_INVALID) |
| `trivial` | Result is obvious | Allowed, downgraded in deliverable |

**Tribunal composition**:

| Tribunal Type | When | Agents |
|---|---|---|
| Mid-run | REFUTED_REVERSED or SURPRISING detected | Theorist + Statistician + Methodologist |
| Pre-convergence | Before any convergence at Analytical+ | Theorist + Statistician + Methodologist + Critic |

```python
def check_tribunal_clear(workspace: Path) -> tuple[bool, list[str]]
def has_reversed_hypotheses(workspace: Path) -> tuple[bool, list[str]]
```

#### 18.4 Continuation Proposals

After self-critique, the system generates ranked follow-up experiment proposals from tribunal verdicts, challenged claims, and single-evidence claims.

```python
def generate_continuation_proposals(ledger: ClaimLedger, tribunal_results: list[TribunalResult] | None = None) -> list[ContinuationProposal]
```

Proposals are ranked by information gain and saved to `.swarm/continuation-proposals.json` for PI review during `/deliberate` or `/review`.

### Evaluator Scoring: CCSAN

The evaluator formula gains a fifth dimension **N (Non-triviality)**:

$$\text{OVERALL} = 0.25C + 0.20C_o + 0.20S + 0.15A + 0.20N$$

Non-triviality below 0.4 triggers an improvement round.

---

## 19. Run Manifest — Structured Deliverable

### Purpose

The **Run Manifest** (`.swarm/run-manifest.json`) is a consolidated, machine-readable summary of a completed run: question, answer, primary claims, hypotheses, experiments, artifacts, caveats, provenance. It is **derived** from existing `.swarm/` state — it does not replace `claim-evidence.json`, `eval-score.json`, or the Claim Ledger; it collates them so that scientists, reviewers, and external graders can read one file instead of six.

### Module

`src/voronoi/science/manifest.py`. Schema version `"1.0"`.

### When It Is Written

`InvestigationDispatcher._write_run_manifest()` is called unconditionally at the end of `_handle_completion` — for science and build modes, for converged/exhausted/negative results. Failure to write the manifest is logged but never blocks completion (the manifest is additive, not a gate).

### Source-of-Truth Map

| Manifest field | Source |
|---|---|
| `question`, `mode`, `rigor`, `provenance` | `Investigation` row in queue |
| `status`, `converged`, `reason` | `.swarm/convergence.json` |
| `evaluator` | `.swarm/eval-score.json` |
| `hypotheses` | `.swarm/belief-map.json` |
| `primary_claims` | Claim Ledger (preferred) → `.swarm/claim-evidence.json` (fallback) |
| `experiments` | Beads `FINDING` tasks |
| `pending_objections` | `ClaimLedger.objections` (pending/investigating/surfaced) |
| `artifacts` | Filesystem scan + finding `DATA_FILE` notes |
| `caveats` | Derived: convergence blockers + `ROBUST=no` + non-APPROVED stat review |
| `answer` | Derived: strongest-status claim (`replicated > locked > asserted > provisional`) |

### Rigor-Tiered Validation

`validate_manifest(manifest, rigor)` returns `ValidationResult(valid, missing, warnings)`. Tiers are strictly additive: `standard < adaptive < analytical < scientific < experimental`.

See [MANIFEST.md](MANIFEST.md) for the full schema, rigor table, sub-structure definitions, and public API reference.

### Relationship to §5 Convergence

Convergence is still the authoritative *signal* (written to `.swarm/convergence.json` and gated by `convergence-gate.sh`). The manifest is written **after** completion is decided; it does not participate in the convergence gate. The manifest's `status` and `converged` fields mirror `convergence.json`.


## 20. Citation Coverage — Paper-Track Manuscript Gate

Paper-track manuscripts (triggered by `/voronoi paper <codename>`) have a zero-tolerance citation-integrity gate that runs as the Scribe's verify-loop step 6 and again after every Refiner round.

### Purpose

Every reference in the compiled `paper.tex` must be **verifiable** against Semantic Scholar, and every verified candidate must be **integrated** (actually `\cite`d) in the body. This single gate catches the two biggest failure modes of LLM-written papers: hallucinated citations, and "we searched and found relevant work, but never actually cited it."

The gate enforces a ≥90% integration threshold and Levenshtein ≥70 fuzzy match policy.

### Module

`src/voronoi/science/citation_coverage.py` — standard library only (uses `difflib.SequenceMatcher` for Levenshtein-like fuzzy matching, no new runtime dependency).

### Public API

```python
DEFAULT_TITLE_THRESHOLD = 0.70      # Levenshtein-like similarity (0..1)
DEFAULT_COVERAGE_TARGET = 0.90      # Integration rate required to pass

@dataclass
class CoverageResult:
    integration_rate: float            # integrated / verified
    verified_count: int
    integrated_count: int
    unintegrated_keys: list[str]       # verified but not \cite'd
    orphan_cites: list[str]            # \cite'd but not verified (hallucinations)
    target: float
    @property
    def passes(self) -> bool           # rate >= target AND orphan_cites == []

def fuzzy_match_title(a: str, b: str, threshold: float = 0.70) -> bool
def extract_cite_keys(tex: str) -> set[str]   # strips comments + verbatim first
def check_coverage(ledger_path, paper_tex_path, *, target=0.90) -> CoverageResult
def write_coverage_audit(result, out_path) -> Path
```

### Comment & Verbatim Stripping

`extract_cite_keys()` strips LaTeX comment lines (unescaped `%` to end-of-line) and the content of `verbatim`, `lstlisting`, and `minted` environments before extracting `\cite` keys. This prevents commented-out or example citations from producing false orphan reports.

### Gate Semantics

The gate **fails** if either:
1. `integration_rate < 0.90` (more than 10% of verified candidates never cited), or
2. `orphan_cites` is non-empty (any `\cite{key}` without a matching ledger entry with `verified: true`).

Orphan cites are treated as hallucinations — zero tolerance, regardless of integration rate.

### Inputs

- `.swarm/manuscript/citation-ledger.json` — produced by the **Lit-Synthesizer** agent. Entries must carry `{bibtex_key, verified, title, paper_id, ...}`.
- `paper.tex` at workspace root — produced by **Scribe**.

### Output

- `.swarm/manuscript/coverage-audit.json` — persisted by `write_coverage_audit()` after every gate run. Read by the dual-rubric Evaluator to score the "citation integrity" axis of MS_QUALITY.

### Where Invoked

- **Scribe verify loop (step 6)** — first gate run; fails the compile iteration if coverage is below target or orphans exist.
- **Refiner — after every review round** — coverage is re-checked; if it regressed below target, the Refiner reverts the round (`git checkout paper.tex paper.pdf`).

### Related Invariant

See [INVARIANTS.md](INVARIANTS.md) — "Every `\cite{...}` in a compiled paper-track manuscript must resolve to a verified entry in `citation-ledger.json`."

---

## 21. Evidence-Gated Epoch Scaling

### Purpose

Prevents unbounded resource commitment before evidence exists. The system operates in **epochs** — dynamically-scoped batches of work where each epoch must produce evidence (belief-map moves) before the agent cap increases.

### EpochState Data Structure

```python
EPOCH_AGENT_CAP: dict[int, int] = {1: 2, 2: 4, 3: 6}

@dataclass
class EpochState:
    epoch: int = 1
    max_tranches: int = 2
    findings_this_epoch: int = 0
    belief_map_moves: int = 0
    tokens_this_epoch: int = 0
    epoch_started_at: str = ""
    history: list[dict] = field(default_factory=list)

    @property
    def learning_rate(self) -> float: ...   # findings per M tokens
    @property
    def has_evidence(self) -> bool: ...     # belief_map_moves > 0
```

### File Location

`.swarm/epoch-state.json` — read/written by dispatcher, read by orchestrator each OODA cycle.

### Functions

```python
def load_epoch_state(workspace: Path) -> EpochState
def save_epoch_state(workspace: Path, state: EpochState) -> None
def advance_epoch(state: EpochState, configured_max: int) -> EpochState
def compute_learning_rate_display(state: EpochState) -> str
```

### Epoch Advancement Rules

- Epoch auto-advances when `has_evidence` is True and `max_tranches < configured_max`
- Each epoch's findings/moves/tokens are archived into `history`
- Cap never exceeds `DispatcherConfig.max_agents`
- The orchestrator prompt instructs the LLM to respect `max_tranches` from the file

### Minimum Viable Experiment (MVE)

The orchestrator prompt mandates that in epoch 1, the FIRST dispatch must be a single concrete experiment that can complete in <30 minutes and produces one measurable outcome. This is a pilot study — it validates the experimental setup works before committing to the full plan.

---

## 22. Structured Failure Diagnosis

### Purpose

When an investigation stalls or fails, produces a structured machine-readable diagnosis that tells the continuation round exactly what failed and why — enabling targeted remediation instead of blind re-execution.

### Function

```python
def build_failure_diagnosis(workspace: Path) -> dict
def save_failure_diagnosis(workspace: Path, diagnosis: dict) -> None
```

### Output Schema

```json
{
  "met_criteria": ["SC1", "SC3"],
  "unmet_criteria": [
    {"id": "SC2", "diagnosis": "NOT_TESTED|TESTED_BUT_UNMET", "description": "...", "recommendation": "..."}
  ],
  "systemic_issues": ["Zero experiments ran — plan likely overscoped"],
  "epoch_history": [{"epoch": 1, "findings": 0, "belief_map_moves": 0}],
  "proposed_action": "Start with a single MVE...",
  "timestamp": "2026-01-01T00:00:00+00:00"
}
```

### Diagnosis Categories

| Category | Meaning |
|----------|---------|
| `NOT_TESTED` | No experiments ran that could have satisfied this criterion |
| `TESTED_BUT_UNMET` | Experiments ran but results didn't satisfy the criterion |

### When Written

- Auto-park (stall strike 3)
- `_handle_completion(failed=True)` — any failed investigation

### Consumed By

`build_warm_start_context()` reads `.swarm/failure-diagnosis.json` and injects it into the continuation prompt under a "Failure Diagnosis from Prior Round" heading.

---

## 23. Lab-Wide Knowledge Graph (Per-PI)

### Purpose

The Claim Ledger (§17) is scoped to a single *lineage* of investigations. The Lab-KG accumulates snapshots of ledger claims, dead ends, and known artifact-traps across **every** lineage a single scientist runs. Purpose: make investigation #100 structurally smarter than investigation #1.

**Scope is per-PI.** The store lives at `~/.voronoi/lab/kg/kg.json` (overridable via `VORONOI_LAB_KG_PATH`). Cross-lab sharing is explicit opt-in and out of scope for this section.

### Module

`src/voronoi/science/lab_kg.py` — `LabKG`, `LabEntry`, `DeadEnd`, `default_store_path`. Re-exported from `voronoi.science`.

### Safeguards Against Contamination

A naive "accumulate everything and trust it" store would rebuild the replication crisis. The KG therefore enforces:

1. **Provenance preservation.** Every entry carries the Claim Ledger provenance tag (`model_prior` / `retrieved_prior` / `run_evidence`). Callers that inject KG content into prompts MUST NOT elevate an entry's trust beyond what its provenance + status justify.
2. **Durability filter.** Only `locked` and `replicated` entries (`DURABLE_STATUSES`) are returned by `query()` by default. `provisional`/`asserted` are retained but require `include_non_durable=True` and MUST be presented to downstream agents as "prior attempts, unsettled", never as established facts.
3. **Replication-on-convergence.** When two independent lineages assert the *same* locked statement, the entry is automatically promoted to `replicated`. Single-run findings never harden into dogma through this path.
4. **Dissent as a first-class edge.** When a lineage challenges a claim that matches an existing entry, that lineage is appended to the entry's `dissent` list. Queries and the Lab Context Brief surface dissenting lineages alongside the claim.
5. **Half-life.** Every durable entry gets `half_life_due` (default 180 days). Entries older than `half_life_due` are returned with `stale_as_of_query=True`; callers SHOULD force re-examination rather than trust stale priors.
6. **Retirement propagation.** When any lineage retires a claim (PI-driven demotion), the KG entry's status flips to `retired` — no further durable use.

### Safeguards Against Groupthink

1. **KG is a second source, never the first.** Scout's `/research` against external literature still runs for every investigation. KG is consulted *after* and *in comparison with* external results.
2. **Adversarial framing on read.** `format_brief()` renders entries with the explicit preamble *"Treat every entry below as a hypothesis to challenge, not a fact to accept. Always run fresh external `/research` before trusting any lab-KG item."*
3. **Novelty Gate asymmetry.** (Orchestrator-level policy, not enforced by this module.) A KG hit that suggests `REDUNDANT` requires stronger evidence than a KG hit that suggests `NOVEL`. Default is "proceed until proven redundant".
4. **Scope by default.** Per-PI scope; cross-lab transfer is explicit `/voronoi kg export/import` (future).

### API

```python
class LabKG:
    @classmethod
    def load(cls, path: Path | None = None) -> "LabKG": ...
    def save(self) -> None: ...
    def upsert_from_ledger(self, lineage_id: str, ledger: ClaimLedger) -> list[LabEntry]: ...
    def record_dead_end(self, lineage_id: str, description: str, reason: str, category: str) -> DeadEnd: ...
    def query(self, topic: str, *, limit: int = 20, include_non_durable: bool = False) -> list[LabEntry]: ...
    def query_dead_ends(self, topic: str, *, limit: int = 20) -> list[DeadEnd]: ...
    def format_brief(self, topic: str, *, limit: int = 10, include_non_durable: bool = False) -> str: ...
```

`upsert_from_ledger` is idempotent: re-inserting an already-present statement updates in place and applies the replication / dissent / retirement rules above.

### Storage Schema

```json
{
  "schema_version": 1,
  "entries": [
    {
      "id": "L1",
      "statement": "...",
      "provenance": "run_evidence",
      "status": "replicated",
      "source_lineage": "lineage-alpha",
      "source_claim_id": "C7",
      "supporting_lineages": ["lineage-alpha", "lineage-beta"],
      "replicated_in": ["lineage-beta"],
      "dissent": [],
      "effect_summary": "+14.2pp (95% CI ...)",
      "artifact_paths": ["output/k4_depth.csv"],
      "first_recorded": "...",
      "last_updated": "...",
      "half_life_due": "..."
    }
  ],
  "dead_ends": [
    {
      "id": "DE1",
      "lineage": "lineage-7",
      "description": "StandardScaler applied per-batch before train/val split",
      "reason": "Caused 14pp spurious improvement; artifact of data leakage",
      "category": "artifact",
      "recorded": "..."
    }
  ]
}
```

### Wire-Up (Future Work)

This section defines the substrate. Three follow-ups remain:

- **Dispatcher**: on completion, call `LabKG.load().upsert_from_ledger(lineage_id, ledger)` after the Claim Ledger is synced.
- **Prompt builder**: write `.swarm/lab-context-brief.md` via `format_brief(question)` before orchestrator launch; Scout/Theorist prompts reference it.
- **Router**: `/voronoi kg query <topic>` for PI-driven exploration.

Each follow-up has its own spec section when implemented; this section is the substrate contract.

### Invariant

See `docs/INVARIANTS.md` INV-53 (KG provenance & durability).

