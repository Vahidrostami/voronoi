# Architecture Specification

> System-level architecture, layers, data flow, deployment topology.

**TL;DR**: 4 layers (Entry → Gateway → Server → Execution) + Science layer. Agents communicate via git + Beads + `.swarm/` files only. Orchestrator never enters worktrees. State externalized to files. Zero runtime deps for core. CLI and Telegram both use `prompt.py` as single prompt source.

## 1. System Overview

Voronoi is a **science-first multi-agent orchestration system**. The user types one prompt; the system classifies intent, selects rigor level, decomposes work, dispatches parallel agents, enforces review gates, and delivers a report or scientific manuscript.

Science is a superset of engineering — the system is designed for science and engineering works by skipping the science-specific gates.

### Design Principles

| Principle | Implication |
|-----------|------------|
| Science-first | Engineering = science with gates off. Zero overhead for build-only tasks. |
| Single prompt builder | CLI and Telegram produce identical orchestrator behavior via `prompt.py`. |
| `.github/` as source of truth | Agent roles live in files Copilot auto-discovers — never duplicated in Python code. |
| Prompt references, not duplicates | Orchestrator is told "read the file" — roles stay in sync automatically. |
| Two science modes | DISCOVER (adaptive rigor, creative exploration) and PROVE (full gates, structured validation). |
| Adaptive rigor | DISCOVER starts light and escalates when hypotheses crystallize. PROVE starts at full scientific rigor. |
| OODA over linear pipeline | Investigations are iterative — hypothesis revision needs loops, not waterfalls. |
| Simplicity criterion | All else equal, simpler is better. Small improvement + big complexity = reject. |

## 2. Layer Architecture

The system is organized into four layers, each with clear responsibilities and boundaries.

```
┌─────────────────────────────────────────────────────┐
│                    Entry Points                      │
│         Telegram Bot  ·  CLI  ·  (future: API)      │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                   Gateway Layer                      │
│   intent.py · router.py · config.py · memory.py     │
│   knowledge.py · literature.py · progress.py        │
│   report.py · codename.py · handoff.py              │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                   Server Layer                       │
│   queue.py · dispatcher.py · prompt.py              │
│   workspace.py · sandbox.py · runner.py             │
│   publisher.py · repo_url.py · events.py            │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Package Data (shipped with pip)          │
│   data/agents/ · data/skills/ · data/prompts/        │
│   data/scripts/ · data/templates/                    │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│               Execution Layer (via tmux)             │
│   Orchestrator (copilot instance reading             │
│     .github/agents/swarm-orchestrator.agent.md)      │
│   Workers (git worktree + tmux window each)          │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                   Science Layer                      │
│   science/ subpackage:                               │
│   _helpers · convergence · fabrication · gates        │
└─────────────────────────────────────────────────────┘
```

### Layer Contracts

| From → To | Contract |
|-----------|----------|
| Entry → Gateway | Free-text string + chat_id |
| Gateway → Server | `Investigation` object with mode (discover/prove), question, repo |
| Server → Execution | Orchestrator prompt (string) + workspace path + tmux session |
| Execution → Science | `.swarm/` files: belief-map.json, findings in Beads, raw data |
| Science → Execution | Convergence result, paradigm stress flags, gate pass/fail |

## 3. Entry Points

Two entry points, one execution path. Both converge at `prompt.py`.

### CLI Path

```
voronoi demo run X  →  cli.py  →  prompt.py  →  copilot -p prompt
voronoi init        →  cli.py  →  scaffold .github/ + scripts/
```

### Telegram Path

```
User message → telegram-bridge.py → CommandRouter.route() or .handle_free_text()
                     ↓
              intent.classify() → mode + rigor
                     ↓
              router → queue.py → dispatcher.py → workspace.py → prompt.py → tmux + copilot
                     ↓
              dispatcher.poll_progress() → build_digest() → Telegram (every 30s)
```

`telegram-bridge.py` runs as a standalone process with singleton lock. It hosts both the PTB (python-telegram-bot) handler and the dispatcher's background jobs (dispatch every 10s, progress every 30s).

### Capability Matrix

| Capability | CLI | Telegram |
|-----------|-----|----------|
| Demo files copied | YES — `cmd_demo()` | YES — `_copy_demo_files()` |
| `.github/` agents/skills | YES — `voronoi init` | YES — `_ensure_github_files()` fallback |
| Prompt builder | YES — `prompt.py` | YES — `prompt.py` (same function) |
| Progress updates | stdout | Telegram messages every 30s |
| Timeout detection | KeyboardInterrupt | Configurable (default 8h) |
| Completion signal | Agent exits | tmux dies OR deliverable.md + convergence.json |
| Queue management | N/A | SQLite queue with atomic claiming |
| Sandbox isolation | N/A | Docker optional, fallback to host |

## 4. Communication Model

Agents do NOT communicate through custom IPC. All inter-agent communication flows through:

| Channel | Purpose | Mechanism |
|---------|---------|-----------|
| **Git** | Code, data, artifacts | Branches + worktrees, merge via `merge-agent.sh` |
| **Beads (bd)** | Tasks, dependencies, findings | Dolt-backed DB, `bd create/update/close` |
| **`.swarm/` files** | Orchestrator state | JSON/Markdown files in workspace root |
| **`.swarm/events.jsonl`** | Structured observability | Append-only event log (tool calls, tests, findings, tokens) |
| **tmux** | Process lifecycle | Session/window management, `; exit` for completion |

### `.swarm/` Directory Structure

```
.swarm/
├── belief-map.json          # Hypothesis probabilities
├── journal.md               # Narrative continuity across OODA cycles
├── strategic-context.md     # Decision rationale, dead ends, gaps
├── experiments.tsv          # Append-only experiment ledger
├── success-criteria.json    # What success looks like (metric contracts)
├── claim-evidence.json      # Claim → finding traceability
├── deliverable.md           # Final output (report or manuscript)
├── eval-score.json          # Evaluator score
├── convergence.json         # Convergence result (written at end)
├── lab-notebook.json        # Lab notebook entries per OODA cycle
├── verify-log-<id>.jsonl    # Per-task verify loop iterations
├── events.jsonl             # Structured event log (tool calls, tests, findings)
├── human-gate.json          # Human approval gate (Scientific+ rigor)
├── abort-signal             # Written by /voronoi abort
└── orchestrator-prompt.txt  # Saved prompt for restart recovery
```

## 5. File Audience Separation

Voronoi strictly separates dev files from runtime files:

| Files | Audience | Shipped with pip? |
|-------|----------|:-:|
| `CLAUDE.md` (repo root) | Developers working ON Voronoi | No |
| `docs/*.md` | Developers working ON Voronoi | No |
| `src/voronoi/data/templates/CLAUDE.md` | Investigation agents (runtime constitution) | Yes |
| `src/voronoi/data/agents/` | Agent role definitions | Yes |
| `src/voronoi/data/skills/` | Skill definitions | Yes |
| `src/voronoi/data/scripts/` | Runtime scripts (spawn, merge, etc.) | Yes |
| `scripts/` (repo root) | Dev scripts (sync, dashboard) — NOT shipped | No |

### How files are sourced

- **Editable install** (`pip install -e .`): `find_data_dir()` returns `src/voronoi/data/`. Agent roles read from `data/agents/`, templates from `data/templates/`.
- **Packaged install** (`pip install voronoi`): `find_data_dir()` returns bundled `data/` inside the installed package.
- **`voronoi init`**: Copies runtime `CLAUDE.md` from templates (NOT the dev CLAUDE.md). Copies agents/skills/prompts from package data into target `.github/`.
- **`sync-package-data.sh`**: Copies only `.env.example` into `data/`. Agent roles, scripts, and skills are maintained in-tree under `src/voronoi/data/`.

## 6. Runtime Agent Roles, Prompts, and Skills

The canonical location for all runtime content is `src/voronoi/data/`. During `voronoi init`, these are copied to the target workspace's `.github/` directory.

```
src/voronoi/data/
├── agents/                          # 12 role definitions (canonical)
│   ├── swarm-orchestrator.agent.md
│   ├── worker-agent.agent.md
│   ├── scout.agent.md
│   ├── investigator.agent.md
│   ├── explorer.agent.md
│   ├── critic.agent.md
│   ├── theorist.agent.md
│   ├── methodologist.agent.md
│   ├── statistician.agent.md
│   ├── synthesizer.agent.md
│   ├── evaluator.agent.md
│   └── scribe.agent.md
├── prompts/                         # Invocable prompts
│   ├── spawn.prompt.md              # /spawn — single agent dispatch
│   ├── merge.prompt.md              # /merge — branch integration
│   ├── standup.prompt.md            # /standup — cross-agent status
│   ├── progress.prompt.md           # /progress — progress check
│   └── teardown.prompt.md           # /teardown — cleanup
└── skills/                          # 9 domain knowledge packages
    ├── beads-tracking/
    ├── git-worktree-management/
    ├── branch-merging/
    ├── task-planning/
    ├── artifact-gates/
    ├── evidence-system/
    ├── investigation-protocol/
    ├── strategic-context/
    └── agent-standup/
```

## 6. Infrastructure Scripts

Pure plumbing — no decision logic. The orchestrator makes all decisions.

| Script | Purpose | Invoked by |
|--------|---------|-----------|
| `telegram-bridge.py` | Telegram ↔ Voronoi bridge (singleton, PTB + dispatcher jobs) | `voronoi server start` |
| `spawn-agent.sh` | `git worktree add` → tmux window → `copilot -p` | Orchestrator when dispatching workers |
| `merge-agent.sh` | `git merge` → push → clean worktree → `bd close` | Orchestrator when merging completed work |
| `convergence-gate.sh` | Multi-signal convergence validation + figure-lint | Orchestrator/dispatcher before declaring done |
| `health-check.sh` | Agent health (tmux, git, process tree) | Monitoring, `/health` command |
| `swarm-init.sh` | `git init` · `bd init` · tmux session · config | CLI `voronoi init`, dispatcher |
| `notify-telegram.sh` | Source + call `notify_telegram "event" "msg"` | merge-agent.sh, spawn-agent.sh |
| `figure-lint.sh` | Verify all `\includegraphics` refs resolve | convergence-gate.sh, merge-agent.sh |
| `teardown.sh` | Kill tmux, prune worktrees/branches | User or orchestrator at session end |
| `sync-package-data.sh` | Copy `.env.example` for pip build | Developer workflow |
| `dashboard.py` | Rich terminal dashboard (optional) | Manual monitoring |

## 7. Deployment Topology

### Server Mode (`~/.voronoi/`)

```
~/.voronoi/
├── .env                    # VORONOI_TG_BOT_TOKEN, etc.
├── config.json             # Server configuration
├── queue.db                # SQLite investigation queue
├── objects/                # Shared bare git repos (deduplication)
└── active/                 # One workspace per investigation
    └── inv-{id}-{slug}/
        ├── .swarm/         # Orchestrator state
        ├── .github/        # Agent roles + skills
        ├── data/raw/       # Experimental data
        └── ...             # Investigation workspace
```

### Project Mode (local repo)

```
my-project/
├── .github/                # Agent roles (from voronoi init)
├── scripts/                # Infrastructure scripts
├── CLAUDE.md               # Agent constitution
├── AGENTS.md               # Compatibility alias → CLAUDE.md
└── .swarm/                 # Created during investigation
```

## 8. Dependency Graph

### Python Package Dependencies

| Dependency | Optional Extra | Purpose |
|-----------|----------------|---------|
| (none) | core | Zero runtime dependencies for core |
| `rich>=13.0` | `dashboard` | Terminal dashboard |
| `python-telegram-bot[job-queue]>=20.0` | `telegram` | Telegram bot integration |
| `fpdf2>=2.7` | `report` | PDF generation |
| `pypandoc_binary>=1.13` | `report` | Markdown → PDF conversion |

### External Tool Dependencies

| Tool | Required | Purpose |
|------|----------|---------|
| Python 3.10+ | YES | Runtime |
| Git | YES | Version control, worktrees |
| tmux | YES | Agent process management |
| Beads (bd) | YES | Task tracking, dependencies |
| Copilot CLI / Claude | YES | Agent runtime |
| Docker | NO | Sandbox isolation (fallback to host) |
| gh CLI | NO | GitHub publishing |

## 9. Data Flow: Investigation Lifecycle

```
User question
     │
     ▼
[Intent Classifier] ─── mode + rigor
     │
     ▼
[Investigation Queue] ─── SQLite: queued → running → complete
     │
     ▼
[Dispatcher] ─── provisions workspace, builds prompt
     │
     ▼
[Orchestrator in tmux] ─── reads .github/agents/swarm-orchestrator.agent.md
     │
     ├──► [Scout] ─── prior knowledge, SOTA
     │
     ├──► [Worker 1] ─── git worktree + tmux window
     ├──► [Worker 2] ─── git worktree + tmux window
     ├──► [Worker N] ─── git worktree + tmux window
     │         │
     │         ▼
     │    [Verify Loop] ─── test/lint/artifact per worker
     │         │
     │         ▼
     │    [EVA] ─── experimental validity audit (investigators only)
     │
     ▼
[Review Gates] ─── Statistician → Critic → Evaluator
     │
     ▼
[Synthesizer] ─── deliverable.md + claim-evidence.json
     │
     ▼
[Convergence Check] ─── rigor-specific criteria
     │
     ▼
[Report Generator] ─── teaser + PDF → Telegram/stdout
```

## 10. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Beads for tasks, SQLite for investigations | Different granularity, different lifecycle. Beads per-workspace; queue.db global. |
| Git worktrees over clones | Shared `.git`, faster, less disk, natural cross-branch diff. |
| tmux `; exit` pattern | Session dies when agent finishes — dispatcher detects completion. |
| Atomic queue claiming | `next_ready()` marks as running in same transaction — no double-dispatch. |
| `.github/` fallback copy | `_ensure_github_files()` copies even if `voronoi init` subprocess fails. |
| Timeout (8h default) | Prevents zombie investigations; writes exhaustion convergence. |
| Orchestrator never enters worktrees | Dispatches and monitors; never fixes code in a worker's worktree. |
| File-mediated orchestrator state | Externalizes state to `.swarm/` files between OODA cycles; prevents context loss. |
| Log-redirect + grep for metrics | Workers redirect output to files and extract with grep, preserving context window. |
