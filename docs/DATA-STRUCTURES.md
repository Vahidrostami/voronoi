# Data Structures Specification

> All dataclasses, enums, database schemas, file formats, and JSON schemas used across the project.

**TL;DR**: Key types: `ClassifiedIntent` (intent.py), `Investigation` (queue.py), `PreRegistration`/`Hypothesis`/`ConvergenceResult` (science/), `DispatcherConfig`/`RunningInvestigation` (dispatcher.py). Two SQLite DBs: `queue.db` (investigations) + `memory.db` (chat). `.swarm/` files: belief-map.json, eval-score.json, convergence.json, experiments.tsv, verify-log-*.jsonl.

## 1. Enums

### WorkflowMode (`gateway/intent.py`)

```python
class WorkflowMode(Enum):
    BUILD = "build"
    INVESTIGATE = "investigate"
    EXPLORE = "explore"
    HYBRID = "hybrid"
    STATUS = "status"
    RECALL = "recall"
    GUIDE = "guide"
```

### RigorLevel (`gateway/intent.py`)

```python
class RigorLevel(Enum):
    STANDARD = "standard"
    ANALYTICAL = "analytical"
    SCIENTIFIC = "scientific"
    EXPERIMENTAL = "experimental"
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
    def is_science(self) -> bool: ...   # INVESTIGATE | EXPLORE | HYBRID
    @property
    def is_meta(self) -> bool: ...      # STATUS | RECALL
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
    status: str                   # queued | running | complete | failed | cancelled
    investigation_type: str       # repo | lab
    repo: str | None
    question: str
    slug: str
    mode: str                     # investigate | explore | build
    rigor: str                    # standard | analytical | scientific | experimental
    codename: str
    workspace_path: str | None
    sandbox_id: str | None
    github_url: str | None
    parent_id: int | None
    demo_source: str | None
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

### PreRegistration (`science/`)

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
```

### Hypothesis (`science/`)

```python
@dataclass
class Hypothesis:
    id: str
    name: str
    prior: float
    posterior: float
    status: str                 # active | confirmed | rejected | merged
    evidence: list[str]
    testability: float
    impact: float
```

### ConvergenceResult (`science/`)

```python
@dataclass
class ConvergenceResult:
    converged: bool
    status: str                 # converged | not_converged | exhausted
    reason: str
    score: float
    blockers: list[str]
```

### ParadigmStressResult (`science/`)

```python
@dataclass
class ParadigmStressResult:
    stressed: bool
    contradiction_count: int
    contradicting_findings: list[str]
    message: str
```

### ConsistencyConflict (`science/`)

```python
@dataclass
class ConsistencyConflict:
    finding_a: str
    finding_b: str
    conflict_type: str          # direction | magnitude | interpretation
    description: str
```

### LabNotebookEntry (`science/`)

```python
@dataclass
class LabNotebookEntry:
    cycle: int
    phase: str                  # observe | orient | decide | act
    verdict: str
    metrics: dict
    failures: list[str]
    next_steps: list[str]
    timestamp: str
```

### FabricationFlag (`science/`)

```python
@dataclass
class FabricationFlag:
    severity: str               # critical | warning | info
    category: str               # missing_data | hash_mismatch | missing_script | suspicious_pattern
    message: str
    finding_id: str
```

### AntiFabricationResult (`science/`)

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
    status TEXT NOT NULL DEFAULT 'queued',
    investigation_type TEXT NOT NULL DEFAULT 'lab',
    repo TEXT,
    question TEXT NOT NULL,
    slug TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'investigate',
    rigor TEXT NOT NULL DEFAULT 'scientific',
    codename TEXT NOT NULL DEFAULT '',
    workspace_path TEXT,
    sandbox_id TEXT,
    github_url TEXT,
    parent_id INTEGER,
    demo_source TEXT,
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
      "impact": 0.95
    }
  ]
}
```

### `.swarm/eval-score.json`

```json
{
  "completeness": 0.85,
  "coherence": 0.90,
  "strength": 0.78,
  "actionability": 0.82,
  "overall": 0.84,
  "notes": "Strong evidence chain, minor gaps in Discussion"
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
  "worker_model": ""
}
```

---

## 9. Beads Note Conventions

Structured metadata stored in Beads task notes:

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
PRE_REG:
  HYPOTHESIS: EWC prevents catastrophic forgetting
  METHOD: Sequential training on 5 MNIST splits
  CONTROLS: Naive sequential (no protection)
  EXPECTED_RESULT: >20% improvement in backward transfer
  CONFOUNDS: Learning rate sensitivity, task order
  STAT_TEST: Welch t-test
  SAMPLE_SIZE: 15 (5 tasks × 3 seeds)
  POWER_ANALYSIS: d=0.8, power=0.80, N=15 sufficient
  SENSITIVITY_PLAN: lambda=[100, 400, 1000]
```
