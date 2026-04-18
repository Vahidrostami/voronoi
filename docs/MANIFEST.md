# Run Manifest — Structured Deliverable

> The canonical, machine-readable summary of a completed Voronoi run.
> Derived from `.swarm/` state at completion; additive (never replaces
> existing files); consumed today by the Claim Ledger, external graders,
> and `jq`. Rendering the PDF *from* the manifest is planned (see §8).

---

## 1. Purpose

Every Voronoi run already produces structured reasoning — claims, experiments,
hypotheses, evaluator dimensions, provenance — but these live in half a dozen
`.swarm/` files with different shapes. The **Run Manifest** consolidates them
into a single JSON document at `.swarm/run-manifest.json` so that:

- **Scientists** can `jq '.primary_claims[0].effect_size'` without opening a PDF.
- **The paper** can be rendered *from* the manifest (future work — see §8).
- **External graders** (ScienceAgentBench, DiscoveryBench, reviewers, CI) can
  score a Voronoi run without parsing prose.
- **Multi-run diffs** become tractable: `diff manifest-a manifest-b`.

The manifest is a **derived artifact** — it never contradicts its sources.
If `.swarm/convergence.json` says `converged: true`, the manifest says
`converged: true`. The source files remain the authority; the manifest
just collates them in one place.

---

## 2. Canonical Path

```
<workspace>/.swarm/run-manifest.json
```

Written at **every** completion (success, negative result, exhaustion) by
`InvestigationDispatcher._write_run_manifest()` on the server path, and by
`cmd_demo()` after the orchestrator subprocess exits on the CLI demo path
(via `_write_demo_manifest()`).  Build-mode and science-mode runs both
produce a manifest — it is mode-agnostic.

Schema version: `"1.0"` (current).

---

## 3. Top-Level Schema

```python
@dataclass
class RunManifest:
    schema_version: str = "1.0"

    # --- Identity & framing ---
    question: str                    # original NL prompt
    answer: str                      # single-sentence scientific answer
    mode: str                        # discover | prove | build
    rigor: str                       # standard | adaptive | analytical | scientific | experimental

    # --- Run status ---
    status: str                      # converged | exhausted | diminishing_returns |
                                     # negative_result | failed | partial | unknown
    converged: bool
    reason: str

    # --- Scientific content ---
    primary_claims:         list[PrimaryClaim]
    hypotheses:             list[HypothesisOutcome]
    experiments:            list[ExperimentRecord]
    artifacts:              list[ManifestArtifact]
    caveats:                list[str]
    reviewer_defense:       list[ReviewerObjection]
    pending_objections:     list[dict]
    continuation_proposals: list[dict]

    # --- Quality & meta ---
    evaluator:    EvaluatorSummary
    provenance:   ProvenanceInfo
    cost:         CostReport
    generated_at: str                # ISO-8601 UTC, set on save
```

See `src/voronoi/science/manifest.py` for the authoritative dataclass
definitions.

---

## 4. Sub-Structures

### `PrimaryClaim`

One structured assertion from the run. Mirrors `Claim` in the Claim Ledger
but adds grader-friendly fields (`variables`, `direction`, `relation`).

```python
id: str                       # "C1" — aligns with Claim.id when from ledger
statement: str                # natural-language claim
variables: dict               # {"independent": [...], "dependent": [...], "moderators": [...]}
relation: str                 # "X increases Y" / "no effect"
direction: str                # confirmed | refuted_reversed | inconclusive | not_tested
effect_size: str              # "d=0.82"
confidence_interval: str      # "[0.61, 1.03]"
p_value: str
sample_summary: str           # "N=150 across 3 runs"
status: str                   # provisional | asserted | locked | replicated | challenged | retired
provenance: str               # model_prior | retrieved_prior | run_evidence
supporting_findings: list[str]    # ["bd-5", "bd-22"]
supporting_artifacts: list[str]   # relative paths referencing manifest.artifacts
caveats: list[str]
```

### `HypothesisOutcome`

One entry from the belief map, distilled for external readers.

```python
id: str                      # "H1"
statement: str
expected_direction: str      # from pre-registration if present
observed_direction: str      # confirmed | refuted_reversed | inconclusive
verdict: str                 # from tribunal if present
confidence: str              # unknown | hunch | supported | strong | resolved
supporting_findings: list[str]
```

### `ExperimentRecord`

One finding flattened for external consumption.

```python
id: str                      # beads task id
method: str                  # cleaned finding title
dataset: str
dataset_sha256: str
script: str
metric_name: str
baseline_value: str
treatment_value: str
effect_size: str
ci: str
p_value: str
n: str
stat_test: str
valence: str                 # positive | negative | inconclusive
status: str
```

### `ManifestArtifact`

A workspace file relevant to the run.

```python
path: str                    # relative to workspace root
kind: str                    # paper | code | data | figure | model | submission | other
sha256: str | None           # SHA-256 (skipped for files >= 50 MB)
bytes: int | None
description: str
```

Discovered automatically — canonical candidates (`paper.pdf`, `paper.tex`,
`submission.csv`, `pred.py`, figures under `output/figures/`), plus any
`DATA_FILE` referenced in finding notes.

### `ProvenanceInfo`

```python
investigation_id: int | None
lineage_id: int | None
cycle_number: int
parent_id: int | None
codename: str
mode: str
rigor: str
git_commit: str              # workspace HEAD at completion
git_tag: str
workspace_path: str
started_at: str              # ISO-8601 UTC
completed_at: str
```

### `EvaluatorSummary`

Verbatim copy of `.swarm/eval-score.json` fields.

```python
score: float
rounds: int
dimensions: dict             # {completeness: {score, note}, coherence: ..., ...}
remediations: list[str]
```

### `ReviewerObjection`

Pattern 5 from the scientist-UX skill: pre-answer anticipated objections.

```python
objection: str
response: str                # "(unanswered — pending)" if derived from a pending objection
```

### `CostReport`

```python
wall_clock_seconds: float
total_tokens: int
total_usd: float
```

Currently populated to zero by default — wiring to real cost tracking is
tracked separately.

---

## 5. Rigor-Tiered Validation

`validate(manifest, rigor)` returns `ValidationResult(valid, missing, warnings)`.
Tiers are **strictly additive** — higher tiers require everything lower tiers
require plus more.

| Tier | Required | Additional warnings |
|---|---|---|
| `standard` | `question`, `status` | — |
| `adaptive` | + `answer`, ≥1 `primary_claim` | — |
| `analytical` | + ≥1 `experiment` | `evaluator.score > 0`, `caveats` non-empty |
| `scientific` | + ≥1 `hypothesis` | `reviewer_defense` non-empty |
| `experimental` | (same required as scientific) | every claim has `effect_size` + `confidence_interval` |

Unknown rigors are treated as `adaptive`.

---

## 6. Source-of-Truth Map

The manifest never invents data. Every field traces to a source:

| Manifest field | Source |
|---|---|
| `question`, `mode`, `rigor` | `Investigation` row in queue |
| `status`, `converged`, `reason` | `.swarm/convergence.json` |
| `evaluator.*` | `.swarm/eval-score.json` |
| `hypotheses` | `.swarm/belief-map.json` |
| `primary_claims` | Claim Ledger (preferred) → `.swarm/claim-evidence.json` (fallback) |
| `experiments` | Beads `FINDING` tasks (via `gateway.evidence.get_findings`) |
| `pending_objections` | `ClaimLedger.objections` with status in `{pending, investigating, surfaced}` |
| `continuation_proposals` | `.swarm/continuation-proposals.json` |
| `artifacts` | Filesystem scan + finding `DATA_FILE` notes |
| `caveats` | Derived: convergence blockers + `ROBUST=no` findings + non-APPROVED stat review |
| `answer` | Derived: strongest-status claim, ranked `replicated > locked > asserted > provisional` |
| `provenance.git_commit` | `.git/HEAD` (best-effort) |

---

## 7. Integration With Dispatcher

```python
# src/voronoi/server/dispatcher.py :: _handle_completion
if is_science:
    self._transition_to_review(run)
else:
    self.queue.complete(run.investigation_id)

self._write_run_manifest(run)    # ← always, best-effort, non-fatal
```

`_write_run_manifest` loads the ledger (if `lineage_id` is set) and calls
`build_manifest_from_workspace()`. Failures are logged, never raised: the
manifest is an *additional* artifact, not a completion gate.

---

## 8. Non-Goals (Current Release)

The manifest is intentionally **derived, not primary**, in this release:

- Synthesizer still writes `.swarm/deliverable.md` and
  `.swarm/claim-evidence.json` as before.
- Scribe still renders the PDF from prose + `claim-evidence.json`.
- The Claim Ledger remains the durable cross-run state; manifests are
  per-run snapshots.

A future iteration may invert this — Synthesizer emits the manifest first,
then renders prose / LaTeX / deliverable.md *from* it — but that requires
updating agent role files and the convergence-gate script and is tracked
separately.

---

## 9. Public API

```python
from voronoi.science import (
    RunManifest,
    build_manifest_from_workspace,
    save_manifest,
    load_manifest,
    validate_manifest,
    MANIFEST_FILENAME,         # "run-manifest.json"
    MANIFEST_SCHEMA_VERSION,   # "1.0"
)
```

Module: `src/voronoi/science/manifest.py`.
Tests: `tests/test_manifest.py`.
