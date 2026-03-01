# Agent Swarm Orchestrator — Design Document

## Project Name: `agent-swarm-template`

A production-ready template repository for orchestrating multiple AI coding agents working in parallel using git worktrees, Beads (bd) for persistent memory and task tracking, tmux for session management, and Claude Code / GitHub CLI for execution.

Clone this repo, initialize it in your project, and start shipping features 10x faster with a self-organizing team of AI agents.

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
│  │          │  │          │  │           │  │           │  │
│  │ breaks   │  │ creates  │  │ runs      │  │ merges    │  │
│  │ tasks    │  │ worktrees│  │ standups  │  │ branches  │  │
│  │ into     │  │ + tmux   │  │ checks    │  │ resolves  │  │
│  │ beads    │  │ sessions │  │ progress  │  │ conflicts │  │
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
   │             │ │            │ │             │
   │ worktree:   │ │ worktree:  │ │ worktree:   │
   │ agent/auth  │ │ agent/api  │ │ agent/dash  │
   │             │ │            │ │             │
   │ claude -p   │ │ claude -p  │ │ claude -p   │
   │ "build auth"│ │ "build api"│ │ "build dash"│
   └─────────────┘ └────────────┘ └─────────────┘
        │                │              │
        └────────────────┼──────────────┘
                         ▼
                  ┌─────────────┐
                  │   main      │  ← merges land here
                  │   branch    │
                  └─────────────┘
```

---

## 3. Repository Structure

```
agent-swarm-template/
│
├── README.md                          # Quick start guide
├── DESIGN.md                          # This file
├── LICENSE                            # MIT
│
├── .claude/
│   ├── settings.json                  # Claude Code project settings
│   ├── commands/
│   │   ├── swarm.md                   # Main orchestrator: plan + dispatch agents
│   │   ├── standup.md                 # Daily standup: review all agent progress
│   │   ├── progress.md               # Quick progress check
│   │   ├── spawn.md                   # Spawn a single agent on a task
│   │   ├── merge.md                   # Merge completed agent branches
│   │   └── teardown.md               # Clean up all worktrees and tmux sessions
│   └── hooks/
│       └── session-start.sh           # Auto-runs bd prime on session start
│
├── CLAUDE.md                          # Agent instructions (read by all agents)
├── AGENTS.md                          # Compatibility alias → points to CLAUDE.md
│
├── scripts/
│   ├── swarm-init.sh                  # One-time project setup (install bd, init, etc.)
│   ├── spawn-agent.sh                 # Create worktree + tmux pane + launch agent
│   ├── standup.sh                     # Run standup across all agents
│   ├── merge-agent.sh                 # Merge a completed agent branch
│   ├── teardown.sh                    # Nuclear cleanup: remove all worktrees + sessions
│   └── cron-standup.sh               # Cron-compatible standup runner
│
├── templates/
│   ├── agent-prompt.md                # Template prompt injected into each worker agent
│   ├── standup-report.md              # Template for standup output
│   └── epic-template.md              # Template for epic planning
│
├── .github/
│   └── workflows/
│       ├── daily-standup.yml          # GitHub Action: automated daily standup
│       └── agent-ci.yml              # CI that runs on each agent branch
│
└── .beads/                            # Created by bd init (gitignored or committed)
    └── beads.db                       # Beads database (task graph, memory)
```

---

## 4. Core Components

### 4.1 CLAUDE.md — The Agent Constitution

Every agent (orchestrator and workers) reads this file on boot. It is the single source of behavioral rules covering:
- Mandatory Beads usage for task tracking
- Git discipline (always push, commit often)
- Multi-agent awareness (stay in your worktree, file discoveries)
- Quality standards (write tests, run suite before closing)

### 4.2 Scripts

| Script | Purpose |
|--------|---------|
| `swarm-init.sh` | One-time setup: check deps, init Beads, create config |
| `spawn-agent.sh` | Create worktree + tmux pane + launch Claude Code agent |
| `standup.sh` | Query Beads + git for full progress report |
| `merge-agent.sh` | Merge completed branch, clean up worktree |
| `teardown.sh` | Nuclear cleanup: kill all agents, remove worktrees |
| `cron-standup.sh` | Cron-compatible wrapper for standup |

### 4.3 Claude Code Commands

| Command | Description |
|---------|-------------|
| `/swarm` | Main orchestrator: plan epic, set dependencies, dispatch agents |
| `/standup` | Interpret standup data, make recommendations |
| `/progress` | Quick raw status check |
| `/spawn` | Spawn a single agent on a task |
| `/merge` | Merge completed branches with confirmation |
| `/teardown` | Full cleanup with safety confirmation |

---

## 5. Workflow: End to End

### Step 0 — Initialize
```bash
./scripts/swarm-init.sh
```

### Step 1 — Plan and dispatch
```
> /swarm Build a full-stack task management app
```
Creates epic → subtasks → dependencies → spawns agents for unblocked tasks.

### Step 2 — Monitor
```bash
tmux attach -t my-app-swarm   # Watch agents work
> /progress                    # Quick check
```

### Step 3 — Standup
```
> /standup
```
Reports completed work, in-progress items, blocked tasks, and recommendations.

### Step 4 — Merge and re-dispatch
```
> /merge
> /swarm continue
```

### Step 5 — Repeat until done

### Step 6 — Cleanup
```
> /teardown
```

---

## 6. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Beads over markdown** | Structured dependency graph, hash IDs, `bd ready` in milliseconds |
| **Git worktrees over clones** | Shared `.git` dir, faster, less disk space |
| **tmux over background** | Visual observability, ability to intervene |
| **Claude `-p` flag** | Non-interactive execution, perfect for dispatch |
| **Max 4 agents** | Practical limit for merge complexity and review overhead |

---

## 7. Future Extensions

- MCP Agent Mail for inter-agent messaging
- Beads Formulas for pre-built epic templates
- Auto-merge for branches passing CI
- Priority queuing for automatic task pickup
- Cost tracking per agent per task
- Web dashboard for real-time swarm status
- Slack/Discord integration for standup reports
- Multi-repo support for microservice orchestration
