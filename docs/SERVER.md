# Server Layer Specification

> Investigation queue, dispatcher, workspace provisioning, sandbox isolation, prompt building, publishing.

**TL;DR**: `queue.py` = SQLite lifecycle (queued→running→complete). `dispatcher.py` polls queue, provisions workspaces, monitors progress; delegates tmux to `tmux.py`. `snapshot.py` = read-only workspace state capture (shared by dispatcher + gateway). `prompt.py` = single source of truth for all orchestrator prompts. `workspace.py` provisions with git clone/worktree. `sandbox.py` = optional Docker. All in `src/voronoi/server/`.

## 1. Module Map

```
src/voronoi/server/
├── __init__.py       # Re-exports extract_repo_url
├── queue.py          # SQLite investigation queue (lifecycle management)
├── dispatcher.py     # Provisions workspaces, launches agents, monitors progress
├── tmux.py           # TMux session launch, auth check, cleanup
├── snapshot.py       # WorkspaceSnapshot — read-only .swarm/ state capture
├── prompt.py         # Unified orchestrator prompt builder
├── workspace.py      # Workspace provisioning (clone, worktree, init)
├── sandbox.py        # Docker sandbox isolation
├── runner.py         # Server config, queue runner, slug generation
├── publisher.py      # GitHub publishing of investigation results
├── compact.py        # Workspace state compaction
├── events.py         # Structured event log
└── repo_url.py       # GitHub URL parsing from free text
```

## 2. Investigation Queue (`queue.py`)

### Purpose

SQLite-backed investigation lifecycle management. Global queue (`~/.voronoi/queue.db`) shared across all investigations.

### Investigation Data Structure

```python
@dataclass
class Investigation:
    id: int              # Auto-assigned on enqueue
    chat_id: str         # Telegram chat or CLI session
    status: str          # queued | running | paused | review | complete | failed | cancelled
    investigation_type: str  # "repo" | "lab"
    repo: str | None     # GitHub repo URL (repo-type only)
    question: str        # The user's question/task
    slug: str            # Filesystem-safe identifier
    mode: str            # discover | prove
    rigor: str           # adaptive | scientific | experimental
    codename: str        # Brain-themed codename
    workspace_path: str | None
    sandbox_id: str | None
    github_url: str | None
    parent_id: int | None    # For follow-up investigations
    demo_source: str | None  # Demo name if from demo
    lineage_id: int | None   # Root investigation ID for claim ledger scoping
    cycle_number: int        # Iteration round within a lineage (default 1)
    created_at: float
    started_at: float | None
    completed_at: float | None
    error: str | None
```

### State Machine

```
         enqueue()
           │
           ▼
       ┌───────┐
       │queued  │
       └───┬───┘
           │ next_ready()  [atomic: SELECT + UPDATE in one transaction]
           ▼
       ┌───────┐
       │running │──────────────────────┐
       └───┬───┘                       │
           │                           │
     ┌─────┼─────┼──────┼─────┐   cancel()
     │     │     │      │     │        │
  complete() fail() pause() review()   │
     │     │     │      │     │        │
     ▼     ▼     ▼      ▼     ▼        ▼
 ┌────────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐
 │complete│ │failed│ │paused│ │review│ │cancelled │
 └────────┘ └──┬───┘ └──┬───┘ └──┬───┘ └──────────┘
               │        │        │
               └────┬───┘   continue_investigation() / accept()
                    │            │              │
                    │ resume()   │              │ accept()
                    ▼            ▼              ▼
               ┌───────┐    ┌───────┐    ┌────────┐
               │running │    │queued │    │complete│
               └───────┘    └───────┘    └────────┘
                        (new inv, same lineage)
```

The `review` state is entered when a science investigation (mode=discover/prove) converges successfully. The PI reviews claims, provides feedback, and can continue to a new round (`continue_investigation`) or accept and close (`accept`). Build-mode investigations skip `review` and go directly to `complete`.

### InvestigationQueue API

```python
class InvestigationQueue:
    def __init__(self, db_path: str | Path): ...

    # Mutation
    def enqueue(self, inv: Investigation) -> int: ...       # Returns investigation ID
    def next_ready(self, max_concurrent: int = 2) -> Investigation | None: ...  # Atomic claim
    def start(self, investigation_id: int, workspace_path: str,
              sandbox_id: str | None = None) -> None: ...
    def complete(self, investigation_id: int, github_url: str | None = None) -> None: ...
    def fail(self, investigation_id: int, error: str) -> None: ...
    def fail_paused(self, investigation_id: int, error: str) -> bool: ... # paused → failed (atomic)
    def cancel(self, investigation_id: int) -> bool: ...
    def pause(self, investigation_id: int, reason: str) -> None: ...    # running → paused
    def resume(self, investigation_id: int) -> None: ...                # paused|failed → running
    def review(self, investigation_id: int) -> bool: ...                # running → review
    def accept(self, investigation_id: int) -> bool: ...                # review → complete
    def continue_investigation(self, investigation_id: int,
                               feedback: str = "") -> int | None: ...  # review|complete → new queued

    # Queries
    def get(self, investigation_id: int) -> Investigation | None: ...
    def get_by_chat(self, chat_id: str, limit: int = 10) -> list[Investigation]: ...
    def get_recent(self, limit: int = 10) -> list[Investigation]: ...
    def get_running(self) -> list[Investigation]: ...
    def get_queued(self) -> list[Investigation]: ...
    def queue_position(self, investigation_id: int) -> int: ...  # 0-based, -1 if not queued
    def find_by_repo(self, repo: str, status: str | None = None) -> list[Investigation]: ...

    # Display
    def format_status(self) -> str: ...  # Telegram-formatted

    # Demo
    def set_demo_source(self, investigation_id: int, demo_name: str, demo_path: str) -> None: ...
    def get_demo_source(self, investigation_id: int) -> tuple[str, str] | None: ...
```

### Database Schema

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

-- Indexes
CREATE INDEX idx_inv_status ON investigations(status);
CREATE INDEX idx_inv_chat ON investigations(chat_id);
```

**Concurrency**: WAL mode, `BEGIN IMMEDIATE` for `next_ready()` to prevent double-dispatch.

---

## 3. Dispatcher (`dispatcher.py`)

### Purpose

The dispatcher is the server's main loop. It polls the queue, provisions workspaces, launches agents in tmux, monitors progress, sends Telegram updates, and detects completion/timeout.

### DispatcherConfig

```python
@dataclass
class DispatcherConfig:
    base_dir: Path           # ~/.voronoi (default)
    max_concurrent: int      # 2 — max simultaneous investigations
    max_agents: int          # 4 — max agents per investigation
    agent_command: str       # "copilot" (default)
    agent_flags: str         # "--allow-all" (default)
    orchestrator_model: str  # "" — use default
    worker_model: str        # "" — use default
    progress_interval: int   # 30 seconds between progress checks
    timeout_hours: int       # 48 — max investigation runtime
    max_retries: int         # 2 — retry failed launches
    stall_minutes: int       # 45 — minutes without progress before warning
    pause_timeout_hours: int # 24 — auto-fail paused investigations after this
    context_advisory_hours: int   # 6 — "prioritize convergence" directive
    context_warning_hours: int    # 10 — "delegate remaining work" + force compact
    context_critical_hours: int   # 14 — force context restart
    compact_interval_hours: int   # 6 — workspace state compaction interval
    max_context_restarts: int     # 2 — max proactive context refreshes
```

### Copilot CLI Flags

The dispatcher injects several Copilot CLI flags at launch time:

| Flag | Where | Purpose |
|------|-------|---------|
| `--effort <level>` | Orchestrator + workers (via `.swarm-config.json`) | Reasoning effort scaled by rigor: adaptive→`high`, scientific→`high`, experimental→`xhigh` |
| `--share <path>` | Orchestrator + workers | Saves clean markdown session transcript to `.swarm/session.md` for audit trails |
| `--deny-tool` | Workers only (via `spawn-agent.sh` role permissions) | Read-only roles (scout, critic, statistician, methodologist) get `--deny-tool=write` |

Both orchestrator and worker tmux launches also propagate Copilot CLI auth/state environment needed for durable restarts: `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, `COPILOT_HOME`, and `GH_HOST`. This ensures a resumed agent uses the same stored Copilot state directory and GitHub host selection as the parent server process, rather than falling back to a fresh login prompt.

Server runtime also reserves `~/.voronoi/tmp` as the shared temp root. `voronoi server start` exports `TMPDIR`, `TMP`, and `TEMP` to that directory, and `_launch_in_tmux()` relays the same values into orchestrator sessions so worker-side tests and scratch files stay under server state instead of falling back to the system `/tmp`.

**Effort-by-rigor mapping** (applied in `_launch_in_tmux()` and `spawn-agent.sh`):

| Rigor | `--effort` | Rationale |
|-------|-----------|----------|
| (none / unknown) | `medium` | Routine build tasks |
| `adaptive` | `high` | Science discovery needs deeper reasoning |
| `scientific` | `high` | Full science protocol |
| `experimental` | `xhigh` | Maximum depth for novel discovery |

**Role permission profiles** (configured in `.swarm-config.json`):

| Role | Permissions |
|------|------------|
| `scout` | `--allow-all --deny-tool=write` |
| `review_critic` | `--allow-all --deny-tool=write` |
| `review_stats` | `--allow-all --deny-tool=write` |
| `review_method` | `--allow-all --deny-tool=write` |
| All others | `--allow-all` (default) |

### RunningInvestigation

Tracks state for a running investigation:

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
    task_snapshot: dict       # Last known bd task state
    notified_findings: set    # Finding IDs already sent to user
    notified_paradigm_stress: bool
    phase: str                # Current phase (scouting, investigating, etc.)
    improvement_rounds: int   # Evaluator improvement cycles
    eval_score: float         # Latest evaluator score
    retry_count: int
    stall_warned: bool
    context_restarts: int         # Proactive context refreshes (separate from retry_count)
    status_message_id: int | None  # Telegram message ID for edit-in-place
    pending_events: list[dict]    # Events accumulated while orchestrator is parked
    orchestrator_parked: bool     # True when orchestrator exited with active workers
    last_parked_digest_at: float  # Throttle digests to 5min while parked
```

### InvestigationDispatcher API

```python
class InvestigationDispatcher:
    def __init__(self, config: DispatcherConfig,
                 send_message: Callable,
                 send_document: Callable | None = None,
                 edit_message: Callable | None = None): ...

    @property
    def queue(self) -> InvestigationQueue: ...       # Lazy init
    @property
    def workspace_mgr(self) -> WorkspaceManager: ... # Lazy init

    # Core loop
    def dispatch_next(self) -> None: ...    # Launch queued, recover running
    def poll_progress(self) -> None: ...    # Monitor, send updates, detect completion
```

### Dispatch Lifecycle

1. `dispatch_next()` calls `queue.next_ready(max_concurrent)`
2. If investigation claimed → provision workspace via `workspace_mgr`
3. Copy demo files if `demo_source` set
4. Build orchestrator prompt via `prompt.py`
5. Verify Copilot auth (`_ensure_copilot_auth()`)
6. Launch in tmux: `tmux new-session -d -s {session} "cd {workspace} && {agent_command} {flags} --effort {level} --share .swarm/session.md -p prompt.txt ; exit"`, injecting auth/state environment into the tmux session before `send-keys`
7. Add to `_running` dict

### Progress Polling

1. `poll_progress()` runs every `progress_interval` seconds (default 30s)
2. Checks for abort signals (`_check_abort_signal()` reads `.swarm/abort-signal`)
3. Checks for pending human gates (`check_human_gates()` — Scientific+ only)
4. For each running investigation:
   - Skip if not due for update (< progress_interval since last)
   - Refresh eval score from `.swarm/eval-score.json`
   - Check if tmux session still alive
   - Get events via `_check_progress()`:
     - `_diff_tasks()` — compares task snapshot for new/started/completed tasks
     - `_check_findings()` — detects new FINDING tasks and SERENDIPITY notes (deduplicates via notified set)
     - `_check_design_invalid()` — detects DESIGN_INVALID flags in open tasks
     - `_check_sentinel()` — experiment contract validation (see SCIENCE.md §10)
     - `_detect_phase()` — classifies phase from workspace file artifacts; detects rigor escalation
     - `_check_paradigm_stress()` — detects contradictions (Scientific+ only)
     - `_check_heartbeat_stalls()` — detects agent inactivity via heartbeat files
     - `_check_event_log()` — reads `.swarm/events.jsonl` for failures, token spend, serendipity
   - **If orchestrator is parked**: accumulate events in `pending_events` for the resume prompt. Throttle Telegram digest edits to every 5 minutes (milestones still sent immediately).
   - **If orchestrator is active**: send digest via `build_digest()` normally.
   - Check for timeout, stall, completion
   - **If orchestrator is dead and workers active**: check `_needs_orchestrator()` — wake on DESIGN_INVALID or all workers done. Otherwise defer.
   - Handle dead agents: try restart or mark failed

### Orchestrator Parking & Wake

When the orchestrator exits cleanly with `active_workers` in the checkpoint, the dispatcher enters **parked mode** for that investigation:

1. Sets `orchestrator_parked = True`
2. Accumulates events in `pending_events` (task completions, findings, serendipity, phase changes)
3. Throttles Telegram digests to every 5 minutes (from 30 seconds)
4. Each poll cycle, calls `_needs_orchestrator()` to check wake conditions
5. On wake: builds resume prompt with accumulated `pending_events`, relaunches orchestrator
6. `pending_events` are drained into the resume prompt and cleared

Wake conditions (`_needs_orchestrator()`):
- All active workers finished (normal wake)
- DESIGN_INVALID detected in open task (urgent — immediate wake)
- Workers no longer alive (process died)

Findings and serendipity are accumulated and delivered in the resume prompt — they do NOT trigger immediate wake because they are not time-sensitive. The orchestrator evaluates them with fresh context.

### Human Review Gates (Scientific+ Rigor)

At Scientific and Experimental rigor, the orchestrator can pause for human approval by writing `.swarm/human-gate.json` with `status: "pending"`. The dispatcher detects this via `check_human_gates()`, **kills the tmux session** to truly pause execution, and sends a Telegram message with `/approve <id>` or `/revise <id> <feedback>` options. On approval, the dispatcher **restarts the agent** with a resume prompt. A gate-pending dead session is NEVER routed through crash-retry logic. Methods:

- `approve_human_gate(investigation_id, feedback)` — approves the gate and restarts the agent
- `revise_human_gate(investigation_id, feedback)` — requests revision with feedback and restarts the agent

### Structured Event Log

The dispatcher reads `.swarm/events.jsonl` (written by workers and orchestrator) via `_check_event_log()` for:
- **Failure counts**: Alerts when multiple tool calls or tests are failing
- **Token accumulation**: Logs when token spend exceeds 50K since last poll
- **Serendipity events**: Surfaces unexpected observations as milestone notifications to the human
- **Stall detection**: Combined with heartbeat checks for comprehensive activity monitoring

See `src/voronoi/server/events.py` for the `SwarmEvent` dataclass and convenience loggers (`log_serendipity()`, `log_finding()`, etc.).

### Event-Driven Digests (Two-Tier Delivery)

The dispatcher batches events since last update into a single `build_digest()` call, which returns `(text, message_type)`. The message_type determines delivery:

| Type | Delivery | Notification? | Triggers |
|------|----------|:---:|----------|
| `MSG_TYPE_STATUS` | Edit existing message | No | Task changes, progress |
| `MSG_TYPE_MILESTONE` | New message | Yes | Findings, design_invalid, serendipity, rigor escalation |

The dispatcher tracks `status_message_id` per investigation. Status updates silently edit the last status message. Milestones always send a new message (clearing the tracked ID so the next status creates a fresh one). When `edit_message` callback is not available (e.g., non-Telegram frontends), all messages are sent as new messages.

Narrative content is synthesized from workspace artifacts (experiments.tsv, success-criteria.json, belief-map.json) via `_synthesize_narrative()`, with VOICE variant fallback when artifacts are thin.

### Phase Detection

Phase inferred from workspace artifacts:

| Phase | Detection |
|-------|-----------|
| `complete` | `deliverable.md` exists |
| `converging` | `convergence.json` exists |
| `synthesizing` | `belief-map.json` exists |
| `reviewing` | Review tasks in progress |
| `investigating` | Experiment tasks in progress |
| `planning` | Tasks created but none started |
| `scouting` | Scout tasks detected |
| `starting` | No tasks yet |

### Completion Detection

| Signal | Meaning |
|--------|---------|
| tmux session dies | Agent finished (or crashed) — try restart if retries remain |
| `deliverable.md` exists | Adaptive-rigor (not escalated) completion |
| `deliverable.md` + `convergence.json` exist | Escalated-adaptive / scientific / experimental completion (convergence status is **case-insensitive**) |
| DESIGN_INVALID open | **Hard gate** — blocks completion even if deliverable exists |
| Timeout reached | Forced completion with exhaustion marker |

The completion gate uses the **effective rigor** (`_effective_rigor()`): if an adaptive investigation has escalated (checkpoint rigor ≠ adaptive), the escalated level is used for gate decisions. This prevents adaptive-rigor investigations that escalated to scientific from completing without convergence validation.

The convergence status check (`_convergence_status_ok`) accepts `converged`, `CONVERGED`, or any case variant for all valid statuses (`converged`, `exhausted`, `diminishing_returns`, `negative_result`). It also checks the legacy `converged: true` boolean field.

### Criteria Synchronization

The dispatcher syncs `criteria_status` from the orchestrator checkpoint into `success-criteria.json` on each poll cycle via `_sync_criteria_from_checkpoint()`. This sync is promotion-only: checkpoint entries can mark a criterion as met, but they do not clear a criterion that is already marked met in the canonical file. That prevents stale or partial checkpoints from regressing canonical criteria state when the orchestrator updates its checkpoint but does not write back the full criteria file. The state digest generator also cross-references both sources, preferring whichever has more "met" values.

### Completion Handling

1. **Hard gate**: If any DESIGN_INVALID tasks are open, completion is blocked
2. Clean up tmux sessions — reads `.swarm-config.json` for the actual session name, enumerates live tmux sessions and kills any whose working directory is under the swarm directory
3. **Negative result detection**: If convergence.json status is `negative_result`, send `format_negative_result()` instead of the standard teaser. This presents valid null findings as legitimate science rather than failure.
4. On success: generate teaser via `ReportGenerator.build_teaser()`, generate PDF via `build_pdf()`, send teaser + document to Telegram
5. On failure: extract log tail, send failure message via `format_failure()`
6. **Federated knowledge sync**: Sync findings to `~/.voronoi/knowledge.db` for cross-investigation search
7. Try GitHub publish if `gh` CLI available
8. Clean up agent worktrees — prune git worktrees, remove worktree directories, remove the `-swarm/` directory
9. Remove `.swarm/.tmux-env` secrets file from workspace
10. Clean `~/.voronoi/tmp` if no other investigations are running

### Agent Restart

When tmux session dies:
1. **Classify the exit first** — check if agent logged out cleanly vs crashed unexpectedly
2. If exit was clean but incomplete, check if a human gate is pending — if so, do NOT retry (the agent is waiting for approval)
3. **Check for auth failure** — normalize the log tail first (strip ANSI/TUI control sequences, collapse punctuation noise), then inspect it for auth-related patterns ("authenticate", "gh auth login", "COPILOT_GITHUB_TOKEN", etc.). If matched, transition to `paused` state instead of burning a retry. Send Telegram notification with `/resume` instructions.
4. **Check for orphaned workers** — in addition to checking tmux windows, `_has_active_workers()` uses `pgrep` to detect orphaned copilot processes whose command line references the workspace path. This prevents premature restart when workers outlive their tmux session.
5. Check retry limit (`max_retries`, default 2)
5. Send contextual notification: "exited early" for clean exits, "crashed" only for unexpected exits
6. Validate orchestrator prompt still exists
7. Build **resume prompt** that includes: the original question, essential protocol references, checkpoint state, success criteria status, task summary, and clear next actions
8. Rotate log file (preserve previous attempt's logs)
9. Re-launch in tmux with the resume prompt
10. On auth failure during launch: transition to `paused` (not exhausting retries)

### Context Restart (Proactive)

When the orchestrator becomes context-exhausted, directive files are unreliable because the agent may be stuck in a polling sleep and never read them. At `context_critical` level (time-based ≥14h or self-reported ≤15% window remaining), the dispatcher **force-restarts** the orchestrator:

1. Compact workspace state (`compact_workspace_state()`)
2. Kill the tmux session
3. Build a fresh resume prompt from checkpoint + state digest
4. Relaunch in tmux with clean context window
5. Send Telegram notification

Time-based restarts are **evidence-gated**: if the orchestrator's context snapshot shows >30% headroom, the force-restart is skipped (the agent is healthy enough to read the directive itself). Token-based restarts (≤15% self-reported) always trigger regardless of elapsed time. This prevents killing a healthy agent that happens to be running for a long time.

This does NOT count against `max_retries` — it uses a separate `context_restarts` counter (limit: `max_context_restarts`, default 2). At `context_warning` level, the dispatcher force-compacts the workspace immediately (instead of waiting for the periodic 6h interval) to help the agent if it does read the directive.

The resume prompt for context refreshes is distinct from crash restarts: it explicitly tells the agent the previous session was healthy, nothing failed, and to continue from the checkpoint without re-validating completed work.

### Continuation Dispatch

When a continuation investigation is dequeued (detected by `inv.parent_id is not None` and `inv.workspace_path` existing on disk), the dispatcher skips fresh provisioning and instead:
1. Reuses the existing workspace directory
2. Calls `prepare_continuation()` to archive `.swarm/` state, tag the git boundary, clear stale completion/event artifacts from active `.swarm/`, prune worktrees, and write immutability invariants
3. Refreshes templates via `_voronoi_init()`
4. Builds a warm-start prompt via `build_warm_start_context()` — injecting claim ledger summary, PI feedback from `inv.pi_feedback`, immutable artifact paths, and artifact manifest
5. Passes `prior_context` to `build_orchestrator_prompt()` so the orchestrator sees Round N context

If the workspace directory is missing (e.g. user cleaned up), the dispatcher falls back to fresh provisioning with a warning log.

### Investigation Resume

The dispatcher exposes `resume_investigation(investigation_id)` for resuming `paused` or `failed` investigations. This:
1. Validates the investigation exists and is in `paused` or `failed` status
2. Validates the workspace still exists with an orchestrator prompt
3. Transitions the queue status back to `running` via `queue.resume()`
4. Resets `retry_count` to 0
5. Builds a fresh resume prompt via `_build_resume_prompt()`
6. Launches in tmux
7. Adds back to `self.running` for monitoring

Paused investigations auto-fail after `pause_timeout_hours` (default 24h).

### Abort Handling

`_handle_abort()` kills all running investigations:
- Reads `.swarm/abort-signal` file written by `handle_abort()` in router
- Kills tmux sessions
- Marks investigations as cancelled in queue
- Clears internal tracking

### Recovery

On dispatcher restart, `_recover_running()` scans for investigations in `running` status:
- Restores `task_snapshot` from Beads (`bd list --json`) so progress reporting is accurate
- If tmux session alive → re-adopt for monitoring
- If tmux dead + deliverable exists → mark complete
- If tmux dead + no deliverable → try restart OR mark failed

---

## 4. Prompt Builder (`prompt.py`)

### Purpose

Single source of truth for all orchestrator prompts. Both CLI and Telegram paths produce identical prompts through this module.

### Core Function

```python
def build_orchestrator_prompt(
    question: str,
    mode: str,              # discover | prove
    rigor: str,             # adaptive | scientific | experimental
    workspace_path: str = "",
    codename: str = "",
    prompt_path: str = "PROMPT.md",
    output_dir: str = "",
    max_agents: int = 4,
    safe: bool = False,
    prior_context: dict | None = None,  # warm-start data from prior runs
) -> str
```

### Prompt Structure (Section Order Matters)

The prompt is intentionally compact (~190 lines) to preserve context budget for the orchestrator's OODA cycles. Procedural details are in skills (loaded on demand), not inline.

| # | Section | Content |
|---|---------|---------|
| 1 | Identity | Role protocol → `.github/agents/swarm-orchestrator.agent.md` |
| 2 | Worker Dispatch | **MANDATORY** — References `worker-lifecycle` skill, forbids built-in agent tools |
| 3 | Mission | Mode/rigor, workspace, project brief path |
| 4 | Personality | Excitement, brain metaphors, factual focus |
| 5 | Science | Mode + rigor-aware sections (human gates for scientific+) |
| 6 | Creative Freedom | DISCOVER mode: dynamic roles, serendipity, adaptive rigor escalation |
| 7 | Investigation invariants | `.swarm/invariants.json` enforcement |
| 8 | REVISE task support | References `revise-calibration` skill |
| 9 | OODA Protocol | Compact — references role file, dispatcher directives |
| 10 | Success criteria | `.swarm/success-criteria.json` format |
| 11 | Phase gates | Hard gates (no paper while DESIGN_INVALID exists) |
| 12 | LLM calls & Anti-simulation | References `copilot-cli-usage` skill, hard anti-simulation gate |
| 13 | Delegation rules | Compact: no inline experiments, no inline code, delegate manuscript to Scribe |
| 14 | Experiment contract | Compact Sentinel description |
| 15 | Rules | Concurrency, artifact contracts, convergence gate |
| 16 | Eval score | `.swarm/eval-score.json` output format |
| 17 | Warm-Start Brief | (Only for `prior_context != None`) |

### Skills Referenced by the Orchestrator Prompt

| Skill | When read | Purpose |
|-------|-----------|---------|
| `worker-lifecycle` | Before dispatching any worker | Complete spawn → monitor → merge → cleanup recipe |
| `copilot-cli-usage` | When making programmatic LLM calls | Correct Copilot CLI invocation |
| `revise-calibration` | When creating REVISE tasks | Calibration iteration protocol |

### Key Design Principle

The prompt **references** `.github/agents/*.agent.md` files in the target workspace. It tells the orchestrator: "Read this file NOW — it contains your complete role definition." Role definitions live canonically in `src/voronoi/data/agents/` and are copied to `.github/agents/` in investigation workspaces. They are NEVER duplicated in Python code.

### Worker Prompt Skill Injection

`build_worker_prompt()` uses `SKILL_MAP` to inject task-type-specific skill references:

| Task Type | Skills Injected |
|-----------|----------------|
| `investigation`, `experiment` | `investigation-protocol`, `evidence-system`, `context-management` |
| `scribe` | `compilation-protocol`, `figure-generation` |
| `paper`, `compilation` | `figure-generation`, `compilation-protocol` |
| `scout` | `deep-research` |
| `exploration` | `deep-research`, `context-management` |

Skills are referenced as paths (e.g., `.github/skills/deep-research/SKILL.md`) in the worker prompt. The agent reads them at task start.

### Scribe Format Enforcement

`build_worker_prompt()` injects an "Output Format — MANDATORY" section for `task_type="scribe"` that overrides any contradictory briefing with:
- Write LaTeX (`paper.tex`), not Markdown
- Compile to `paper.pdf` using the compilation-protocol skill
- Place paper in the output directory from the project brief
- Write `.swarm/deliverable.md` as a SHORT summary (convergence signal), not the paper
- Copy `paper.pdf` to `.swarm/report.pdf` for Telegram delivery

This prevents the orchestrator's LLM-generated briefing from accidentally telling the Scribe to write Markdown.

---

## 5. Workspace Manager (`workspace.py`)

### Purpose

Provisions investigation workspaces with auto-cloning, git worktrees, and framework scaffolding.

### Directory Layout

```
~/.voronoi/
├── objects/                    # Bare git repos (shared object store)
│   └── owner--repo.git        # --reference for deduplication
├── tmp/                        # Dedicated temp root for bridge + agent subprocesses
└── active/                    # Active investigation workspaces
    └── inv-{id}-{slug}/       # One per investigation
        ├── .github/           # Agent roles, skills, instructions, hooks
        ├── .swarm/            # Orchestrator state
        ├── scripts/           # Infrastructure scripts
        ├── data/raw/          # Experimental data
        └── PROMPT.md          # Investigation brief
```

### WorkspaceInfo

```python
@dataclass
class WorkspaceInfo:
    investigation_id: int
    path: str
    workspace_type: str    # "repo" | "lab"
    repo: str | None       # GitHub URL for repo-type
    slug: str
    created_at: float
    sandbox_id: str | None
```

### WorkspaceManager API

```python
class WorkspaceManager:
    def __init__(self, base_dir: str | Path): ...

    def provision_repo(self, investigation_id: int, repo: RepoRef,
                       slug: str) -> WorkspaceInfo: ...
    def provision_lab(self, investigation_id: int, slug: str,
                      question: str) -> WorkspaceInfo: ...
    def get_workspace_path(self, investigation_id: int, slug: str) -> Path | None: ...
    def cleanup(self, investigation_id: int, slug: str) -> bool: ...
    def list_active(self) -> list[str]: ...  # Excludes -swarm directories
```

### Provisioning Steps

**Repo-type** (`provision_repo`):
1. Clone with `--reference` to bare repo in `objects/` (deduplication)
2. Run `voronoi init` to scaffold `.github/`
3. Fallback: copy `.github/` files even if `voronoi init` fails

**Lab-type** (`provision_lab`):
1. Create fresh directory
2. Initialize git repo
3. Write `PROMPT.md` with user question
4. Run `voronoi init`
5. Initialize Beads

### Workspace Naming Convention

- Lab: `inv-{investigation_id}-{slug}/`
- Repo: `inv-{investigation_id}-{slug}/`
- Swarm worktree dir: `inv-{investigation_id}-{slug}-swarm/`

---

## 6. Sandbox Manager (`sandbox.py`)

### Purpose

Docker-based execution isolation per investigation. Optional — falls back to host if Docker unavailable.

### SandboxConfig

```python
@dataclass
class SandboxConfig:
    enabled: bool           # Whether to attempt Docker isolation
    image: str              # Docker image name
    cpus: int               # CPU limit
    memory: str             # Memory limit (e.g., "4g")
    timeout_hours: int      # Container timeout
    network: bool           # Network enabled (False → "--network none")
    fallback_to_host: bool  # Fall back if Docker unavailable
```

### SandboxInfo

```python
@dataclass
class SandboxInfo:
    container_id: str
    container_name: str
    workspace_path: str
    status: str
```

### SandboxManager API

```python
class SandboxManager:
    def __init__(self, config: SandboxConfig | None = None): ...
    def is_docker_available(self) -> bool: ...
    def start(self, investigation_id: int, workspace_path: str) -> SandboxInfo | None: ...
    def exec(self, container_name: str, command: list[str],
             timeout: int = 120) -> tuple[int, str]: ...
    def stop(self, investigation_id: int) -> bool: ...
    def is_running(self, investigation_id: int) -> bool: ...
```

### Standalone Function

```python
def exec_in_sandbox_or_host(workspace_path: str, command: list[str],
                            timeout: int = 120) -> tuple[int, str]
```

Reads `.sandbox-id` file in workspace; if present, executes in container; otherwise executes on host.

### Docker Container Contract

- One container per investigation
- Workspace mounted read-write at `/workspace`
- Resource limits: cpus, memory, timeout
- Optional network isolation
- Container named: `voronoi-inv-{investigation_id}`

---

## 7. Server Configuration (`runner.py`)

### ServerConfig

```python
class ServerConfig:
    def __init__(self, base_dir: str | None = None): ...

    # Server settings
    base_dir: Path                        # ~/.voronoi
    max_concurrent: int                   # 2
    max_agents_per_investigation: int     # 4
    agent_command: str                    # "copilot"
    agent_flags: str                      # "--allow-all"
    orchestrator_model: str               # ""
    worker_model: str                     # ""
    workspace_retention_days: int         # Cleanup threshold

    # GitHub settings
    github_lab_org: str                   # "voronoi-lab"
    github_visibility: str                # "private"
    github_auto_publish: bool             # True

    # Sandbox settings
    sandbox: SandboxConfig

    def save(self) -> None: ...  # Persist to config.json
```

### Config File Location

`~/.voronoi/config.json` — JSON with sections: `server`, `github`, `sandbox`.

### Environment Variable Overrides

| Env Var | Config Key |
|---------|-----------|
| `VORONOI_AGENT_COMMAND` | `agent_command` |
| `VORONOI_ORCHESTRATOR_MODEL` | `orchestrator_model` |
| `VORONOI_WORKER_MODEL` | `worker_model` |
| `VORONOI_MAX_CONCURRENT` | `max_concurrent` |

### Helper Functions

```python
def make_slug(text: str, max_len: int = 40) -> str
def create_investigation_from_text(text: str, chat_id: str,
                                   mode: str = "discover",
                                   rigor: str = "adaptive") -> Investigation
```

---

## 8. GitHub Publisher (`publisher.py`)

### Purpose

Publishes investigation results (workspace + findings) to GitHub repositories.

### GitHubPublisher API

```python
class GitHubPublisher:
    def __init__(self, lab_org: str = "voronoi-lab",
                 visibility: str = "private"): ...
    def is_gh_available(self) -> bool: ...
    def publish(self, workspace_path: str, repo_name: str,
                description: str = "") -> tuple[bool, str]: ...  # (success, url_or_error)
    def create_finding_issues(self, repo_name: str,
                              findings: list[dict]) -> list[str]: ...  # Issue URLs
```

Requires `gh` CLI installed and authenticated.

---

## 9. Repo URL Parser (`repo_url.py`)

### Purpose

Extracts GitHub repository references from free-text user messages.

### RepoRef

```python
@dataclass
class RepoRef:
    owner: str
    name: str

    @property
    def full_name(self) -> str: ...    # "owner/name"
    @property
    def clone_url(self) -> str: ...    # "https://github.com/owner/name.git"
    @property
    def slug(self) -> str: ...         # "owner--name"
```

### Functions

```python
def extract_repo_url(text: str) -> RepoRef | None
def strip_repo_url(text: str) -> str  # Returns question without repo URL
```

**Pattern priority**: explicit github.com URLs → `owner/repo` patterns → None.

**False positive filtering**: Skips patterns matching common words (and/or, w/o, etc.).
