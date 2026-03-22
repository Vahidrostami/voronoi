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

| Gate | Standard | Analytical | Scientific | Experimental |
|------|:--------:|:----------:|:----------:|:------------:|
| Code review (Critic inline) | YES | YES | YES | YES |
| Statistician review | — | YES | YES | YES |
| Finding interpretation | — | YES | YES | YES |
| Claim-evidence registry | — | YES | YES | YES |
| Final evaluation (CCSA) | — | YES | YES | YES |
| Methodologist design review | — | — | YES (advisory) | YES (mandatory) |
| Pre-registration | — | — | YES | YES |
| Pre-reg compliance audit | — | — | YES | YES |
| Power analysis | — | — | YES | YES |
| Partial blinding for Critic | — | — | YES | YES |
| Adversarial review loop | — | — | YES | YES |
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
    status: str           # converged | not_converged | exhausted
    reason: str           # Human-readable explanation
    score: float          # 0.0 – 1.0 convergence score
    blockers: list[str]   # What's preventing convergence
```

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

## 10. Anti-Fabrication

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

## 11. Data Integrity

### Functions

```python
def compute_data_hash(filepath: Path) -> str        # SHA-256 hex digest
def verify_data_hash(filepath: Path, expected_hash: str) -> bool
```

All raw data files MUST be hashed immediately after collection. Hash stored in finding metadata.

---

## 12. Lab Notebook

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

## 13. Experiment Ledger

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

## 14. Claim-Evidence Traceability

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

## 15. Anti-Simulation Enforcement

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
