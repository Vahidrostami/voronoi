# Agent Swarm Template

A production-ready template for orchestrating multiple AI coding agents working in parallel using git worktrees, [Beads](https://github.com/steveyegge/beads) for task tracking, tmux for session management, and an AI coding CLI ([Copilot CLI](https://githubnext.com/projects/copilot-cli/) or [Claude Code](https://docs.anthropic.com/en/docs/claude-code)) for execution.

Clone → initialize → start shipping features 10x faster with a self-organizing team of AI agents.

## Quick Start

```bash
# 1. Clone and enter
git clone https://github.com/yourorg/agent-swarm-template my-app
cd my-app

# 2. Install dependencies
brew install beads tmux gh

# 3. Initialize
./scripts/swarm-init.sh

# 4. Launch the swarm
claude
> /swarm Build a full-stack SaaS app with auth, billing, dashboard, and API
```

## How It Works

```
You ─► /swarm "Build X" ─► Orchestrator
                              │
                  ┌───────────┼───────────┐
                  ▼           ▼           ▼
             agent-auth   agent-api   agent-dash
             (worktree)   (worktree)  (worktree)
                  │           │           │
                  └───────────┼───────────┘
                              ▼
                         main branch
```

1. **Plan** — The orchestrator decomposes your task into an epic with subtasks in Beads
2. **Dispatch** — Unblocked tasks get isolated git worktrees + tmux panes + Claude Code agents
3. **Monitor** — Run `/standup` or `/progress` to check agent status
4. **Merge** — Run `/merge` to land completed work and unblock downstream tasks
5. **Repeat** — Until the epic is done

## Commands

| Command | Description |
|---------|-------------|
| `/swarm <task>` | Plan and dispatch a multi-agent workload |
| `/standup` | Daily standup across all agents |
| `/progress` | Quick status check |
| `/spawn <id>` | Spawn a single agent on a task |
| `/merge` | Merge completed agent branches |
| `/teardown` | Clean up all worktrees and sessions |

## GitHub Copilot Integration

This template includes support for the newest GitHub Copilot features:

- **`.github/agents/`** — Custom Copilot agents (orchestrator + worker personas)
- **`.github/skills/`** — Modular agent skills (task planning, worktree management, etc.)
- **`.github/prompts/`** — Reusable prompt templates for common workflows

## Repository Structure

```
agent-swarm-template/
├── .claude/commands/          # Claude Code slash commands
├── .github/
│   ├── agents/                # Copilot custom agents
│   ├── skills/                # Copilot agent skills
│   ├── prompts/               # Copilot reusable prompts
│   └── workflows/             # CI + automated standup
├── scripts/                   # Shell scripts for orchestration
├── templates/                 # Prompt and report templates
├── CLAUDE.md                  # Agent constitution
├── AGENTS.md                  # → CLAUDE.md alias
└── DESIGN.md                  # Full design document
```

## Prerequisites

- [Beads (bd)](https://github.com/steveyegge/beads) — Task tracking with dependency graphs
- [tmux](https://github.com/tmux/tmux) — Terminal multiplexer for agent sessions
- [GitHub CLI (gh)](https://cli.github.com/) — GitHub integration
- One of: [Copilot CLI](https://githubnext.com/projects/copilot-cli/) or [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — AI coding agent (must support `-p` flag for non-interactive mode)

## Why Not Just `/fleet`?

Copilot's `/fleet` command is great for parallelizing short-lived tasks within a single session — like writing tests for 10 files. But it doesn't solve multi-day epics: subagents share a working directory (risking file conflicts), task state vanishes when the session ends, and there's no merge workflow or human oversight. This template gives you **git worktree isolation** so agents can't step on each other, **Beads for persistent task tracking** that survives across sessions and reboots, **explicit branch merges** with conflict detection, and **standup reports** so you stay in control. Think of `/fleet` as a turbo button for one agent's subtask; this is the full command center for a team of agents shipping a feature over days.

## Configuration

After running `swarm-init.sh`, edit `.swarm-config.json`:

```json
{
  "max_agents": 4,
  "agent_command": "copilot -p",
  "auto_merge": false,
  "branch_prefix": "agent-"
}
```

The `agent_command` field controls which CLI is used to dispatch worker agents into tmux panes. Supported values:
- `"copilot -p"` — GitHub Copilot CLI (default)
- `"claude -p"` — Claude Code CLI

The init script auto-detects which is installed. Override manually if needed.

## Design

See [DESIGN.md](DESIGN.md) for the full architecture, workflow diagrams, and design decisions.

## Demos

Ready-to-run scenarios in [demos/](demos/):

- **[Emergent Ecosystem](demos/emergent-ecosystem/)** — 4 species with different communication strategies compete on a shared grid. 6 agents across 3 waves. Run it with Copilot CLI or Claude Code:
  ```bash
  copilot
  > /swarm @swarm-orchestrator Build an emergent multi-species ecosystem simulation. Details in demos/emergent-ecosystem/PROMPT.md
  ```

## License

MIT — see [LICENSE](LICENSE).
