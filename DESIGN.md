# Agent Swarm Orchestrator — Design Document

## Project Name: `agent-swarm-template`

A production-ready template repository for orchestrating multiple AI coding agents working in parallel using git worktrees, Beads (bd) for persistent memory and task tracking, tmux for session management, and an AI coding CLI (Copilot CLI or Claude Code) for execution.

---

## 1. Vision

A single developer types:

```
claude
> /swarm Build a full-stack SaaS app with auth, billing, dashboard, and API
```

The orchestrator agent:

1. Breaks the task into an epic with subtasks in Beads
2. Sets up dependency graph (billing depends on auth, dashboard depends on API)
3. Creates isolated git worktrees for each unblocked task
4. Opens a tmux session with one pane per agent
5. Dispatches Claude Code agents into each pane
6. Monitors progress, runs daily standups
7. Merges completed work, promotes newly unblocked tasks
8. Repeats until the epic is done

The human reviews standup reports, approves merges, and steers direction. The agents do the grinding.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      HUMAN (you)                            │
│         /swarm  /standup  /merge  /progress                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   ORCHESTRATOR AGENT                        │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌───────────┐  │
│  │ Planner  │  │ Spawner  │  │  Monitor  │  │  Merger   │  │
│  └──────────┘  └──────────┘  └───────────┘  └───────────┘  │
│                                                             │
│                    ┌──────────┐                              │
│                    │  Beads   │  ← single source of truth   │
│                    │  (bd)    │                              │
│                    └──────────┘                              │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
   ┌─────────────┐ ┌────────────┐ ┌─────────────┐
   │ tmux pane 0 │ │ tmux pane 1│ │ tmux pane 2 │
   │ worktree:   │ │ worktree:  │ │ worktree:   │
   │ agent/auth  │ │ agent/api  │ │ agent/dash  │
   │ copilot -p  │ │ copilot -p │ │ copilot -p  │
   │ or claude   │ │ or claude  │ │ or claude   │
   └─────────────┘ └────────────┘ └─────────────┘
        │                │              │
        └────────────────┼──────────────┘
                         ▼
                  ┌─────────────┐
                  │   main      │  ← merges land here
                  └─────────────┘
```

---

## 3. Repository Structure

```
agent-swarm-template/
├── README.md                          # Quick start guide
├── DESIGN.md                          # This file
├── LICENSE                            # MIT
├── CLAUDE.md                          # Agent instructions (read by all agents)
├── AGENTS.md                          # Compatibility alias → points to CLAUDE.md
├── .claude/
│   ├── settings.json                  # Claude Code project settings
│   ├── commands/                      # Claude Code slash commands
│   │   ├── swarm.md                   # Main orchestrator
│   │   ├── standup.md                 # Daily standup
│   │   ├── progress.md               # Quick progress check
│   │   ├── spawn.md                   # Spawn a single agent
│   │   ├── merge.md                   # Merge completed branches
│   │   └── teardown.md               # Clean up everything
│   └── hooks/
│       └── session-start.sh           # Auto-runs bd prime on session start
├── .github/
│   ├── agents/                        # GitHub Copilot custom agents
│   │   ├── swarm-orchestrator.agent.md
│   │   └── worker-agent.agent.md
│   ├── skills/                        # GitHub Copilot agent skills
│   │   ├── task-planning/SKILL.md
│   │   ├── git-worktree-management/SKILL.md
│   │   ├── beads-tracking/SKILL.md
│   │   ├── agent-standup/SKILL.md
│   │   └── branch-merging/SKILL.md
│   ├── prompts/                       # GitHub Copilot reusable prompts
│   │   ├── swarm.prompt.md
│   │   ├── standup.prompt.md
│   │   ├── spawn.prompt.md
│   │   ├── merge.prompt.md
│   │   ├── progress.prompt.md
│   │   └── teardown.prompt.md
│   └── workflows/
│       ├── daily-standup.yml          # Automated daily standup
│       └── agent-ci.yml              # CI for agent branches
├── scripts/
│   ├── swarm-init.sh                  # One-time project setup
│   ├── spawn-agent.sh                 # Create worktree + tmux + launch agent
│   ├── standup.sh                     # Run standup across all agents
│   ├── merge-agent.sh                 # Merge a completed agent branch
│   ├── teardown.sh                    # Nuclear cleanup
│   └── cron-standup.sh               # Cron-compatible standup runner
├── templates/
│   ├── agent-prompt.md                # Template for worker agent prompts
│   ├── standup-report.md              # Template for standup output
│   └── epic-template.md              # Template for epic planning
└── .beads/                            # Created by bd init (gitignored)
    └── beads.db                       # Beads database
```

---

## 4. GitHub Copilot Integration

This template leverages the newest GitHub Copilot features for agent customization:

### 4.1 Custom Agents (`.github/agents/`)

Each `.agent.md` file defines a Copilot agent persona with YAML frontmatter:

- **`swarm-orchestrator.agent.md`** — The main coordinator that plans, dispatches, monitors, and merges
- **`worker-agent.agent.md`** — Individual worker agents with strict scope discipline

Agents specify their `name`, `description`, `tools`, and behavioral instructions.

### 4.2 Agent Skills (`.github/skills/`)

Skills are modular instruction sets that Copilot loads contextually:

| Skill | Purpose |
|-------|---------|
| `task-planning` | Decomposing features into Beads epics and subtasks |
| `git-worktree-management` | Creating and managing isolated worktrees |
| `beads-tracking` | Using bd for task lifecycle management |
| `agent-standup` | Running progress reports across agents |
| `branch-merging` | Safely merging agent branches to main |

Each skill has a `SKILL.md` with YAML frontmatter and step-by-step instructions.

### 4.3 Reusable Prompts (`.github/prompts/`)

Prompt files (`.prompt.md`) provide quick-trigger workflows:

| Prompt | Trigger |
|--------|---------|
| `swarm` | Plan and dispatch multi-agent workload |
| `standup` | Daily standup report |
| `spawn` | Launch a single agent |
| `merge` | Merge completed branches |
| `progress` | Quick status check |
| `teardown` | Full cleanup |

---

## 5. Core Components

### 5.1 CLAUDE.md — The Agent Constitution

Every agent reads this file on boot. It defines mandatory behavior for task tracking,
git discipline, multi-agent awareness, and quality standards.

### 5.2 Scripts

| Script | Purpose |
|--------|---------|
| `swarm-init.sh` | One-time project setup (checks deps, inits Beads, writes config) |
| `spawn-agent.sh` | Creates worktree, opens tmux pane, launches agent (code domain) |
| `spawn-agent-generic.sh` | Creates directory, opens tmux pane, launches agent (research/generic) |
| `standup.sh` | Queries Beads + git for comprehensive progress report |
| `merge-agent.sh` | Merges agent branch to main, cleans up worktree/tmux |
| `merge-agent-generic.sh` | Assembles output files from generic agent into project |
| `autopilot.sh` | Autonomous daemon: polls, merges, dispatches — no human needed |
| `plan-tasks.sh` | LLM-powered task decomposition from prompt file |
| `quality-gate.sh` | Pluggable validation (tests, conflicts, custom hooks) |
| `dashboard.py` | Rich terminal UI for live swarm monitoring |
| `teardown.sh` | Removes all worktrees, kills tmux, prunes branches |
| `cron-standup.sh` | Cron-compatible wrapper that writes reports and posts issues |

### 5.3 Configuration (`.swarm-config.json`)

Generated by `swarm-init.sh`:

```json
{
  "project_name": "my-app",
  "project_dir": "/path/to/project",
  "swarm_dir": "/path/to/project-swarm",
  "tmux_session": "my-app-swarm",
  "max_agents": 4,
  "agent_command": "copilot",
  "agent_flags": "--allow-all",
  "agent_flags_safe": [
    "--allow-tool", "shell(git*)",
    "--allow-tool", "shell(python*)",
    "--allow-tool", "shell(bd*)",
    "--deny-tool", "shell(curl*)",
    "--deny-tool", "shell(ssh*)",
    "--deny-tool", "shell(sudo*)"
  ],
  "created": "2026-03-01T12:00:00Z"
}
```

### Safe Mode

By default, agents run with `--allow-all` (full autonomy). For unattended or server
deployments, use **safe mode** to restrict agent capabilities via granular tool permissions:

```bash
# Autopilot with safe mode:
./scripts/autopilot.sh --prompt PROMPT.md --safe

# Single agent with safe mode:
./scripts/spawn-agent.sh --safe <task-id> <branch> "<description>"
```

**What safe mode does:**
- ✅ Allows: git, python, npm, node, bd, file operations, sbatch/squeue (Slurm)
- ❌ Blocks: curl, wget, ssh, scp, sudo, dd, rm -rf /, chmod 777, eval, netcat
- Deny rules override allow rules — agents can't bypass restrictions
- Configured via `agent_flags_safe` array in `.swarm-config.json`

**When to use each mode:**

| Scenario | Mode | Flag |
|---|---|---|
| Interactive, watching agents | `--allow-all` | _(default)_ |
| Unattended server (tmux + SSH) | safe | `--safe` |
| CI/CD pipeline | safe | `--safe` |
| Docker sandbox | `--allow-all` | _(sandbox provides isolation)_ |

---

## 6. Workflow: End to End

### Step 0 — Clone and initialize
```bash
git clone https://github.com/yourorg/agent-swarm-template my-app
cd my-app
./scripts/swarm-init.sh
```

### Step 1 — Plan and dispatch
```
claude
> /swarm Build a full-stack task management app with auth, REST API, React frontend, and PostgreSQL backend
```

### Step 2 — Monitor
```bash
tmux attach -t my-app-swarm    # Watch agents work in real time
> /progress                     # Quick check from Claude
```

### Step 3 — Standup
```
> /standup
```

### Step 4 — Merge and re-dispatch
```
> /merge
> /swarm continue
```

### Step 5 — Repeat until epic is done

### Step 6 — Cleanup
```
> /teardown
```

---

## 7. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Beads over markdown plans** | Structured dependency graph with hash-based IDs; `bd ready` answers in milliseconds |
| **Git worktrees over clones** | Shared `.git` directory; faster, less disk space; natural `git diff` across branches |
| **tmux over background processes** | Visual observability; scroll output; intervene in real time |
| **Agent CLI `-p` flag** | Non-interactive execution; agent receives instructions, does work, exits. Supports both `copilot -p` and `claude -p` (configurable via `agent_command` in `.swarm-config.json`) |
| **Max 4 agents** | Balances merge complexity, database contention, and human review overhead |

---

## 8. Autopilot Mode

The `scripts/autopilot.sh` daemon eliminates human-in-the-loop orchestration by implementing a continuous poll-merge-dispatch cycle.

### How It Works

```
User runs: ./scripts/autopilot.sh [--dashboard /tmp/swarm.txt]

┌─────────────────────────────────────────────────────────┐
│                   AUTOPILOT LOOP                        │
│                                                         │
│  1. Dispatch all bd-ready tasks (up to max_agents)      │
│  2. Sleep poll_interval (30s)                           │
│  3. For each active agent:                              │
│     ├─ Beads task closed? → quality gate → merge        │
│     ├─ tmux window gone?  → check results → merge/retry │
│     └─ Timeout exceeded?  → kill → retry (up to 3x)    │
│  4. Check bd ready for newly unblocked tasks            │
│  5. Dispatch next wave                                  │
│  6. Repeat until no open work remains                   │
└─────────────────────────────────────────────────────────┘
```

### Quality Gates

`scripts/quality-gate.sh` runs before every merge:
1. Branch must have commits
2. Beads task must be closed
3. No merge conflicts with main
4. Tests must pass (auto-detects Python pytest / Node npm test)
5. Custom gate hook (`.swarm-quality-gate.sh`) if present

Failed gates trigger a retry with error context (up to `--max-retries`).

### Usage

```bash
# ZERO-TOUCH: From prompt file to finished project
./scripts/autopilot.sh --prompt PROMPT.md --dashboard /tmp/swarm.txt

# Research domain (plain directories, no git branching):
./scripts/autopilot.sh --prompt research-brief.md --domain research

# Pre-planned tasks (Beads already populated):
./scripts/autopilot.sh

# With live TUI dashboard (separate terminal):
python3 scripts/dashboard.py --refresh 3

# Dry run — see what would happen:
./scripts/autopilot.sh --prompt PROMPT.md --dry-run

# Custom timeouts and notification:
./scripts/autopilot.sh --timeout 900 --notify "say 'swarm complete'"
```

### Domain Support

| Domain | Isolation | Merge Strategy | Quality Gate |
|--------|-----------|---------------|--------------|
| `code` (default) | Git worktrees | `git merge` | Tests + conflict check |
| `research` | Plain directories | File assembly | Summary check |
| `generic` | Plain directories | File assembly | Custom hook |

### LLM Auto-Planner

`scripts/plan-tasks.sh` calls the agent CLI to decompose a prompt into structured tasks:

```bash
./scripts/plan-tasks.sh PROMPT.md              # Auto-plan
./scripts/plan-tasks.sh PROMPT.md --dry-run    # Preview only
```

The planner outputs JSON, creates Beads epic + tasks + dependency graph automatically.

### Live Dashboard

`scripts/dashboard.py` provides a rich terminal UI:

```
┌─ 🐝 Swarm Dashboard ─────────────────────────────────────────┐
│ my-project  ████████░░░░░░ 60%  ✓3 ◐2 ○1 ⚡1 ready  🤖2  ⏱5m │
├───────────────────────────────────────────────────────────────┤
│ 📋 Task Graph          │ 🤖 Active Agents                    │
│ ✓ world-engine   P1    │ agent-ants     2 commits  🟢 running │
│ ◐ ants           P2    │ agent-birds    1 commit   🟢 running │
│ ○ runner         P2    │                                      │
└───────────────────────────────────────────────────────────────┘
```

---

## 9. Future Extensions

- Autopilot TUI dashboard (rich terminal UI with live agent status)
- Event-driven completion (fswatch/inotify instead of polling)
- LLM-powered auto-planning (agent decomposes prompt into Beads graph)
- Adaptive retry with failure analysis (LLM reviews errors before retrying)
- Non-code domain support (research papers, business reports, course creation)
- MCP Agent Mail for inter-agent messaging
- Beads Formulas for pre-built epic templates
- Cost tracking per agent per task
- Slack/Discord integration for standup reports
- Multi-repo support for microservice orchestration
