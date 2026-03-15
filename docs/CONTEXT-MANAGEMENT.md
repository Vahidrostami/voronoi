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

## 8. Context Pressure Estimation

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
