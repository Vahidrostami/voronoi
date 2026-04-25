# Architecture Specification

> System-level architecture, layers, data flow, deployment topology.

**TL;DR**: 4 layers (Entry → Gateway → Server → Execution) + Science layer. Agents communicate via git + Beads + `.swarm/` files only. Orchestrator never enters worktrees. State externalized to files. Zero runtime deps for core. CLI and Telegram both use `prompt.py` as single prompt source. Science layer includes an interpretive coherence gate (directional verification, triviality screening, Judgment Tribunal) that validates findings make scientific sense — not just that experiments ran correctly.

## 1. System Overview

Voronoi is a **science-first multi-agent orchestration system**. The user types one prompt; the system classifies intent, selects rigor level, decomposes work, dispatches parallel agents, enforces review gates, and delivers a report or scientific manuscript.

Science is a superset of engineering — the system is designed for science and engineering works by skipping the science-specific gates.

### Design Principles

| Principle | Implication |
|-----------|------------|
| Science-first | Engineering = science with gates off. Zero overhead for build-only tasks. |
| Single prompt builder | CLI and Telegram produce identical orchestrator behavior via `prompt.py`. |
| Runtime content source of truth | Agent roles live in `src/voronoi/data/agents/` and are copied to `.github/agents/` in investigation workspaces — never duplicated in Python code. |
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
│   handlers_query.py · handlers_mutate.py             │
│   handlers_workflow.py                               │
│   knowledge.py · literature.py · progress.py        │
│   report.py · evidence.py · pdf.py                   │
│   codename.py · handoff.py                           │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Server Layer (OUTER LOOP)               │
│   dispatcher.py — the always-on outer loop:          │
│     collect events · wake orchestrator when needed    │
│     accumulate pending_events while parked           │
│     detect reversed hypotheses · trigger tribunal    │
│     auto-merge worker branches · throttle digests    │
│   queue.py · prompt.py · workspace.py · sandbox.py  │
│   runner.py · publisher.py · repo_url.py · events.py│
│   tmux.py · snapshot.py · compact.py                │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Package Data (shipped with pip)          │
│   data/agents/ · data/skills/ · data/prompts/        │
│   data/instructions/ · data/hooks/ · data/scripts/   │
│   data/templates/                                    │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│         Execution Layer (MIDDLE + INNER LOOPS)       │
│   Orchestrator (episodic copilot sessions —          │
│     read checkpoint → OODA → dispatch → exit)        │
│   Workers (git worktree + tmux window each,          │
│     execute → verify → commit inner loop)            │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                   Science Layer                      │
│   science/ subpackage:                               │
│   consistency · convergence · fabrication · gates     │
│   claims · interpretation · manifest                 │
│   citation_coverage · lab_kg                         │
└─────────────────────────────────────────────────────┘
```

### Three Loops + Judgment Loop

```
Outer Loop  — Dispatcher (code, always on, reliable)
│  Decides: "Does the orchestrator need to be called?"
│  Detects: reversed hypotheses, DESIGN_INVALID, worker completion
│  Does NOT: Reason about science, pick hypotheses, evaluate findings
│
└── Middle Loop — Orchestrator (LLM, episodic sessions, creative)
    │  Decides: Everything about the science
    │  Does NOT: Monitor processes, manage tmux, sleep, merge git
    │
    ├── Inner Loop — Workers (LLM, one-shot, focused)
    │      Execute one task, verify, classify direction, commit.
    │
    └── Judgment Loop — Tribunal (LLM, multi-agent deliberation)
           Triggered by REFUTED_REVERSED or pre-convergence review.
           Theorist + Statistician + Methodologist (+ Critic at pre-convergence).
           Evaluates whether surprising findings make scientific sense.
           Output: tribunal-verdicts.json → blocks or enables convergence.
```

The Judgment Loop is NOT a replacement for any existing loop — it is a targeted intervention that runs between experiment completion and convergence when findings contradict the causal model.

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
              ┌──────┴────────────────────────────────┐
              │                                        │
         DISCOVER/PROVE                          DELIBERATE
              │                                        │
      router → queue.py →                    handle_deliberate()
      dispatcher.py →                        loads investigation context
      workspace.py →                         (belief map, tribunal verdicts,
      prompt.py →                             continuation proposals)
      tmux + copilot                         returns structured summary
              │                                        │
      dispatcher.poll_progress()             user reviews → /continue
      → build_digest()
      → Telegram (every 30s)
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
├── strategic-context.md     # Decision rationale, dead ends, gaps
├── experiments.tsv          # Append-only experiment ledger
├── success-criteria.json    # What success looks like (metric contracts)
├── claim-evidence.json      # Claim → finding traceability
├── deliverable.md           # Final output (report or manuscript)
├── eval-score.json          # Evaluator score
├── convergence.json         # Convergence result (written at end)
├── interpretation-request.json  # Tribunal trigger (written by dispatcher on REFUTED_REVERSED)
├── tribunal-verdicts.json   # Tribunal outputs (EXPLAINED|ANOMALY_UNRESOLVED|ARTIFACT|TRIVIAL)
├── continuation-proposals.json  # Ranked follow-up experiments (generated at review)
├── lab-notebook.json        # Lab notebook entries per OODA cycle
├── verify-log-<id>.jsonl    # Per-task verify loop iterations
├── events.jsonl             # Structured event log (tool calls, tests, findings)
├── human-gate.json          # Human approval gate (Scientific+ rigor)
├── abort-signal             # Written by /voronoi abort
├── orchestrator-prompt.txt  # Saved prompt for restart recovery
└── archive/                 # Archived state from prior rounds
    └── run-<N>/             # Per-round state snapshot
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
- **`voronoi init`**: Copies runtime `CLAUDE.md` from templates (NOT the dev CLAUDE.md). Copies agents/skills/prompts/instructions/hooks from package data into target `.github/`.
- **`sync-package-data.sh`**: Copies only `.env.example` into `data/`. Agent roles, scripts, and skills are maintained in-tree under `src/voronoi/data/`.

## 6. Runtime Agent Roles, Prompts, and Skills

The canonical location for all runtime content is `src/voronoi/data/`. During `voronoi init`, these are copied to the target workspace's `.github/` directory.

```
src/voronoi/data/
├── agents/                          # 19 role files (canonical)
│   ├── swarm-orchestrator.agent.md
│   ├── worker-agent.agent.md
│   ├── question-framer.agent.md
│   ├── assumption-auditor.agent.md
│   ├── scout.agent.md
│   ├── investigator.agent.md
│   ├── explorer.agent.md
│   ├── critic.agent.md
│   ├── theorist.agent.md
│   ├── methodologist.agent.md
│   ├── statistician.agent.md
│   ├── synthesizer.agent.md
│   ├── evaluator.agent.md
│   ├── scribe.agent.md
│   ├── outliner.agent.md
│   ├── lit-synthesizer.agent.md
│   ├── figure-critic.agent.md
│   ├── refiner.agent.md
│   └── red-team.agent.md
├── prompts/                         # Invocable prompts
│   ├── spawn.prompt.md              # /spawn — single agent dispatch
│   ├── merge.prompt.md              # /merge — branch integration
│   ├── standup.prompt.md            # /standup — cross-agent status
│   ├── progress.prompt.md           # /progress — progress check
│   └── teardown.prompt.md           # /teardown — cleanup
├── instructions/                    # File-based instructions (applyTo globs)
│   ├── experiments.instructions.md  # Anti-fabrication for experiments/**
│   ├── data-files.instructions.md   # Data integrity for data/**
│   ├── findings.instructions.md     # Finding schema for *finding*/*results*
│   ├── shell-scripts.instructions.md # Copilot CLI rules for **/*.sh
│   └── test-files.instructions.md   # Test quality for tests/**
├── hooks/                           # Agent lifecycle hooks
│   ├── investigation-hooks.json     # Hook config (SessionStart + PreToolUse)
│   ├── session-context.sh           # Inject Beads status at session start
│   └── protect-data.sh              # Block destructive commands on raw data
└── skills/                          # 21 domain knowledge packages
    ├── beads-tracking/
    ├── git-worktree-management/
    ├── branch-merging/
    ├── task-planning/
    ├── artifact-gates/
    ├── evidence-system/
    ├── investigation-protocol/
    ├── strategic-context/
    ├── agent-standup/
    ├── deep-research/               # /research grounding for scout/explorer
    ├── context-management/          # /compact protocol for long-running agents
    ├── copilot-cli-usage/           # Programmatic LLM call patterns
    └── data-integrity/              # SHA-256 hashing + raw data preservation
```

## 6b. Infrastructure Scripts

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

### Copilot CLI Flags Injected at Launch

Both the dispatcher (orchestrator launch) and `spawn-agent.sh` (worker launch) inject these flags:

| Flag | Orchestrator | Workers | Purpose |
|------|:---:|:---:|---------|
| `--effort <level>` | Yes (from rigor) | Yes (from `.swarm-config.json`) | Reasoning effort scaled by rigor level |
| `--share .swarm/session.md` | Yes | Yes (per-worktree) | Clean markdown audit trail for post-hoc review |
| `--deny-tool=write` | No | Read-only roles only | Structural enforcement of role permissions |

The launchers also propagate Copilot CLI session state into tmux (`COPILOT_HOME`, `GH_HOST`, and auth token env vars when present). This is part of the infrastructure contract for long-running or resumed investigations: a restarted agent must reuse the same Copilot CLI account context instead of prompting for `/login` after a human gate or crash recovery.

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

## 8. MCP Server (`src/voronoi/mcp/`)

### Purpose

Provides validated, typed tool calls for Beads task management and `.swarm/` state files. Replaces free-text `bd update --notes` conventions with schema-enforced MCP tools that prevent malformed metadata, missing fields, and fabricated data hashes.

### Module Layout

```
src/voronoi/mcp/
├── __init__.py
├── __main__.py         # Package entry point (python -m voronoi.mcp)
├── server.py           # MCP stdio transport + tool registry
├── tools_beads.py      # Task lifecycle: create, update, close, query, record_finding
├── tools_swarm.py      # .swarm/ files: checkpoint, belief_map, success_criteria, experiment
└── validators.py       # Schema validation, hash verification, enum checks
```

### Per-Workspace Sidecar

Each copilot instance (orchestrator + each worker) launches its own MCP server process via `.github/mcp-config.json`:

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

`command` is written from the Python interpreter that ran `voronoi init` or provisioned the workspace. This keeps the MCP sidecar on the same environment where the `voronoi` package is installed, even inside spawned investigation workspaces.

The server communicates over stdio (no network, no ports). It reads `VORONOI_WORKSPACE` (or cwd) to locate `.beads/` and `.swarm/` directories.

### Tool Categories

| Category | Tools | Validation |
|----------|-------|-----------|
| **Task lifecycle** | `voronoi_create_task`, `voronoi_close_task`, `voronoi_query_tasks` | PRODUCES/REQUIRES path existence, task status transitions |
| **Findings** | `voronoi_record_finding`, `voronoi_stat_review` | Required fields, data file existence, SHA-256 hash verification |
| **Pre-registration** | `voronoi_pre_register` | Canonical `PRE_REG`/`PRE_REG_POWER`/`PRE_REG_SENSITIVITY` note formats consumed by science gates |
| **State files** | `voronoi_write_checkpoint`, `voronoi_update_belief_map`, `voronoi_update_success_criteria`, `voronoi_log_experiment` | Canonical checkpoint/belief-map schemas, enum values, reference integrity |

### Integration Rules

- Beads MCP tools MUST upsert only the fields they own and preserve unrelated task notes.
- State-file MCP tools MUST read/write the same schemas used by the core convergence and dispatcher code paths.
- `voronoi_update_belief_map` MUST emit the canonical list-based hypothesis schema from INV-33, append new evidence IDs to the existing list (with deduplication, never replace), and re-infer the confidence tier when `posterior` is updated without an explicit `confidence`.

### Invariant Enforcement

The MCP server reinforces invariants at the tool boundary and writes canonical formats that the existing science gates consume directly:

| Invariant | Before (prompt) | After (MCP) |
|-----------|-----------------|-------------|
| INV-10: Pre-reg before execution | Agent told "MUST" | `voronoi_pre_register` writes the canonical fields consumed by dispatch/merge gates |
| INV-11: Raw data SHA-256 | Agent told to compute hash | `voronoi_record_finding` computes and verifies hash |
| INV-15: Claim-evidence trace | Agent told to link findings | `voronoi_update_belief_map` validates evidence IDs and writes canonical evidence links |
| INV-19: PRODUCES verified | merge-agent.sh checks | `voronoi_close_task` checks PRODUCES before allowing close |

## 9. Dependency Graph

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

## 9b. Data Flow: Investigation Lifecycle

```
User question
     │
     ▼
[Intent Classifier] ─── mode + rigor (DISCOVER / PROVE / DELIBERATE)
     │
     ▼
[Investigation Queue] ─── SQLite: queued → running → review → complete
     │
     ▼
[Dispatcher] ─── provisions workspace, builds prompt
     │
     ▼
[Orchestrator in tmux] ─── reads .github/agents/swarm-orchestrator.agent.md
     │
     ├──► [Scout] ─── prior knowledge, SOTA
     │
     ├──► [Theorist] ─── causal model, triviality screening
     │
     ├──► [Worker 1..N] ─── git worktree + tmux window each
     │         │
     │         ▼
     │    [Verify Loop] ─── test/lint/artifact per worker
     │         │
     │         ▼
     │    [EVA] ─── experimental validity audit
     │         │
     │         ▼
     │    [Direction Classification] ─── CONFIRMED / REFUTED_REVERSED / INCONCLUSIVE
     │
     ▼
[Review Gates] ─── Statistician (+ direction verify) → Critic → Evaluator (CCSAN)
     │
     ├── REFUTED_REVERSED? ──► [Judgment Tribunal]
     │                          Theorist + Statistician + Methodologist
     │                          Output: tribunal-verdicts.json
     │                          ANOMALY_UNRESOLVED → block convergence
     │
     ▼
[Synthesizer] ─── deliverable.md + claim-evidence.json
     │
     ▼
[Pre-Convergence Tribunal] ─── mandatory at Analytical+ (+ Critic)
     │
     ▼
[Convergence Check] ─── rigor-specific criteria + tribunal clear + no reversals
     │
     ▼
[Report Generator] ─── teaser + PDF + continuation proposals → Telegram/stdout
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
