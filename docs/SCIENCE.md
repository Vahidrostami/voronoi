# Science Layer Specification

> Pre-registration, belief maps, convergence, paradigm stress, consistency, EVA, anti-fabrication, data integrity.

**TL;DR**: Gates activate by rigor: Standard (none) → Analytical (+statistician, eval) → Scientific (+pre-reg, methodologist, blinding) → Experimental (+replication). EVA catches experiments that run but don't test what they claim. Baseline-first is a hard gate. All raw data gets SHA-256. Organized as `src/voronoi/science/` subpackage.

## 1. Overview

The science layer (`src/voronoi/science/`) enforces the scientific rigor framework. It is split into focused submodules:

| Submodule | Responsibility |
|-----------|---------------|
| `_helpers.py` | Beads queries, consistency gate, paradigm stress, heartbeat stall, finding interpretation, claim-evidence I/O, success criteria I/O |
| `convergence.py` | Belief map, orchestrator checkpoint, convergence detection |
| `fabrication.py` | Anti-fabrication verification, simulation bypass detection |
| `gates.py` | Dispatch/merge gates, pre-registration, invariants, calibration, replication |

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
| Final evaluation (CCSA) | — | YES | YES | YES |
| Methodologist design review | — | YES (advisory) | YES (mandatory) | YES (mandatory) |
| Pre-registration | — | YES | YES | YES |
| Pre-reg compliance audit | — | YES | YES | YES |
| Power analysis | — | YES | YES | YES |
| Partial blinding for Critic | — | YES | YES | YES |
| Adversarial review loop | — | YES | YES | YES |
| Plan review | YES (Critic) | YES (Critic + Theorist) | YES (Critic + Theorist) | YES (Critic + Theorist + Methodologist) |
| Replication | — | — | — | YES |

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

Tracks hypothesis probabilities across OODA cycles. Drives information-gain prioritization — the orchestrator pursues hypotheses with highest expected information gain.

### Data Structures

```python
@dataclass
class Hypothesis:
    id: str
    name: str
    prior: float           # Initial probability [0, 1]
    posterior: float        # Updated probability [0, 1]
    status: str            # active | confirmed | rejected | merged
    evidence: list[str]    # Finding IDs supporting/refuting
    testability: float     # How easily tested [0, 1]
    impact: float          # How important if true [0, 1]

    @property
    def uncertainty(self) -> float: ...        # Entropy measure
    @property
    def information_gain(self) -> float: ...   # Expected info gain
```

```python
class BeliefMap:
    def add_hypothesis(self, h: Hypothesis) -> None: ...
    def update_hypothesis(self, id: str, posterior: float, status: str) -> None: ...
    def get_priority_order(self) -> list[Hypothesis]: ...  # Sorted by information_gain DESC
    def all_resolved(self) -> bool: ...                     # All confirmed or rejected
    def summary(self) -> str: ...                           # Human-readable summary
```

### File Location

`.swarm/belief-map.json` — read/written by orchestrator at each OODA cycle.

**Schema contract**: `hypotheses` MUST be a JSON array of objects (not an object map keyed by ID). Both the Python loader and the shell convergence gate validate this on load. Non-conforming data (e.g., object maps) is automatically migrated to the array format.

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

The dispatcher detects pending gates and sends a Telegram message. The human replies `/approve <id>` or `/revise <id> <feedback>`. The orchestrator polls the gate file and resumes when approved or revises when feedback is given.

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

### Escalation Path

When the sentinel finds a critical failure:
1. Writes `.swarm/sentinel-audit.json` (persisted for orchestrator to read)
2. Writes `.swarm/dispatcher-directive.json` with `level: sentinel_violation` (forces orchestrator to act)
3. Returns `design_invalid` event (triggers Telegram alert to PI)
4. `_is_complete()` returns False while DESIGN_INVALID exists (hard gate — cannot be bypassed)

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
