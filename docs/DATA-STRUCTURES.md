# Data Structures Specification

> All dataclasses, enums, database schemas, file formats, and JSON schemas used across the project.

**TL;DR**: Key types: `ClassifiedIntent` (intent.py), `Investigation` (queue.py), `PreRegistration`/`Hypothesis`/`ConvergenceResult` (science/gates.py, science/convergence.py), `DispatcherConfig`/`RunningInvestigation` (dispatcher.py). Two SQLite DBs: `queue.db` (investigations) + `memory.db` (chat). `.swarm/` files: belief-map.json, eval-score.json, convergence.json, experiments.tsv, verify-log-*.jsonl, novelty-gate.json, scout-brief.md.

## 1. Enums

### WorkflowMode (`gateway/intent.py`)

```python
class WorkflowMode(Enum):
    DISCOVER = "discover"     # Open question — adaptive rigor, creative exploration
    PROVE = "prove"           # Specific hypothesis — full science gates
    STATUS = "status"         # Meta: query swarm state
    RECALL = "recall"         # Meta: search knowledge store
    GUIDE = "guide"           # Meta: operator guidance
    ASK = "ask"               # Meta: question about a running investigation
    DELIBERATE = "deliberate" # Meta: multi-turn Socratic reasoning about results
```

### RigorLevel (`gateway/intent.py`)

```python
class RigorLevel(Enum):
    ADAPTIVE = "adaptive"           # DISCOVER mode — starts analytical, escalates dynamically
    SCIENTIFIC = "scientific"       # PROVE mode — full gates from the start
    EXPERIMENTAL = "experimental"   # PROVE mode + replication
```

---

## 2. Core Dataclasses

### ClassifiedIntent (`gateway/intent.py`)

```python
@dataclass(frozen=True)
class ClassifiedIntent:
    mode: WorkflowMode
    rigor: RigorLevel
    confidence: float        # 0.0 – 1.0
    summary: str             # Brief description of classified intent
    original_text: str       # Unmodified user input

    @property
    def is_science(self) -> bool: ...   # DISCOVER | PROVE
    @property
    def is_meta(self) -> bool: ...      # STATUS | RECALL | GUIDE | ASK | DELIBERATE
```

### ClassifiedPhase (`gateway/intent.py`)

```python
@dataclass(frozen=True)
class ClassifiedPhase:
    mode: WorkflowMode
    rigor: RigorLevel
    description: str
    order: int
```

### Investigation (`server/queue.py`)

```python
@dataclass
class Investigation:
    id: int                       # Auto-assigned
    chat_id: str
    status: str                   # queued | running | paused | review | complete | failed | cancelled
    investigation_type: str       # repo | lab
    repo: str | None
    question: str
    slug: str
    mode: str                     # discover | prove
    rigor: str                    # adaptive | scientific | experimental
    codename: str
    workspace_path: str | None
    sandbox_id: str | None
    github_url: str | None
    parent_id: int | None
    demo_source: str | None
    lineage_id: int | None        # Root investigation ID for claim ledger scoping
    cycle_number: int             # Iteration round within a lineage (1, 2, 3...)
    pi_feedback: str              # PI feedback for this continuation round (empty for root)
    created_at: float
    started_at: float | None
    completed_at: float | None
    error: str | None
```

### RepoRef (`server/repo_url.py`)

```python
@dataclass
class RepoRef:
    owner: str
    name: str

    @property
    def full_name(self) -> str: ...   # "owner/name"
    @property
    def clone_url(self) -> str: ...   # "https://github.com/owner/name.git"
    @property
    def slug(self) -> str: ...        # "owner--name"
```

---

## 3. Gateway Dataclasses

### Message (`gateway/memory.py`)

```python
@dataclass
class Message:
    chat_id: str
    role: str               # "user" | "assistant" | "system"
    content: str
    timestamp: float
    metadata: dict
    message_id: str | None = None
```

### ConversationContext (`gateway/memory.py`)

```python
@dataclass
class ConversationContext:
    chat_id: str
    messages: list[Message]
    summary: str | None
    active_workflow_id: str | None
```

### Finding (`gateway/knowledge.py`)

```python
@dataclass
class Finding:
    id: str
    title: str
    status: str
    priority: int
    notes: list[str]
    # Extracted fields (parsed from notes):
    effect_size: str | None
    confidence_interval: str | None
    sample_size: str | None
    stat_test: str | None
    valence: str | None         # positive | negative | inconclusive
    confidence: str | None
    data_file: str | None
    robust: str | None          # yes | no
```

### Paper (`gateway/literature.py`)

```python
@dataclass
class Paper:
    paper_id: str
    title: str
    abstract: str | None
    year: int | None
    citation_count: int
    authors: list[str]
    url: str
```

### FixSpec (`gateway/handoff.py`)

```python
@dataclass
class FixSpec:
    title: str
    finding_id: str
    root_cause: str
    fix_description: str
    expected_improvement: str
    files_to_change: list[str]
    repo: str | None = None
    priority: int = 2
    validation_criteria: str = ""
```

---

## 4. Server Dataclasses

### DispatcherConfig (`server/dispatcher.py`)

```python
@dataclass
class DispatcherConfig:
    base_dir: Path              # ~/.voronoi
    max_concurrent: int         # 2
    max_agents: int             # 4
    agent_command: str          # "copilot"
    agent_flags: str            # "--allow-all"
    orchestrator_model: str     # ""
    worker_model: str           # ""
    progress_interval: int      # 30 (seconds)
    timeout_hours: int          # 8
    max_retries: int            # 2
    stall_minutes: int          # 45
    park_timeout_hours: int     # 4 (force-wake parked orchestrator after this)
```

### RunningInvestigation (`server/dispatcher.py`)

```python
@dataclass
class RunningInvestigation:
    investigation_id: int
    workspace_path: str
    tmux_session: str
    question: str
    mode: str
    codename: str
    chat_id: str
    rigor: str
    started_at: float
    last_update_at: float
    task_snapshot: dict
    notified_findings: set
    notified_paradigm_stress: bool
    phase: str                  # starting | scouting | planning | investigating | reviewing | synthesizing | converging | complete
    improvement_rounds: int
    eval_score: float
    retry_count: int
    stall_warned: bool
    notified_design_invalid: set
    last_event_ts: float          # For event log polling
    status_message_id: int | None # Telegram message ID for edit-in-place
```

### WorkspaceInfo (`server/workspace.py`)

```python
@dataclass
class WorkspaceInfo:
    investigation_id: int
    path: str
    workspace_type: str         # "repo" | "lab"
    repo: str | None
    slug: str
    created_at: float
    sandbox_id: str | None
```

### SandboxConfig (`server/sandbox.py`)

```python
@dataclass
class SandboxConfig:
    enabled: bool
    image: str
    cpus: float
    memory: str                 # e.g., "4g"
    timeout_hours: int
    network: str                # e.g., "none"
    fallback_to_host: bool
```

### SandboxInfo (`server/sandbox.py`)

```python
@dataclass
class SandboxInfo:
    container_id: str
    container_name: str
    workspace_path: str
    status: str
```

---

## 5. Science Dataclasses

### PreRegistration (`science/gates.py`)

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
    power_analysis: str
    sensitivity_plan: str
    approved_by: str
    deviations: list[str]
    expected_direction: str  # e.g. "higher_is_better", "L4_A < L4_D"
```

### Hypothesis (`science/convergence.py`)

```python
@dataclass
class Hypothesis:
    id: str
    name: str
    prior: float
    posterior: float
    status: str                 # untested | testing | confirmed | refuted | merged
    evidence: list[str]
    testability: float
    impact: float
    confidence: str             # unknown | hunch | supported | strong | resolved
    rationale: str              # Evidence-linked reasoning for current confidence
    next_test: str              # What would change confidence
```

**Hypothesis status values**: `untested | testing | confirmed | refuted | refuted_reversed | merged`

`refuted_reversed` indicates a statistically significant result in the **opposite** direction of the prediction. This triggers the Judgment Tribunal.

### Interpretation Layer Dataclasses (`science/interpretation.py`)

```python
class DirectionMatch:
    CONFIRMED = "confirmed"           # Significant + correct direction
    REFUTED_REVERSED = "refuted_reversed"  # Significant + opposite direction
    INCONCLUSIVE = "inconclusive"      # Not significant

class TrivialityClass:
    NOVEL = "novel"        # Outcome genuinely uncertain — full investigation
    EXPECTED = "expected"  # Outcome likely but confirmation useful — sanity check
    TRIVIAL = "trivial"    # Outcome obvious — skip or reframe

class TribunalVerdict:
    EXPLAINED = "explained"                    # Coherent explanation found
    ANOMALY_UNRESOLVED = "anomaly_unresolved"  # No satisfying explanation — BLOCKS convergence
    ARTIFACT = "artifact"                      # Design flaw — DESIGN_INVALID
    TRIVIAL = "trivial"                        # Result is expected/obvious
```

```python
@dataclass
class InterpretationRequest:
    finding_id: str
    trigger: str               # refuted_reversed | contradiction | surprising | pre_convergence
    hypothesis_id: str
    expected: str
    observed: str
    causal_edges_violated: list[str]
    timestamp: str

@dataclass
class TribunalResult:
    finding_id: str
    verdict: str               # TribunalVerdict constant
    explanations: list[Explanation]
    recommended_action: str
    trivial_to_resolve: bool
    tribunal_agents: list[str]
    timestamp: str

@dataclass
class Explanation:
    id: str                    # E1, E2, etc.
    theory: str
    test: str                  # Minimal experiment to test it
    effort: str                # trivial | moderate | substantial
    tested: bool
    test_result: str

@dataclass
class ContinuationProposal:
    id: str
    target_claim: str
    description: str
    rationale: str
    experiment_type: str       # targeted | replication | exploration
    information_gain: float    # 0.0–1.0
    effort: str                # trivial | moderate | substantial
```

### ConvergenceResult (`science/convergence.py`)

```python
@dataclass
class ConvergenceResult:
    converged: bool
    status: str                 # converged | not_converged | exhausted
    reason: str
    score: float
    blockers: list[str]
```

### ParadigmStressResult (`science/_helpers.py`)

```python
@dataclass
class ParadigmStressResult:
    stressed: bool
    contradiction_count: int
    contradicting_findings: list[str]
    message: str
```

### Claim (`science/claims.py`)

```python
@dataclass
class Claim:
    id: str                       # "C1", "C2", ...
    statement: str                # Paper-level assertion
    provenance: str               # model_prior | retrieved_prior | run_evidence
    status: str                   # provisional | asserted | locked | challenged | replicated | retired
    supporting_findings: list[str]  # Beads finding IDs
    source_cycle: int             # Which run produced this
    effect_summary: str | None    # e.g. "d=0.8, p=0.003"
    sample_summary: str | None    # e.g. "N=200 across 3 experiments"
    literature_refs: list[str]
    model_basis: str | None
    artifacts: list[ClaimArtifact]
    challenges: list[Objection]
    first_asserted: str           # ISO timestamp
    last_updated: str
```

### ClaimArtifact (`science/claims.py`)

```python
@dataclass
class ClaimArtifact:
    path: str                     # Relative workspace path
    artifact_type: str            # data | code | result | figure | model
    sha256: str | None
    git_tag: str | None
    description: str
```

### Objection (`science/claims.py`)

```python
@dataclass
class Objection:
    id: str                       # "O1", "O2", ...
    target_claim: str             # Claim ID
    concern: str
    objection_type: str           # confound | power | methodology | interpretation | scope | other
    raised_by: str                # PI | self_critique | critic_agent
    status: str                   # pending | investigating | resolved | dismissed | surfaced
    resolution: str | None
    resolution_cycle: int | None
    timestamp: str
```

### ClaimLedger (`science/claims.py`)

```python
class ClaimLedger:
    claims: list[Claim]
    objections: list[Objection]
    # Methods: add_claim, lock_claim, challenge_claim, retire_claim,
    #          add_objection, resolve_objection, get_locked, get_challenged,
    #          get_pending_objections, get_immutable_paths, format_for_prompt,
    #          format_for_review, summary
```

**Storage**: `~/.voronoi/ledgers/<lineage_id>/claim-ledger.json`

### ConsistencyConflict (`science/_helpers.py`)

```python
@dataclass
class ConsistencyConflict:
    finding_a: str
    finding_b: str
    conflict_type: str          # direction | magnitude | interpretation
    description: str
```

### FabricationFlag (`science/fabrication.py`)

```python
@dataclass
class FabricationFlag:
    severity: str               # critical | warning | info
    category: str               # missing_data | hash_mismatch | missing_script | suspicious_pattern
    message: str
    finding_id: str
```

### AntiFabricationResult (`science/fabrication.py`)

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

---

## 6. Database Schemas

### Investigation Queue (`~/.voronoi/queue.db`)

```sql
CREATE TABLE investigations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN ('queued','running','paused','review','complete','failed','cancelled')),
    investigation_type TEXT NOT NULL DEFAULT 'lab',
    repo TEXT,
    question TEXT NOT NULL,
    slug TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'discover',
    rigor TEXT NOT NULL DEFAULT 'scientific',
    codename TEXT NOT NULL DEFAULT '',
    workspace_path TEXT,
    sandbox_id TEXT,
    github_url TEXT,
    parent_id INTEGER,
    demo_source TEXT,
    lineage_id INTEGER,            -- Root investigation ID for claim ledger scoping
    cycle_number INTEGER DEFAULT 1, -- Iteration round within a lineage
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    error TEXT
);

CREATE INDEX idx_inv_status ON investigations(status);
CREATE INDEX idx_inv_chat ON investigations(chat_id);
```

### Conversation Memory (`memory.db` per chat)

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL,
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_msg_chat_ts ON messages(chat_id, timestamp DESC);

CREATE TABLE conversation_state (
    chat_id TEXT PRIMARY KEY,
    summary TEXT,
    active_workflow_id TEXT,
    last_activity REAL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

## 7. File Formats

### `.swarm/belief-map.json`

```json
{
  "hypotheses": [
    {
      "id": "H1",
      "name": "Encoding enables cross-lever discovery",
      "prior": 0.5,
      "posterior": 0.82,
      "status": "confirmed",
      "evidence": ["bd-18", "bd-22"],
      "testability": 0.9,
      "impact": 0.95,
      "confidence": "strong",
      "rationale": "bd-18 showed 2.3x improvement in cross-lever recall; bd-22 replicated with different encoder architecture",
      "next_test": "Test on out-of-distribution domains to check generalization"
    }
  ]
}
```

### `.swarm/eval-score.json`

```json
{
  "score": 0.84,
  "rounds": 1,
  "dimensions": {
    "completeness": {"score": 0.85, "note": "Minor gap in sensitivity analysis"},
    "coherence": {"score": 0.90, "note": "Good internal consistency"},
    "strength": {"score": 0.78, "note": "Finding bd-43 sample size marginal"},
    "actionability": {"score": 0.82, "note": "Concrete parameter ranges provided"}
  },
  "remediations": [
    "Run sensitivity analysis varying K from 0.1 to 1.0",
    "Increase sample size for finding bd-43"
  ]
}
```

### `.swarm/convergence.json`

```json
{
  "converged": true,
  "status": "converged",
  "reason": "All hypotheses resolved, eval score 0.84",
  "score": 0.84,
  "blockers": []
}
```

### `.swarm/claim-evidence.json`

```json
[
  {
    "claim": "Structured encoding enables discovery of cross-lever effects",
    "finding_ids": ["bd-18", "bd-22"],
    "hypothesis_ids": ["H1"],
    "strength": "robust",
    "interpretation": "Large effect (d=1.47) with narrow CI"
  }
]
```

### `.swarm/success-criteria.json`

```json
{
  "metric_name": "accuracy_retention_pct",
  "direction": "higher_is_better",
  "baseline_task": "bd-17",
  "baseline_value": 45.2,
  "acceptance": {
    "min_effect_size": 0.5,
    "max_p_value": 0.05
  }
}
```

### `.swarm/experiments.tsv`

```
timestamp	task_id	branch	metric_name	metric_value	status	description
2026-03-11T08:15:00Z	bd-17	baseline	accuracy_pct	45.2	keep	Baseline
```

### `.swarm/lab-notebook.json`

```json
[
  {
    "cycle": 1,
    "phase": "observe",
    "verdict": "Baseline established at 45.2%",
    "metrics": {"accuracy": 45.2},
    "failures": [],
    "next_steps": ["Launch EWC and Replay agents"],
    "timestamp": "2026-03-11T08:15:00Z"
  }
]
```

### `.swarm/verify-log-<task-id>.jsonl`

```jsonl
{"iteration": 1, "status": "fail", "error_type": "test_failure", "summary": "3/12 failed", "timestamp": "..."}
{"iteration": 2, "status": "pass", "summary": "all pass", "timestamp": "..."}
```

### `.swarm/events.jsonl`

Structured event log for investigation observability. Append-only JSONL.

```jsonl
{"ts":1710500000,"agent":"investigator","task_id":"bd-42","event":"tool_call","status":"pass","detail":"pytest: 12 passed","tokens_used":1240}
{"ts":1710500010,"agent":"investigator","task_id":"bd-42","event":"finding_committed","status":"ok","detail":"bd-43: effect d=0.82","tokens_used":0}
{"ts":1710500020,"agent":"worker","task_id":"bd-10","event":"test_run","status":"fail","detail":"attempt 2: AssertionError","tokens_used":890}
{"ts":1710500030,"agent":"worker","task_id":"bd-10","event":"verify_step","status":"pass","detail":"produces_check","tokens_used":0}
```

Event types: `tool_call`, `finding_committed`, `test_run`, `verify_step`, `cycle_start`, `cycle_end`.

### `.swarm/human-gate.json`

Human approval gate for Scientific+ rigor investigations.

```json
{
  "gate": "pre-registration",
  "status": "pending",
  "summary": "Hypothesis: Encoding enables cross-lever discovery. Method: 2x2 factorial. N=100/cell. Ready to run experiments."
}
```

Status values: `pending` → `notified` (dispatcher sent Telegram) → `approved` | `revision_requested`.
When `revision_requested`, includes a `feedback` field with human-written feedback.

Gate types: `pre-registration`, `convergence`, `novelty`.

The `novelty` gate is written by the orchestrator when the Scout's novelty assessment is REDUNDANT:
```json
{
  "gate": "novelty",
  "status": "pending",
  "summary": "Scout found published work covering this ground.",
  "blocking_paper": "[title, URL]",
  "suggested_pivot": "[how to differentiate]"
}
```
Human response options: `approved` (proceed as replication/extension), `pivot` (adjust question), `abort` (end investigation).

### `.swarm/novelty-gate.json`

Written by the Scout after Problem Positioning (Phase 0). Records the novelty assessment for all three states.

**NOVEL:**
```json
{
  "status": "clear", "assessment": "novel",
  "gap_statement": "No published work maps structural complexity × model capability × encoding format",
  "closest_paper": "Smith et al. 2025, Structured Prompting for LLMs",
  "differentiation": "We use deterministic evaluation over known causal DAGs"
}
```

**INCREMENTAL:**
```json
{
  "status": "clear", "assessment": "incremental",
  "closest_paper": "Smith et al. 2025",
  "overlap": "Same encoding technique",
  "differentiation": "Different evaluation methodology",
  "framing_constraint": "Frame as extension of Smith et al., not independent discovery"
}
```

**REDUNDANT:**
```json
{
  "status": "blocked", "assessment": "redundant",
  "blocking_paper": "Smith et al. 2025",
  "overlap": "Same methodology and comparable results",
  "suggested_pivot": "Test on different model families"
}
```

### `.swarm/scout-brief.md`

Scout's knowledge brief including Problem Positioning section (field context, current frontier with citations, gap statement, closest prior work deep comparison, novelty assessment), known results, prior approaches, suggested hypotheses, and SOTA methodology.

---

## 8. Configuration Files

### `~/.voronoi/config.json`

```json
{
  "server": {
    "max_concurrent": 2,
    "max_agents_per_investigation": 4,
    "agent_command": "copilot",
    "agent_flags": "--allow-all",
    "orchestrator_model": "",
    "worker_model": "",
    "workspace_retention_days": 30
  },
  "github": {
    "lab_org": "voronoi-lab",
    "visibility": "private",
    "auto_publish": false
  },
  "sandbox": {
    "enabled": false,
    "image": "voronoi-python:latest",
    "cpus": 2.0,
    "memory": "4g",
    "timeout_hours": 8,
    "network": "none",
    "fallback_to_host": true
  }
}
```

### `.swarm-config.json` (per project)

```json
{
  "project_name": "My Project",
  "project_dir": "/path/to/project",
  "swarm_dir": ".swarm",
  "bridge_enabled": false,
  "agent_command": "copilot",
  "orchestrator_model": "",
  "worker_model": "",
  "effort": "high",
  "role_permissions": {
    "scout": "--allow-all --deny-tool=write",
    "review_critic": "--allow-all --deny-tool=write",
    "review_stats": "--allow-all --deny-tool=write",
    "review_method": "--allow-all --deny-tool=write"
  }
}
```

| Field | Purpose |
|-------|---------|
| `effort` | Copilot CLI `--effort` level, mapped from rigor by the dispatcher |
| `role_permissions` | Per-role `--deny-tool`/`--allow-tool` overrides. Read-only roles get `--deny-tool=write` |

### `.github/mcp-config.json` (per workspace)

Written by `voronoi init` and dispatcher workspace provisioning. Copilot CLI auto-discovers MCP servers from this file.

```json
{
  "mcpServers": {
    "voronoi": {
      "command": "/absolute/path/to/python",
      "args": ["-m", "voronoi.mcp"],
      "env": {"VORONOI_WORKSPACE": "."}
    }
  }
}
```

`command` is the absolute interpreter path for the Python environment that launched Voronoi. This avoids MCP sidecars starting under a different interpreter that cannot import `voronoi`.

---

## 9. Beads Note Conventions

Structured metadata stored in Beads task notes:

Structured note writers MUST upsert only the fields they own and preserve unrelated lines already present in the note blob.

### Artifact Contracts

```
PRODUCES: src/encoder.py, output/results.json
REQUIRES: data/raw/transactions.csv
GATE: output/validation_report.json
```

### Finding Metadata

```
TYPE: finding
VALENCE: positive | negative | inconclusive
CONFIDENCE: 0.85
EFFECT_SIZE: d=1.47
CI_95: [1.12, 1.83]
N: 15
STAT_TEST: Welch t-test
P: <0.001
DATA_FILE: data/raw/results.csv
DATA_HASH: sha256:e7b3f...
SENSITIVITY: lambda=[100,400,1000], all significant
ROBUST: yes
REPLICATED: no
INTERPRETATION: Encoding enables 82% better detection
PRACTICAL_SIGNIFICANCE: large
SUPPORTS_HYPOTHESIS: H1
```

### Metric Contract

```
METRIC_CONTRACT:
  PRIMARY: {name: TBD, direction: higher_is_better}
  CONSTRAINT: {name: runtime_seconds, max: 600}
  BASELINE_TASK: bd-17
  ACCEPTANCE: {min_effect_size: 0.5, max_p_value: 0.05}

METRIC_FILLED:
  PRIMARY: {name: accuracy_retention_pct, direction: higher_is_better, baseline_value: 45.2}
```

### Pre-Registration

```
PRE_REG: HYPOTHESIS=[EWC prevents catastrophic forgetting] | METHOD=[Sequential training on 5 MNIST splits] | CONTROLS=[Naive sequential (no protection)] | EXPECTED_RESULT=[>20% improvement in backward transfer] | CONFOUNDS=[Learning rate sensitivity, task order] | STAT_TEST=[Welch t-test] | SAMPLE_SIZE=[15 (5 tasks x 3 seeds)]
PRE_REG_POWER: EFFECT_SIZE=[d=0.8] | POWER=[0.80] | ALPHA=[0.05] | MIN_N=[15]
PRE_REG_SENSITIVITY: lambda=[100, 400, 1000]
```

These line formats are the canonical forms consumed by `parse_pre_registration()` and the science gates.
