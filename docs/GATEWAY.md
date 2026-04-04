# Gateway Layer Specification

> Intent classification, command routing, conversation memory, knowledge recall, reporting, and Telegram integration.

**TL;DR**: `intent.py` classifies text → mode+rigor. `router.py` dispatches commands via `CommandRouter` class + free-text handler, delegating to `handlers_query.py`, `handlers_mutate.py`, and `handlers_workflow.py`. `memory.py` = per-chat SQLite. `knowledge.py` searches past findings. `report.py` generates teasers, reports, manuscripts, and PDFs (via `evidence.py` for data extraction and `pdf.py` for rendering). `progress.py` builds narrative digest updates. `telegram-bridge.py` adds inline buttons, group support, singleton lock. All in `src/voronoi/gateway/`.

## 1. Module Map

```
src/voronoi/gateway/
├── __init__.py            # Empty — namespace package
├── intent.py              # Intent classifier: text → mode + rigor
├── router.py              # Central command router (thin dispatch layer)
├── handlers_query.py      # Read-only status/progress/knowledge handlers
├── handlers_mutate.py     # Task/investigation state change handlers
├── handlers_workflow.py   # Investigation enqueue (discover/prove/demo)
├── config.py              # Configuration loading (.env, .swarm-config.json)
├── memory.py              # Per-chat SQLite conversation memory
├── knowledge.py           # Knowledge store recall (search past findings)
├── literature.py          # Semantic Scholar API integration
├── progress.py            # Progress formatting helpers (Telegram)
├── report.py              # Report/manuscript generation facade
├── evidence.py            # Evidence extraction and rendering
├── pdf.py                 # PDF generation strategy chain
├── codename.py            # Brain-themed codename generator
└── handoff.py             # Science → engineering handoff protocol
```

## 2. Intent Classifier (`intent.py`)

### Purpose

Maps free-text user input to a workflow mode and rigor level. Used for explicit `/voronoi` command parsing and as a fallback classifier.

**Note:** For free-text routing in Telegram, the router uses **state-aware dispatch** instead of calling `classify()` directly. See §3 (Router).

### Enums

```python
class WorkflowMode(Enum):
    DISCOVER    # Open question — adaptive rigor
    PROVE       # Specific hypothesis — full science gates
    STATUS      # "/voronoi status"
    RECALL      # "what did we learn", "previous finding"
    GUIDE       # Explicit operator guidance (/voronoi guide)
    ASK         # Mid-investigation question — Q&A about running work
```

```python
class RigorLevel(Enum):
    ADAPTIVE      # DISCOVER — starts light, escalates
    SCIENTIFIC    # PROVE — full gates from the start
    EXPERIMENTAL  # PROVE + replication
```

### Core Functions

```python
def classify(text: str) -> ClassifiedIntent
```

**Input**: Free-text user message (Telegram or CLI).

**Output**: `ClassifiedIntent(mode, rigor, confidence, summary, original_text)`

**Classification priority** (highest to lowest):
1. Explicit `/voronoi <command>` patterns — exact match
2. ASK signals (mid-investigation questions)
3. PROVE signals (specific hypotheses, controlled experiments)
4. DISCOVER signals (open questions, building, exploring)
5. RECALL signals (knowledge queries)
6. Fallback to `GUIDE` mode (confidence 0.3) if no signals match

```python
def classify_for_new_investigation(text: str) -> ClassifiedIntent
```

**Purpose**: Simplified classifier used by the state-aware router when **no investigation is running**. Only returns DISCOVER, PROVE, or RECALL — never ASK or GUIDE. Low-confidence messages default to DISCOVER (the router prompts the user).

### Compound Intent

```python
def classify_compound(text: str) -> list[ClassifiedPhase]
```

Splits multi-phase prompts (e.g., "investigate X then build Y") into ordered phases.

### Signal Banks

| Bank | Example triggers |
|------|-----------------|
| `_PROVE_SIGNALS` | "test whether", "prove", "A/B test", "controlled trial", "sample size" |
| `_DISCOVER_SIGNALS` | "why", "root cause", "compare", "build", "optimize", "paper on" |
| `_RECALL_SIGNALS` | "what did we learn", "previous finding", "history of" |
| `_ASK_SIGNALS` | "any results", "how is the results", "update me on", "what have agents found" |

### ClassifiedIntent Properties

| Property | Type | Description |
|----------|------|-------------|
| `.is_science` | bool | True if mode is DISCOVER or PROVE |
| `.is_meta` | bool | True if mode is STATUS, RECALL, GUIDE, or ASK |

---

## 3. Command Router (`router.py`)

### Purpose

Central dispatch point for all user actions. Every Telegram command and programmatic call routes through here. Returns formatted strings suitable for Telegram messages.

### Read-Only Handlers

| Function | Returns |
|----------|---------|
| `handle_status(project_dir) -> str` | Queue status: queued, running, recent completed |
| `handle_ask(project_dir, question) -> str` | Answer a natural-language question about a running investigation |
| `handle_tasks(project_dir) -> str` | Open Beads tasks from active workspaces |
| `handle_health(project_dir) -> str` | System health check (tmux, beads, git, disk) |
| `handle_ready(project_dir) -> str` | Unblocked tasks ready for work |
| `handle_recall(project_dir, query) -> str` | Workspace recall plus cross-investigation findings |
| `handle_belief(project_dir) -> str` | Current belief map |
| `handle_journal(project_dir) -> str` | Investigation journal |
| `handle_finding(project_dir, finding_id) -> str` | Single finding detail |
| `handle_results(project_dir) -> str` | Recent investigation results |
| `handle_guide(project_dir, question) -> str` | Guidance for unclear intent |

### Mutation Handlers

| Function | Effect |
|----------|--------|
| `handle_reprioritize(project_dir, task_id, priority) -> str` | Changes task priority |
| `handle_pause(project_dir, task_id) -> str` | Pauses a task |
| `handle_resume(project_dir, task_id) -> str` | Resumes a paused task |
| `handle_resume_investigation(project_dir, inv_id_or_codename) -> str` | Resumes a paused/failed investigation |
| `handle_add(project_dir, task_desc) -> str` | Creates new task |
| `handle_complete(project_dir, task_id, reason) -> str` | Closes a Beads task (bd-xxx) |
| `handle_complete_investigation(project_dir, id_or_codename) -> str` | Accepts and closes a reviewed investigation |
| `handle_abort(project_dir, inv_id) -> str` | Aborts investigation |
| `handle_pivot(project_dir, inv_id, new_question) -> str` | Pivots investigation question |

### Iterative Science Handlers

| Function | Effect |
|----------|--------|
| `handle_review_investigation(project_dir, id_or_codename) -> str` | Show Claim Ledger in review format |
| `handle_continue_investigation(project_dir, id_or_codename, feedback) -> str` | Create continuation run with PI feedback |
| `handle_complete_investigation(project_dir, id_or_codename) -> str` | Accept and close a reviewed investigation |
| `handle_claims(project_dir, id_or_codename) -> str` | Show current claim ledger state |

These handlers interact with the Claim Ledger (`~/.voronoi/ledgers/<lineage_id>/claim-ledger.json`). The `continue` handler parses natural-language feedback for `lock C1`, `challenge C2: reason` patterns and updates the ledger before creating the continuation investigation. PI feedback is stored in the `pi_feedback` field on `Investigation` — it is NOT appended to the question text. The dispatcher reads `pi_feedback` to build the warm-start prompt context.

### Workflow Handlers

| Function | Mode | Rigor |
|----------|------|-------|
| `handle_discover(project_dir, question, chat_id) -> str` | DISCOVER | ADAPTIVE |
| `handle_prove(project_dir, hypothesis, chat_id) -> str` | PROVE | SCIENTIFIC |
| `handle_demo(project_dir, demo_name, chat_id, dry_run, safe) -> str` | (from demo) | (from demo) |

### Internal Helpers

- `_enqueue(project_dir, question, mode, rigor, chat_id) -> tuple[int, str, str]` — Returns `(inv_id, status_msg, codename)`. Creates `Investigation`, enqueues in `queue.db`.
- `_get_active_workspaces(project_dir) -> list[tuple[str, str]]` — Returns `(path, label)` for running investigations.
- `_run_bd(*args, cwd)` — Short-circuits with empty result if `.beads/` doesn't exist.

### Dependencies

- `voronoi.beads.run_bd`, `has_beads_dir`
- `voronoi.gateway.intent.classify`
- `voronoi.gateway.progress.*`
- `voronoi.gateway.codename.codename_for_id`
- `voronoi.gateway.memory.ConversationMemory`
- `voronoi.gateway.knowledge.KnowledgeStore`
- `voronoi.server.queue.InvestigationQueue`
- `voronoi.server.runner.make_slug`

---

## 4. Configuration (`config.py`)

### Loading Hierarchy (lowest to highest priority)

1. `.env` in current directory
2. `~/.voronoi/.env`
3. `.swarm-config.json` in current dir / repo root / `~/.voronoi/`
4. Environment variables (highest priority — always win)

### Config Keys

| Key | Source | Description |
|-----|--------|-------------|
| `bot_token` | `VORONOI_TG_BOT_TOKEN` | Telegram bot token |
| `user_allowlist` | `VORONOI_ALLOWED_USERS` | Comma-separated Telegram user IDs |
| `ops_users` | `VORONOI_TG_OPS_USERS` | Comma-separated user IDs/usernames for `/voronoi ops`. Falls back to `user_allowlist` if not set. |
| `bridge_enabled` | `.swarm-config.json` | Whether Telegram bridge is active |
| `project_dir` | `.swarm-config.json` | Default project directory |
| `project_name` | `.swarm-config.json` | Human-readable project name |
| `swarm_dir` | `.swarm-config.json` | Agent working directory |
| `agent_command` | `VORONOI_AGENT_COMMAND` | Agent CLI command (default: "copilot") |
| `orchestrator_model` | `VORONOI_ORCHESTRATOR_MODEL` | Model for orchestrator |
| `worker_model` | `VORONOI_WORKER_MODEL` | Model for workers |
| `gh_token` | `GITHUB_TOKEN` / `GH_TOKEN` | GitHub auth for publishing |

### Functions

```python
def load_dotenv(env_path: Path | None = None) -> None
def load_config(config_path: str = ".swarm-config.json") -> dict
def save_chat_id(project_dir: str, chat_id: int | str) -> None
def get_chat_id(project_dir: str) -> str | None
```

---

## 5. Conversation Memory (`memory.py`)

### Purpose

Per-chat SQLite conversation memory for multi-turn scientific discussions. Maintains context across messages within a conversation.

### Data Structures

```python
@dataclass
class Message:
    chat_id: str
    role: str          # "user" | "assistant" | "system"
    content: str
    timestamp: float
    metadata: dict     # Arbitrary key-value pairs
    message_id: str | None = None
```

```python
@dataclass
class ConversationContext:
    chat_id: str
    messages: list[Message]
    summary: str | None
    active_workflow_id: str | None
```

### ConversationMemory API

```python
class ConversationMemory:
    def __init__(self, db_path: str | Path): ...
    def save_message(self, msg: Message) -> int: ...
    def get_context(self, chat_id: str, max_messages: int = 20,
                    max_age_seconds: float = 1800) -> ConversationContext: ...
    def set_summary(self, chat_id: str, summary: str) -> None: ...
    def set_active_workflow(self, chat_id: str, workflow_id: str | None) -> None: ...
    def get_message_count(self, chat_id: str) -> int: ...
    def clear_chat(self, chat_id: str) -> int: ...  # Returns count deleted
```

### Database Schema

| Table | Columns | Notes |
|-------|---------|-------|
| `messages` | id, chat_id, role, content, timestamp, metadata, created_at | Index on (chat_id, timestamp DESC) |
| `conversation_state` | chat_id, summary, active_workflow_id, last_activity, updated_at | UPSERT on save |

**Configuration**: SQLite WAL mode, 10s timeout, context window: 30 min / 20 messages.

---

## 6. Knowledge Store (`knowledge.py`)

### Purpose

Search past findings and evidence from the current workspace plus completed investigations. Powers the `/recall` command.

### Finding Data Structure

```python
@dataclass
class Finding:
    id: str
    title: str
    status: str
    priority: int
    notes: list[str]
    # Extracted from notes:
    effect_size: str | None
    confidence_interval: str | None
    sample_size: str | None
    stat_test: str | None
    valence: str | None    # positive | negative | inconclusive
    confidence: str | None
    data_file: str | None
    robust: str | None     # yes | no
```

### KnowledgeStore API

```python
class KnowledgeStore:
    def __init__(self, project_dir: str | Path): ...
    def search_findings(self, query: str, max_results: int = 10) -> list[Finding]: ...
    def get_journal(self, max_lines: int = 30) -> str | None: ...
    def get_belief_map(self) -> str | None: ...
    def get_strategic_context(self) -> str | None: ...
    def format_recall_response(self, query: str, max_results: int = 5) -> str: ...
```

**Search algorithm**: Hybrid BM25 keyword + weighted scoring. Combines:
- **BM25** (via in-memory SQLite FTS5): Exact token matching for IDs (`bd-42`), data hashes (`sha256:...`), stat values (`d=0.82`), method names (`ANOVA`).
- **Keyword scoring**: Weighted word overlap on title + notes, boosted for completed findings and investigations.

Weighted combination: 60% keyword + 40% BM25. Falls back to keyword-only if FTS5 is unavailable.

### FederatedKnowledge API

```python
class FederatedKnowledge:
    def __init__(self, db_path: Path | None = None): ...
    def sync_findings(self, investigation_id: str, codename: str, workspace: Path) -> int: ...
    def search(self, query: str, max_results: int = 10) -> list[Finding]: ...
    def format_search_response(self, query: str, max_results: int = 5) -> str: ...
```

**Cross-investigation search**: Persistent SQLite index at `~/.voronoi/knowledge.db`. The dispatcher syncs findings from every completed investigation via `sync_findings()`. `/recall` first searches the active workspace, then appends non-duplicate cross-investigation findings from the federated index. Search queries return findings with `codename:task_id` composite IDs. The index prefers FTS5 when available and falls back to `LIKE` search on SQLite builds without FTS5. This enables:
- Detecting redundant work across investigations
- Surfacing prior findings when starting new investigations
- Building a cumulative knowledge base that grows with each completed study

---

## 7. Literature Search (`literature.py`)

### Purpose

Queries Semantic Scholar API for prior work. Used by Scout agents.

### Paper Data Structure

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

### Functions

```python
def search_papers(query: str, max_results: int = 5) -> list[Paper]: ...
def format_literature_brief(papers: list[Paper]) -> str: ...
```

**API**: `https://api.semanticscholar.org/graph/v1`, timeout 15s, returns empty list on any failure.

---

## 8. Progress Formatting (`progress.py`)

### Purpose

Assembles phase-aware, milestone-driven digest updates for Telegram. Adapts message structure, detail level, and tone to the current investigation phase and elapsed time. Uses a **two-tier delivery model** (edit-in-place for status, new messages for milestones) to avoid notification flood during long-running investigations.

### Voice System (inspired by OpenClaw's SOUL.md)

Voronoi has a personality layer defined in `VOICE_PHASE_VARIANTS` — a dictionary of 2-3 variant phrases per phase that rotate deterministically by codename hash. This ensures different investigations get different wording while the same investigation stays consistent.

Voice tone: **sharp research lab manager** — confident, concise, research-aware. Speaks in terms of scientific progress, not task management.

### Design Philosophy

Messages adapt to the user's needs at each stage of a long-running investigation:

| Phase | Strategy | Rationale |
|-------|----------|-----------|
| Early (setup/planning) | Set expectations, no empty bars | 0% progress is demoralizing and misleading |
| Active (investigating) | Highlight achievements, show ETA | Users need pace and milestones |
| Late (reviewing/converging) | Focus on quality and criteria | Users want to know "how good" |
| Complete | Celebrate, summarize | Users want the outcome |

Key rules:
- **Two-tier delivery**: Status updates edit in place (silent); findings/phase changes send new messages (notification)
- **No empty progress bars**: Show bar only when at least 1 task is completed
- **Narrative synthesis**: Phase descriptions generated from workspace artifacts (experiments, criteria, beliefs) — not static templates
- **Don't alarm for normal states**: "watch" status suppressed during early phases
- **Milestone markers**: `✓` for completions, `★` for findings, `⚠` for problems
- **Phase position**: Header shows "Phase X/Y" journey indicator
- **Adaptive criteria display**: Early → just count; mid → ratio with context ("getting close"); late/detail → full list
- **Typing indicator**: Sent before milestone notifications for natural feel

### Constants

| Constant | Type | Description |
|----------|------|-------------|
| `MODE_EMOJI` | `dict[str, str]` | `{"discover": "🔬", "prove": "🧪"}` |
| `RIGOR_DESCRIPTIONS` | `dict[str, str]` | Human labels per rigor level |
| `MODE_VERB` | `dict[str, str]` | `{"discover": "discovery"}` |
| `VOICE_PHASE_VARIANTS` | `dict[str, list[str]]` | Per-phase rotating variant phrases |
| `VOICE_CRITERIA_CONTEXT` | `dict[str, str]` | Context labels: "early days", "getting close" |
| `VOICE_QUALITY_LABELS` | `dict[str, str]` | Quality labels: "solid", "improving" |
| `PHASE_DESCRIPTIONS` | `dict[str, dict]` | Mode-specific static descriptions (fallback) |
| `PHASE_ORDER` | `list[str]` | Ordered phase list for journey position |
| `MSG_TYPE_*` | `str` | Message type constants for delivery routing |

### Message Types (for two-tier delivery)

| Constant | Value | Delivery | Notification? |
|----------|-------|----------|:---:|
| `MSG_TYPE_STATUS` | `"status"` | Edit in place | No |
| `MSG_TYPE_MILESTONE` | `"milestone"` | New message | Yes |

Launch, completion, failure, alert, and restart messages always send as new messages (via their dedicated `format_*` functions). The `MSG_TYPE_*` constants are only needed for `build_digest()` return values.

### Phase Names

`starting` → `scouting` → `planning` → `investigating` → `reviewing` → `synthesizing` → `converging` → `complete`

Each phase has unique conversational text per mode, plus rotating VOICE variants per codename.

### Narrative Synthesis

```python
def _synthesize_narrative(workspace: Path, phase: str, task_snapshot: dict, elapsed_sec: float) -> str
```

Reads workspace artifacts (experiments.tsv, success-criteria.json, belief-map.json) and produces a context-aware 1-2 sentence description. Returns `''` when artifacts are insufficient, allowing fallback to VOICE variants. Examples:
- "3/8 experiments passed, 2 discarded. 4/13 criteria met — making progress."
- "Leading hypothesis: GABA encoding (P=0.85)."

### Core Digest Builder

```python
def build_digest(
    *, codename: str, mode: str, phase: str, elapsed_sec: float,
    task_snapshot: dict, workspace: Path, events_since_last: list[dict],
    eval_score: float = 0.0, compact: bool = False,
) -> tuple[str, str]
```

Returns `(message_text, message_type)`. The message_type tells the delivery layer whether to edit-in-place (`MSG_TYPE_STATUS`) or send a new message (`MSG_TYPE_MILESTONE`).

Produces a **narrative-first** message with an optional metrics footer:
1. **Header**: `*Codename* — 2h 15min`
2. **Narrative paragraph**: Conversational summary merging phase description, agent activity, and "so what?" calibration into a single readable paragraph. Uses `_build_narrative_paragraph()` which synthesizes from artifacts, folds in agent count and pace, and adds context like "normal at this stage" or "results are looking strong."
3. **Milestones**: `✓` completions, `★` findings, `⚠` problems (since last update)
4. **Metrics footer**: Compact progress section with bar, experiments, criteria, quality — visually separated from the narrative
6. **Criteria**: Adaptive — count with context label mid-run, full list in detail view
7. **Quality**: Score with voice label ("solid" vs "improving")
8. **Track assessment**: Only `off_track` always shown; `watch` suppressed in early phases
9. **Agent count**: Brief "N agents active"
10. **Pace info**: "Averaging Xh per task" for long-running investigations

### "What's Up" Digest

```python
def build_digest_whatsup(*, running_investigations: list, queued: int) -> str
```

Multi-investigation overview with phase position, VOICE-rotated descriptions, adaptive progress. Only surfaces agent health problems (stuck agents), not "healthy" counts.

### Track Assessment

```python
def assess_track_status(workspace: Path, task_snapshot: dict, eval_score: float) -> tuple[str, str]
```

Returns `(status, reason)` where status is `on_track`, `watch`, or `off_track`. Watch messages use non-alarming language for normal early states.

### Journey Position

```python
def phase_position(phase: str) -> tuple[int, int]
```

Returns `(current_step, total_steps)` for phase journey display. 1-based.

### Message Formatters

```python
def format_launch(codename: str, mode: str, rigor: str, question: str) -> str
def format_complete(codename: str, mode: str, total_tasks: int, closed_tasks: int,
                    elapsed_sec: float, eval_score: float) -> str
def format_failure(codename: str, reason: str, elapsed_sec: float, closed: int,
                   total: int, log_tail: str, retry_count: int, max_retries: int) -> str
def format_alert(codename: str, message: str) -> str
def format_restart(codename: str, attempt: int, max_retries: int, log_tail: str) -> str
def format_wake(codename: str, n_events: int = 0) -> str
def format_pause(codename: str, reason: str, elapsed_sec: float,
                 closed: int, total: int) -> str
```

### Utility Functions

```python
def progress_bar(done: int, total: int, width: int = 20) -> str
def format_duration(seconds: float) -> str         # "45min" or "2h 15min"
def estimate_remaining(elapsed_sec: float, done: int, total: int) -> str
def phase_description(mode: str, phase: str, codename: str = "") -> str  # VOICE-rotated or static
def phase_position(phase: str) -> tuple[int, int]     # Journey position (step, total)
```

---

## 8b. Mid-Investigation Q&A (`handlers_query.py` — `handle_ask`)

### Purpose

Lets users ask natural-language questions about running investigations and get conversational answers without terminal access. Gathers workspace artifacts (experiments.tsv, success-criteria.json, belief-map.json, task list, journal, findings) and sends them with the user's question to Copilot CLI for a one-shot LLM answer. Falls back to keyword-based synthesis when Copilot is unavailable.

### Function

```python
def handle_ask(project_dir: str, question: str) -> str
```

**Invoked by**: `/voronoi ask <question>` command or ASK intent from free-text classification.

**Returns**: A conversational LLM-generated answer grounded in workspace data (primary), or a keyword-matched structured response (fallback).

### Architecture

```
User question
    │
    ▼
_gather_workspace_context()   ← reads experiments, criteria, beliefs, tasks, journal
    │
    ▼
_build_ask_prompt()           ← system prompt + workspace JSON + user question
    │
    ▼
_run_copilot_query()          ← copilot -p "<prompt>" -s --no-color
    │
    ├── success → return LLM answer
    │
    └── failure → _answer_from_context()  ← keyword-based fallback
```

### Data Sources

| Artifact | Path | What's gathered |
|----------|------|-----------------|
| Experiments | `.swarm/experiments.tsv` | Total, passed, discarded, crashed, details (capped at 20) |
| Success criteria | `.swarm/success-criteria.json` | Items, how many met |
| Belief map | `.swarm/belief-map.json` | Hypotheses with priors/posteriors |
| Tasks | `bd list --json` | Total, closed, in-progress, items (capped at 30) |
| Journal | `.swarm/journal.md` | Last 20 lines |

### Copilot CLI Integration

Uses the same Copilot CLI that agents use, with the configured worker model:

- Binary: `copilot` (must be on PATH)
- Model: `VORONOI_WORKER_MODEL` env var (falls back to Copilot default)
- Flags: `-p <prompt> -s --no-color`
- Timeout: 60 seconds
- Prompt instructs LLM to answer ONLY from workspace data, format for Telegram

### Fallback: Keyword-Based Synthesis

When Copilot is unavailable (not installed, auth expired, timeout), falls back to `_answer_from_context()` which uses keyword matching:

| Question about... | Keywords matched | Data sources used |
|-------------------|------------------|-------------------|
| Experiments/results | experiment, result, data, show, found, finding | `experiments.tsv`, findings |
| Failures/crashes | fail, crash, error, wrong, problem, issue | `experiments.tsv` (crash/discard), task notes |
| Specific methods | classifier, model, method, algorithm, ... | `experiments.tsv` descriptions |
| Hypotheses/beliefs | hypothes, belief, theory, leading | `belief-map.json` |
| Success criteria | criteri, success, progress, track, going | `success-criteria.json`, tasks |
| General | *(catch-all)* | All sources combined |

**Keyword priority**: The method-specific branch is checked *before* the hypothesis branch to prevent generic words from misrouting classifier/model questions.

**Float safety**: Hypothesis prior/posterior values are converted via `_safe_float()` which returns 0.0 for non-numeric values (`"N/A"`, `None`, `"TBD"`). This prevents crashes when LLM agents write non-numeric belief map entries.

### Safety Measures

- **Response length cap**: Both LLM and fallback responses are capped at 3500 characters (`_ASK_MAX_RESPONSE`) to stay within Telegram's 4096-character message limit. Truncated responses end with `… _(truncated)_`.
- **Prompt injection defense**: The user's question is placed inside a code fence (```` ``` ````) in the LLM prompt, with an explicit instruction to treat it as data, not follow any instructions it may contain.

### Design Decisions

- **LLM-first, fallback-safe**: Copilot CLI provides natural conversational answers; keyword matching ensures the feature works without external dependencies.
- **Multi-investigation**: Scans all running investigations and returns answers per codename.
- **Grounded answers**: System prompt instructs LLM to answer ONLY from workspace data — no hallucination.
- **Graceful degradation**: When artifacts don't exist yet (early phases), says so explicitly rather than returning empty data.
- **Read-only**: Never modifies workspace state. Safe to call at any time.
- **No runtime dependency**: Copilot CLI is an optional external tool, not a Python dependency.

---

## 9. Report Generator (`report.py`)

### Purpose

Generates teasers, markdown reports, scientific manuscripts, and PDFs from investigation workspaces.

### ReportGenerator API

```python
class ReportGenerator:
    def __init__(self, workspace_path: Path, mode: str | None = None,
                 rigor: str | None = None): ...

    @property
    def is_manuscript(self) -> bool: ...  # scientific/experimental rigor
    @property
    def doc_type(self) -> str: ...        # "manuscript" or "report"
```

### Format Decision Logic

A workspace produces a **manuscript** if:
- Rigor is `scientific` or `experimental`, OR
- Content contains 3+ paper section headings (abstract, introduction, methods, results, discussion)

Otherwise it produces a **report**.

### Key Methods

| Method | Returns | Purpose |
|--------|---------|---------|
| `_get_findings()` | `list[dict]` | All findings from Beads (parses EFFECT_SIZE, CI_95, etc.) |
| `_render_belief_map()` | `str \| None` | Simple markdown belief map |
| `_render_belief_narrative()` | `str \| None` | Hypothesis trajectories with ↑↓→ arrows |
| `_render_evidence_chain()` | `str \| None` | Claim → finding traceability with audit warnings |
| `_render_findings_table(findings)` | `list[str]` | Tabular findings |
| `_render_findings_interpreted(findings)` | `list[str]` | With statistical interpretation |
| `_render_limitations(findings)` | `str \| None` | Fragile, wide-CI, unreviewed, rejected findings |
| `_render_cross_finding_comparison(findings)` | `str \| None` | Ranking by effect size, mixed valence notes |
| `_render_negative_results(findings)` | `str \| None` | Dedicated section for negative/inconclusive results |
| `_pick_headline(findings)` | `dict` | Finding with largest effect size |
| `build_teaser(investigation_id, question, total_tasks, closed_tasks, elapsed_min, *, mode, codename)` | `str` | Telegram-optimized completion summary |
| `build_auto_markdown()` | `str` | Chooses manuscript or report format |
| `build_markdown()` | `str` | Standard/analytical report |
| `build_manuscript_markdown()` | `str` | Scientific manuscript format |
| `build_pdf()` | `Path \| None` | PDF via strategy chain |

### Teaser Format (Telegram)

Sent on investigation completion:
- Header: `🏁 *Codename* 🔬 COMPLETE · 45min`
- Question
- 💡 Headline finding (largest effect, with ✅/❌ emoji, d=, CI, p, N)
- All findings list
- Progress bar + finding count
- "📎 Full report attached"

### PDF Strategy Chain

Tries each strategy in order, stops at first success:
1. **Pre-compiled PDF** — agent may have generated one
2. **LaTeX compilation** — tries latexmk, pdflatex, tectonic
3. **Pandoc** — markdown → PDF
4. **fpdf2** — basic markdown → PDF
5. **Fallback** — returns `.md` file

After strategy 1 (pre-compiled) or 2 (LaTeX) succeeds, the result is also copied to the demo output directory (`demos/<name>/output/paper/`) if a single demo directory exists in the workspace. Markdown-based fallbacks (pandoc, fpdf2, .md) are NOT copied — the paper folder is reserved for publication-quality output.

### Report Sections (Standard/Analytical)

Question → Executive Summary → Evidence Chain → Interpreted Findings → Summary Table → Comparative Analysis → Negative Results → Hypothesis Trajectory → Methodology Journal → Detailed Conclusion → Limitations

### Manuscript Sections (Scientific/Experimental)

Full deliverable (pre-written manuscript) + appended: Evidence Chain, Interpreted Findings, Comparative Analysis, Negative Results, Limitations

---

## 10. Codename Generator (`codename.py`)

### Purpose

Deterministic brain-themed codenames for investigations. Makes investigations identifiable in Telegram messages.

### Codename Pool

Dopamine, Serotonin, GABA, Glutamate, Oxytocin, Endorphin, Acetylcholine, Norepinephrine, Anandamide, Adrenaline, Melatonin, Cortisol, Histamine, Glycine

### Functions

```python
def codename_for_id(inv_id: int) -> str        # Deterministic: id % len(pool)
def theme_for_codename(name: str) -> str        # Thematic description
def codename_pool_prompt() -> str               # Formatted for LLM selection
```

---

## 11. Handoff Protocol (`handoff.py`)

### Purpose

Structured handoff from Voronoi science → engineering systems (e.g., Anton). Creates GitHub issues or Beads tasks from investigation findings.

### FixSpec Data Structure

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

### AntonHandoff API

```python
class AntonHandoff:
    def __init__(self, project_dir: str | Path): ...
    def create_beads_task(self, spec: FixSpec) -> tuple[bool, str]: ...
    def create_github_issue(self, spec: FixSpec) -> tuple[bool, str]: ...
    def create_validation_task(self, spec: FixSpec, fix_task_id: str) -> tuple[bool, str]: ...
    def format_handoff_notification(self, spec: FixSpec, task_id: str) -> str: ...
```

All mutation methods return `(success: bool, message: str)` — never raise exceptions.

---

## 12. Telegram Bridge (`scripts/telegram-bridge.py`)

### Purpose

Main I/O bridge between Telegram and Voronoi business logic. Runs as a standalone process with singleton lock.

### Architecture

```
Telegram API ↔ telegram-bridge.py ↔ CommandRouter (business logic)
                      ↕
              InvestigationDispatcher (background jobs)
```

### Singleton Lock

TCP socket on port derived from bot token hash. Prevents dual instances polling the same bot token.

### Command Handler (`/voronoi`)

Parses `/voronoi <subcommand> [args]`, routes through `CommandRouter.route()`, adds contextual inline buttons to response.

### Free-Text Handler

Processes non-command messages using **state-aware routing**:
- Checks user allowlist
- Skips group messages unless bot is @mentioned or message is a reply to bot
- Strips @botname, routes via `CommandRouter.handle_free_text()`

**State-aware routing logic:**
- If an investigation is running → route to ASK (LLM-powered Q&A about the investigation)
- If no investigation is running → classify as DISCOVER/PROVE and start a new investigation
- Greetings → intro message

This eliminates the old regex-based ASK classification, which missed natural phrasings like "any new results?" or "how is the results so far?" and defaulted to GUIDE ("Guidance noted"). Now any free text while an investigation is running gets a real answer.

### Inline Button Callbacks

Handles button presses from previous messages. Routes to appropriate handler (status, health, tasks, abort, belief, results, guide).

### Contextual Inline Buttons

Buttons change based on message content:

| After this message... | Buttons shown |
|-----------------------|---------------|
| Workflow launch | [📊 Status] [🛑 Abort] |
| Status command | [📋 Tasks] [⚡ Ready] [🩺 Health] |
| Digest update | [Progress] [Guide] [Abort] |
| Completion | [Details] [Belief Map] |

### Dispatcher Integration

The bridge runs the dispatcher as background jobs via PTB's job queue:
- `dispatch_next()` every **10 seconds** — launches queued investigations
- `poll_progress()` every **30 seconds** — monitors running investigations

Dispatcher callbacks (`send_message`, `send_document`) use `call_soon_threadsafe` to schedule coroutines in the main async loop.

### Group Support

- Private chats: all messages processed
- Group chats: only responds when @mentioned or when message is a reply to a bot message

### Message Sending

All sends use Markdown parse mode with best-effort fallback to plain text. Document attachments sent separately, failures logged but don't break text delivery.

## 13. Ops Commands (`handlers_query.py:handle_ops`)

### Purpose

Read-only server diagnostics exposed via `/voronoi ops <command>`. Gives operators visibility into the server's runtime state (tmux sessions, processes, disk usage, logs) without requiring a separate SSH session.

### Security Model

- **No user input reaches a shell.** Each ops subcommand maps to a hardcoded `subprocess.run([...])` invocation with a fixed argument list. The subcommand name is matched against an allowlist dict — unknown subcommands are rejected.
- **Ops-user restriction.** Gated by `VORONOI_TG_OPS_USERS` env var (comma-separated user IDs/usernames). Falls back to `VORONOI_TG_USER_ALLOWLIST` if not set. The router receives an `ops_allowed` flag from the bridge, which checks this list before forwarding.
- **Output truncation.** Subprocess output is truncated to 3500 characters to stay within Telegram's 4096-char message limit (accounting for header/timestamp formatting).

### Available Commands

| Subcommand | Subprocess | Description |
|------------|------------|-------------|
| `tmux` | `tmux list-sessions` | List active tmux sessions |
| `agents` | `ps aux \| grep -E 'copilot\|claude'` | Show agent-related processes |
| `disk` | `du -sh ~/.voronoi/active/*` | Disk usage per investigation workspace |
| `logs` | `tail -30 <latest agent.log>` | Last 30 lines of most recent agent log |
| *(no args)* | — | Show available ops subcommands |

### Function Signature

```python
def handle_ops(project_dir: str, sub: str, *, ops_allowed: bool = True) -> str:
```

- `ops_allowed=False` → returns an unauthorized message without executing anything
- Unknown subcommand → returns help listing available commands

### Router Wiring

```python
elif sub == "ops":
    ops_sub = args[0] if args else ""
    return handle_ops(self.project_dir, ops_sub, ops_allowed=ops_allowed), None
```

The `route()` method receives `ops_allowed` as a keyword argument (default `True` for CLI usage). The Telegram bridge sets it based on the `ops_users` config list.
