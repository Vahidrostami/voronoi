# Context Management Specification

> Three-tier memory model, orchestrator checkpoint, targeted queries, code-assembled worker prompts.

**TL;DR**: LLM agents have finite context. Without management, a 10h investigation overflows the window by hour 6. Three mechanisms fix this: (1) checkpoint file written every OODA cycle (~300 tokens to restore state), (2) targeted `bd query` instead of `bd list --json` (10x reduction), (3) code-assembled worker prompts via `build_worker_prompt()` (15K tokens/dispatch removed from orchestrator). Result: ~128K cumulative vs ~800K without. Everything in `src/voronoi/server/prompt.py` and `src/voronoi/science/`.

## 1. The Problem

A 10-hour investigation with 50+ tasks, 30+ OODA cycles, and 30+ worker dispatches generates ~800K tokens of conversation history. Without management, the orchestrator loses early instructions (project brief, factorial design, success criteria) and starts making incoherent decisions.

## 2. Three Memory Tiers

```
┌─────────────────────────────────────────────────┐
│  Tier 1: Conversation Context (ephemeral)       │
│  The LLM's active working memory. ~200K window. │
│  Everything here is lost on restart.             │
├─────────────────────────────────────────────────┤
│  Tier 2: State Files (durable, per-workspace)   │
│  .swarm/orchestrator-checkpoint.json             │
│  .swarm/belief-map.json                          │
│  .swarm/success-criteria.json                    │
│  .swarm/experiments.tsv                          │
│  Survives restarts. Read at cycle start.         │
├─────────────────────────────────────────────────┤
│  Tier 3: Beads DB (durable, queryable)          │
│  All tasks, findings, notes, dependencies.       │
│  Survives everything. Queried, never dumped.     │
└─────────────────────────────────────────────────┘
```

## 3. Per-Agent Context Budget

| Agent | Startup | Per-Cycle | Total Session | Lifetime |
|-------|---------|-----------|---------------|----------|
| **Orchestrator** | ~17K tokens | ~2-4K tokens | Hours (30+ cycles) | 1 per investigation |
| **Worker** | ~15-25K tokens | N/A (single task) | ~30 min | 1 per task |
| **Scout** | ~10K tokens | N/A | ~15 min | 1 per investigation |
| **Reviewer** | ~10-15K tokens | N/A | ~20 min | 1 per finding |

### 3.1 Orchestrator Startup (~17K tokens)

| Component | Tokens |
|-----------|--------|
| System prompt from `prompt.py` | ~5K |
| `swarm-orchestrator.agent.md` (read on first instruction) | ~5K |
| PROMPT.md (project brief — read ONCE) | ~4K |
| CLAUDE.md + AGENTS.md (auto-loaded) | ~3K |

### 3.2 Orchestrator Per-Cycle (~2-4K tokens)

| Action | Tokens |
|--------|--------|
| Read checkpoint | ~300 |
| Read belief map | ~200 |
| Targeted `bd query` | ~500-2K |
| Reasoning + decisions | ~500 |
| Write worker briefings | ~200 per worker |
| Write checkpoint | ~200 |

### 3.3 Worker Startup (~15-25K tokens)

| Component | Tokens |
|-----------|--------|
| Role definition (loaded from file by `build_worker_prompt()`) | ~5-10K |
| Task briefing (from orchestrator) | ~200-500 |
| Project brief sections (only relevant parts) | ~1-3K |
| Strategic context | ~200 |
| Artifact contracts + git discipline | ~500 |

Workers are bounded: single task, verify loop (max 3-5 iterations), then done.

## 4. Orchestrator Checkpoint

**File**: `.swarm/orchestrator-checkpoint.json`
**Code**: `OrchestratorCheckpoint` in `src/voronoi/science/`

Written after every OODA cycle. Read at the start of the next cycle.

### 4.1 Fields

| Field | Purpose |
|-------|---------|
| `cycle` | OODA cycle counter |
| `phase` | Current investigation phase |
| `hypotheses_summary` | Compact string: `"H1:confirmed, H2:testing"` |
| `total_tasks` / `closed_tasks` | Progress count |
| `active_workers` | Branch names of running agents |
| `recent_events` | Rolling window of 5 |
| `recent_decisions` | Rolling window of 5 with rationale |
| `dead_ends` | Approaches to never re-explore |
| `next_actions` | The orchestrator's TODO list |
| `criteria_status` | Map of success criterion → met/unmet |
| `eval_score` | Latest evaluator quality score |
| `tokens_this_cycle` | Tokens consumed in the current OODA cycle |
| `tokens_cumulative` | Total tokens consumed across all cycles |
| `context_window_remaining_pct` | Estimated remaining context window (0.0–1.0) |

### 4.2 API

```python
from voronoi.science import (
    OrchestratorCheckpoint, load_checkpoint, save_checkpoint,
    format_checkpoint_for_prompt,
)

# Load
cp = load_checkpoint(workspace_path)

# Save (after each OODA cycle)
cp.cycle += 1
cp.recent_events.append("Scenario 5 complete: MBRS=0.71")
save_checkpoint(workspace_path, cp)  # auto-trims rolling windows

# Inject into prompt (~300 tokens)
text = format_checkpoint_for_prompt(cp)
```

### 4.3 Recovery

On restart, the orchestrator reads the checkpoint and immediately knows:
- Where it is (phase, cycle count)
- What happened (recent events)
- What to do next (next_actions)
- What to avoid (dead_ends)

Without checkpoint: orchestrator re-reads all history → wastes context → may re-explore dead ends.

## 5. Targeted Beads Queries

### 5.1 Problem

`bd list --json` returns ALL tasks. With 50+ tasks carrying notes, this is 10-25K tokens per call.

### 5.2 Solution

Use `bd query` with filters:

```bash
bd query "status!=closed AND updated>30m" --json   # Only recent changes
bd query "title=FINDING AND status=closed" --json   # Only findings
bd query "notes=DESIGN_INVALID AND status!=closed"  # Only problems
bd ready --json                                      # Only actionable work
```

### 5.3 Impact

Per-cycle Beads context: ~10-25K → ~500-2K tokens.

## 6. Code-Assembled Worker Prompts

### 6.1 Problem

The orchestrator was instructed to read role files (~10K each) and copy them into worker prompts. Over 30 dispatches, this consumed ~450K tokens of orchestrator context for pure copy-paste.

### 6.2 Solution

`build_worker_prompt()` in `src/voronoi/server/prompt.py` reads role files from disk and assembles complete worker prompts. The orchestrator only writes a ~200 word briefing.

```python
from voronoi.server.prompt import build_worker_prompt

prompt = build_worker_prompt(
    task_type="investigation",
    task_id="bd-42",
    branch="agent-pilot",
    briefing="Run the pilot experiment on scenarios 1-2...",
    strategic_context="Tests whether encoding helps discovery...",
    produces="output/pilot_results.json",
    metric_contract="PRIMARY=MBRS, higher_is_better",
)
```

### 6.3 Task Type → Role Mapping

| Task type | Role file |
|-----------|-----------|
| `build` | `worker-agent.agent.md` |
| `scout` | `scout.agent.md` |
| `investigation` / `experiment` | `investigator.agent.md` |
| `exploration` / `comparison` | `explorer.agent.md` |
| `review_stats` | `statistician.agent.md` |
| `review_critic` | `critic.agent.md` |
| `review_method` | `methodologist.agent.md` |
| `theory` | `theorist.agent.md` |
| `synthesis` | `synthesizer.agent.md` |
| `evaluation` | `evaluator.agent.md` |
| `paper` / `compilation` | `worker-agent.agent.md` |

Skills are auto-selected by task type (e.g., `investigation` → investigation-protocol + evidence-system).

### 6.4 Impact

Per-dispatch cost: ~15-25K → ~200 tokens in orchestrator context.

## 7. Project Brief Read-Once Protocol

The orchestrator reads PROMPT.md once at startup. After that, it works from:
- Checkpoint (what we've done)
- Belief map (what we think)
- Targeted queries (what changed)

If a specific detail is needed, `grep` for it instead of re-reading the whole file.

## 8. Worker Self-Verification Protocol

Every worker runs a mandatory self-verification sequence before closing a task. This is injected into every worker prompt by `build_worker_prompt()`.

### Step 1: Test Loop (iterate until pass)

Run tests → if FAIL, fix and retry → repeat up to 3 times. If still failing after 3 attempts, report `VERIFY_EXHAUSTED` in Beads notes. Do NOT close the task.

### Step 2: Self-Review Checklist

1. All PRODUCES artifacts exist and are non-empty
2. Reported metrics match the actual data
3. No hardcoded test values or simulated data
4. All commits pushed to branch

### Step 3: Incremental Findings Commit

Write observations to Beads notes as they occur — don't rely on context memory. This prevents loss of intermediate observations if the agent's context fills up.

### Impact

The self-verification protocol catches errors at the source, reducing wasted Critic dispatch cycles. Workers that would previously declare "done" on broken code now self-correct or escalate explicitly.

## 9. Token Budget Tracking

The orchestrator checkpoint includes token budget fields:

| Field | Purpose |
|-------|---------|
| `tokens_this_cycle` | Tokens consumed in the current OODA cycle |
| `tokens_cumulative` | Total tokens consumed across all cycles |
| `context_window_remaining_pct` | Estimated remaining context window (0.0–1.0) |

When `context_window_remaining_pct` drops below 20%, the orchestrator should:
1. Force checkpoint write
2. Switch to more aggressive targeted Beads queries
3. Avoid re-reading large files

This is now **enforced structurally** by the dispatcher via context pressure directives (see §11).

## 10. Structured Event Log

**File**: `.swarm/events.jsonl`
**Code**: `src/voronoi/server/events.py`

Workers and the orchestrator append structured events for real-time observability:

```jsonl
{"ts":1710500000,"agent":"investigator","task_id":"bd-42","event":"tool_call","status":"pass","detail":"pytest: 12 passed","tokens_used":1240}
{"ts":1710500010,"agent":"investigator","task_id":"bd-42","event":"finding_committed","status":"ok","detail":"bd-43: effect d=0.82","tokens_used":0}
```

The dispatcher reads these events during progress polling for:
- **Stall detection**: No events for 5+ min = potentially stuck agent
- **Token tracking**: Cumulative token spend across the investigation
- **Failure monitoring**: Count failures for alerting

Convenience functions: `log_tool_call()`, `log_finding()`, `log_test_result()`, `log_verify_step()`.

## 11. Context Pressure & Dispatcher Directives

**Code**: `src/voronoi/server/dispatcher.py` — `_check_context_pressure()`, `_write_directive()`

The dispatcher monitors session age and self-reported context pressure. When thresholds are crossed, it writes `.swarm/dispatcher-directive.json` for the orchestrator to poll.

### Time-Based Directives

| Hours Elapsed | Directive | Action |
|---|---|---|
| `context_advisory_hours` (default 12) | `context_advisory` | Prioritize convergence |
| `context_warning_hours` (default 20) | `context_warning` | Delegate ALL remaining work to fresh agents |
| `context_critical_hours` (default 28) | `context_critical` | Write checkpoint and dispatch Scribe NOW |

### Self-Reported Context Pressure

If the orchestrator writes `context_window_remaining_pct` in the checkpoint:
- ≤ 30%: dispatcher sends `context_warning`
- ≤ 15%: dispatcher sends `context_critical`

Self-reported pressure can trigger directives earlier than the time thresholds.

### `/compact` — Native Context Compression

At `context_warning` and `context_critical` levels, the dispatcher directive instructs the orchestrator to run Copilot CLI's `/compact` command. This is **native LLM-level context compression** — the agent's conversation history is summarized in-place, recovering 60-70% of context budget without restarting.

**Why this matters:** Voronoi's workspace compaction (`compact.py`) compresses *state files* agents read. `/compact` compresses the agent's *conversation memory* — the accumulated tool calls, reasoning, and outputs from 30+ OODA cycles. These are complementary:

| Mechanism | What it compresses | When |
|-----------|-------------------|------|
| `compact.py` (dispatcher) | `.swarm/` files (experiments.tsv, events.jsonl) | Every `compact_interval_hours` |
| `/compact` (agent-side) | Agent's conversation history (context window) | On `context_warning` or `context_critical` directive |

**Checkpoint + file state survives `/compact`** because they're on disk, not in conversation context. The agent reads checkpoint at each OODA cycle start, so compacted conversation history doesn't lose critical state.

**Directive format** (written to `.swarm/dispatcher-directive.json`):
```json
{"directive": "context_warning",
 "message": "10h elapsed. Run /compact NOW, then delegate remaining work to fresh agents.",
 "hours_elapsed": 10.2}
```

The orchestrator reads this directive every OODA cycle and executes `/compact` before continuing.

The full protocol is documented in the `context-management` skill (`src/voronoi/data/skills/context-management/SKILL.md`), which is injected into long-running worker prompts via `SKILL_MAP`.

### Configuration

All thresholds are configurable via `~/.voronoi/config.json` or environment variables:

```json
{"server": {"context_advisory_hours": 12, "context_warning_hours": 20,
            "context_critical_hours": 28, "compact_interval_hours": 6}}
```

Environment: `VORONOI_CONTEXT_ADVISORY_HOURS`, `VORONOI_CONTEXT_WARNING_HOURS`, `VORONOI_CONTEXT_CRITICAL_HOURS`, `VORONOI_COMPACT_INTERVAL_HOURS`.

## 12. Workspace State Compaction

**Code**: `src/voronoi/server/compact.py`

Called periodically by the dispatcher (default every 6 hours). Prevents workspace state files from growing unboundedly in long investigations.

### What Gets Compacted

| File | Action |
|---|---|
| `.swarm/experiments.tsv` | Keep last 20 rows, archive rest to `experiments.archive.tsv` |
| `.swarm/events.jsonl` | Keep last 2 hours, archive rest to `events.archive.jsonl` |
| `.swarm/state-digest.md` | Written fresh — compact summary of all state for OODA reads |

### State Digest

The `state-digest.md` is a compact summary (~50 lines) containing:
- Success criteria status
- Experiment counts (keep/crash/discard)
- Active agent branches
- Checkpoint summary with dead ends

The orchestrator reads this instead of querying each file individually.

## 13. Brief-Digest Protocol

At startup, after reading `PROMPT.md` once, the orchestrator extracts critical constraints into `.swarm/brief-digest.md`:
- Success criteria (verbatim)
- Experimental design summary
- Hard constraints (α thresholds, minimum effect sizes)
- Mandated entry point

This digest is re-read at each OODA cycle start, preventing design violations when context degrades. Unlike the full PROMPT.md (~8K+ tokens), the digest is ~50 lines.

## 14. Restart Recovery — Minimal Resume Prompt

**Code**: `src/voronoi/server/dispatcher.py` — `_build_resume_prompt()`

When the agent crashes and is restarted, the dispatcher writes a **new** minimal prompt (`orchestrator-prompt-resume.txt`) instead of appending to the original:

| Old approach | New approach |
|---|---|
| Append resume section to original prompt | Write fresh ~100 line resume file |
| Original grows with each restart | Original untouched |
| Agent re-reads role file + PROMPT.md | Agent works from checkpoint + digest |

The resume prompt contains:
1. Identity + mode/rigor (10 lines)
2. Checkpoint summary inline
3. State digest inline (if available)
4. Success criteria status
5. Remaining tasks
6. Exact next actions

## 15. Stall Detection

The dispatcher detects stalled investigations using **multiple signals** (not just `bd list --json`):

1. `.swarm/orchestrator-checkpoint.json` — cycle > 0 or total_tasks > 0
2. `.swarm/experiments.tsv` — data rows exist
3. `.swarm/events.jsonl` — non-empty
4. `git branch --list agent-*` — worker branches exist
5. `task_snapshot` — fallback from `bd list --json`

If ALL signals are absent after `stall_minutes`, the stall warning fires. This eliminates false alarms from `bd` not being on the dispatcher's PATH.

## 16. Context Pressure Estimation

For a 10-hour investigation pipeline:

| Phase | Cycles | Context/Cycle | Cumulative |
|-------|--------|---------------|------------|
| Startup + scout + planning | 5 | ~5K (more reading) | ~42K |
| Pilot (2 scenarios) | 5 | ~3K | ~57K |
| Full experiment (12 scenarios) | 12 | ~3K | ~93K |
| Review gates | 5 | ~3K | ~108K |
| Synthesis + paper | 5 | ~4K | ~128K |
| **Total** | **32** | | **~128K** |

Fits within a 200K context window with headroom. Compare to the old approach (~800K+ which overflows any current model).

## 9. Failure Modes Without Context Management

| Hour | What goes wrong |
|------|----------------|
| 6 | Orchestrator forgets factorial design → dispatches wrong conditions |
| 8 | Orchestrator forgets phase gates → dispatches paper before experiments finish |
| 10 | Orchestrator forgets success criteria → declares convergence prematurely |
| Restart | No memory of decisions → re-explores dead ends |
