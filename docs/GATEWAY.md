# Gateway Layer Specification

> Intent classification, command routing, conversation memory, knowledge recall, reporting, and Telegram integration.

**TL;DR**: `intent.py` classifies text → mode+rigor. `router.py` dispatches all commands via `CommandRouter` class + free-text handler. `memory.py` = per-chat SQLite. `knowledge.py` searches past findings. `report.py` generates teasers, reports, manuscripts, and PDFs (LaTeX→pandoc→fpdf2 chain). `progress.py` builds narrative digest updates (replaces per-event streaming). `telegram-bridge.py` adds inline buttons, group support, singleton lock. All in `src/voronoi/gateway/`.

## 1. Module Map

```
src/voronoi/gateway/
├── __init__.py       # Empty — namespace package
├── intent.py         # Intent classifier: text → mode + rigor
├── router.py         # Central command router for all user actions
├── config.py         # Configuration loading (.env, .swarm-config.json)
├── memory.py         # Per-chat SQLite conversation memory
├── knowledge.py      # Knowledge store recall (search past findings)
├── literature.py     # Semantic Scholar API integration
├── progress.py       # Progress formatting helpers (Telegram)
├── report.py         # Report/manuscript generation from workspace
├── codename.py       # Brain-themed codename generator
└── handoff.py        # Science → engineering handoff protocol
```

## 2. Intent Classifier (`intent.py`)

### Purpose

Maps free-text user input to a workflow mode and rigor level. This is the first decision point in every request.

### Enums

```python
class WorkflowMode(Enum):
    BUILD       # "build", "implement", "deploy", "refactor"
    INVESTIGATE # "why", "root cause", "hypotheses"
    EXPLORE     # "which best", "compare", "evaluate"
    HYBRID      # "figure out and fix", "paper", "manuscript"
    STATUS      # "/voronoi status"
    RECALL      # "what did we learn", "previous finding"
    GUIDE       # Fallback — unclear intent
```

```python
class RigorLevel(Enum):
    STANDARD      # Build tasks — Builder + Critic only
    ANALYTICAL    # + Scout, Statistician, Explorer, Synthesizer, Evaluator
    SCIENTIFIC    # + Methodologist, Theorist, all gates
    EXPERIMENTAL  # + replication, full pipeline
```

### Core Function

```python
def classify(text: str) -> ClassifiedIntent
```

**Input**: Free-text user message (Telegram or CLI).

**Output**: `ClassifiedIntent(mode, rigor, confidence, summary, original_text)`

**Classification priority** (highest to lowest):
1. Explicit `/voronoi <command>` patterns — exact match
2. Pattern matching against signal banks (investigate, explore, build, hybrid, etc.)
3. Rigor escalation signals (experimental > scientific > analytical)
4. Fallback to `GUIDE` mode (confidence 0.3) if no signals match

**Invariant**: When in doubt, classify **higher** rigor — gates can be skipped but not added retroactively.

### Compound Intent

```python
def classify_compound(text: str) -> list[ClassifiedPhase]
```

Splits multi-phase prompts (e.g., "investigate X then build Y") into ordered phases.

### Signal Banks

| Bank | Example triggers |
|------|-----------------|
| `_INVESTIGATE_SIGNALS` | "why", "root cause", "hypothesis", "correlation" |
| `_EXPLORE_SIGNALS` | "which best", "compare", "evaluation", "tradeoffs" |
| `_EXPERIMENTAL_SIGNALS` | "A/B test", "controlled trial", "p-value" |
| `_ANALYTICAL_SIGNALS` | "optimize", "measure", "metrics", "effect size" |
| `_BUILD_SIGNALS` | "build", "implement", "deploy", "refactor" |
| `_HYBRID_SIGNALS` | "paper", "manuscript", "figure out and fix" |
| `_RECALL_SIGNALS` | "what did we learn", "previous finding" |

### ClassifiedIntent Properties

| Property | Type | Description |
|----------|------|-------------|
| `.is_science` | bool | True if mode is INVESTIGATE, EXPLORE, or HYBRID |
| `.is_meta` | bool | True if mode is STATUS or RECALL |

---

## 3. Command Router (`router.py`)

### Purpose

Central dispatch point for all user actions. Every Telegram command and programmatic call routes through here. Returns formatted strings suitable for Telegram messages.

### Read-Only Handlers

| Function | Returns |
|----------|---------|
| `handle_status(project_dir) -> str` | Queue status: queued, running, recent completed |
| `handle_tasks(project_dir) -> str` | Open Beads tasks from active workspaces |
| `handle_health(project_dir) -> str` | System health check (tmux, beads, git, disk) |
| `handle_ready(project_dir) -> str` | Unblocked tasks ready for work |
| `handle_recall(project_dir, query) -> str` | Knowledge store search results |
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
| `handle_add(project_dir, task_desc) -> str` | Creates new task |
| `handle_abort(project_dir, inv_id) -> str` | Aborts investigation |
| `handle_pivot(project_dir, inv_id, new_question) -> str` | Pivots investigation question |

### Workflow Handlers

| Function | Mode | Rigor |
|----------|------|-------|
| `handle_investigate(project_dir, question, chat_id) -> str` | INVESTIGATE | SCIENTIFIC |
| `handle_explore(project_dir, question, chat_id) -> str` | EXPLORE | ANALYTICAL |
| `handle_build(project_dir, question, chat_id) -> str` | BUILD | STANDARD |
| `handle_experiment(project_dir, question, chat_id) -> str` | INVESTIGATE | EXPERIMENTAL |
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

Search past findings and evidence from completed investigations. Powers the `/recall` command.

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

Assembles narrative digest updates for Telegram. Replaces per-event streaming with batched, contextual messages every ~30 seconds.

### Constants

| Constant | Type | Description |
|----------|------|-------------|
| `MODE_EMOJI` | `dict[str, str]` | `{"investigate": "🔬", "explore": "🧭", "build": "🔨"}` |
| `RIGOR_DESCRIPTIONS` | `dict[str, str]` | Human labels per rigor level |
| `MODE_VERB` | `dict[str, str]` | `{"investigate": "Investigation"}` |
| `PHASE_DESCRIPTIONS` | `dict[str, dict]` | Mode-specific conversational descriptions per phase |

### Phase Names

`starting` → `scouting` → `planning` → `investigating` → `reviewing` → `synthesizing` → `converging` → `complete`

Each phase has unique conversational text per mode (e.g., "Setting things up..." vs "Doing some background research first.").

### Core Digest Builder

```python
def build_digest(
    *, codename: str, mode: str, phase: str, elapsed_sec: float,
    task_snapshot: dict, workspace: str, events_since_last: list[dict],
    eval_score: float = 0.0
) -> str
```

Produces a single narrative message with sections:
1. **Header**: `*Codename* — 2h 15min`
2. **What happened**: Completed tasks, findings, design invalids, new tasks (up to 5)
3. **Where we are**: Phase description + progress bar + ETA
4. **Experiment summary**: From `.swarm/experiments.tsv`
5. **Success criteria**: Met/total with descriptions
6. **Eval score**: Quality score if > 0
7. **Track assessment**: Warning if off-track or on-watch
8. **What's next**: "N agents working right now"

### "What's Up" Digest

```python
def build_digest_whatsup(*, running_investigations: list, queued: int) -> str
```

Multi-investigation overview: per-investigation codename, elapsed, task breakdown, phase, agent health.

### Track Assessment

```python
def assess_track_status(workspace: str, task_snapshot: dict, eval_score: float) -> tuple[str, str]
```

Returns `(status, reason)` where status is `on_track`, `watch`, or `off_track`. Checks for DESIGN_INVALID, success criteria progress, eval score thresholds, and task pacing.

### Message Formatters

```python
def format_launch(codename: str, mode: str, rigor: str, question: str) -> str
def format_complete(codename: str, mode: str, total_tasks: int, closed_tasks: int,
                    elapsed_sec: float, eval_score: float) -> str
def format_failure(codename: str, reason: str, elapsed_sec: float, closed: int,
                   total: int, log_tail: str, retry_count: int, max_retries: int) -> str
def format_alert(codename: str, message: str) -> str
def format_restart(codename: str, attempt: int, max_retries: int, log_tail: str) -> str
```

### Utility Functions

```python
def progress_bar(done: int, total: int, width: int = 20) -> str
def format_duration(seconds: float) -> str         # "45min" or "2h 15min"
def estimate_remaining(elapsed_sec: float, done: int, total: int) -> str
def phase_description(mode: str, phase: str) -> str  # Conversational text
def voronoi_header(inv_id: int, mode: str, suffix: str = "", codename: str = "") -> str
```

### Backward-Compatible Wrappers

```python
def phase_label(mode: str, phase: str) -> str          # Calls phase_description()
def format_workflow_start(mode: str, rigor: str, summary: str) -> str
def format_workflow_complete(mode: str, total_tasks: int, findings: int, duration_min: float) -> str
```

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

Processes non-command messages:
- Checks user allowlist
- Skips group messages unless bot is @mentioned or message is a reply to bot
- Strips @botname, classifies via `CommandRouter.handle_free_text()`

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
