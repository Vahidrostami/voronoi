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
| `spawn-agent.sh` | Creates worktree, opens tmux pane, launches Claude Code agent |
| `standup.sh` | Queries Beads + git for comprehensive progress report |
| `merge-agent.sh` | Merges agent branch to main, cleans up worktree/tmux |
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
  "agent_command": "copilot -p",
  "created": "2026-03-01T12:00:00Z"
}
```

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

## 8. Future Extensions

- MCP Agent Mail for inter-agent messaging
- Beads Formulas for pre-built epic templates
- Auto-merge for branches that pass CI
- Priority queuing for automatic task pickup
- Cost tracking per agent per task
- Web dashboard for real-time swarm status
- Slack/Discord integration for standup reports
- Multi-repo support for microservice orchestration
