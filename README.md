# Voronoi

Orchestrate multiple AI coding agents working in parallel — with git worktree isolation, dependency-aware task tracking, and automatic merge workflows.

## Install

```bash
pip install voronoi
```

## Usage

```bash
# In any git repo:
cd my-project
voronoi init

# Start your AI coding agent
copilot                    # or: claude
> /swarm Build a full-stack SaaS app with auth, billing, dashboard, and API
```

That's it. The swarm plans the work, spawns isolated agents, and merges results back.

## What `voronoi init` sets up

```
my-project/
├── scripts/           # Orchestration scripts (spawn, merge, standup, teardown)
├── templates/         # Prompt templates for agent personas
├── .claude/           # Slash commands (/swarm, /standup, /merge, etc.)
├── CLAUDE.md          # Agent constitution — edit to customize agent behavior
└── AGENTS.md          # Agent configuration alias
```

**Everything is local files.** No daemon, no server, no account. Agents are coordinated through git branches, [Beads](https://github.com/steveyegge/beads) for task tracking, and tmux sessions.

## Commands

Once initialized, use these from inside your AI coding agent:

| Command | What it does |
|---------|-------------|
| `/swarm <task>` | Decompose task → spawn parallel agents |
| `/standup` | Status report across all agents |
| `/progress` | Quick overview |
| `/spawn <id>` | Launch a single agent on a specific task |
| `/merge` | Merge completed agent branches into current branch |
| `/teardown` | Kill all agents, clean up worktrees |

## How it works

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
                        your branch
```

1. **Plan** — Orchestrator decomposes your task into subtasks with dependencies
2. **Dispatch** — Each unblocked task gets its own git worktree + agent
3. **Monitor** — `/standup` or `/progress` to check on agents
4. **Merge** — `/merge` to land completed work and unblock the next wave
5. **Repeat** — Until done

## Upgrade

When a new version ships:

```bash
pip install --upgrade voronoi
cd my-project
voronoi upgrade
```

This replaces `scripts/`, `templates/`, and `.claude/` with the latest versions. Your `CLAUDE.md` is preserved (that's your customization point).

## Prerequisites

- **Python 3.10+**
- **[Beads (bd)](https://github.com/steveyegge/beads)** — dependency-aware task tracking
- **[tmux](https://github.com/tmux/tmux)** — terminal multiplexer for agent sessions
- **[GitHub CLI (gh)](https://cli.github.com/)** — GitHub integration
- One of: **[Copilot CLI](https://githubnext.com/projects/copilot-cli/)** or **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)**

```bash
# macOS
brew install beads tmux gh
```

## Configuration

After `voronoi init`, a `.swarm-config.json` is generated:

```json
{
  "max_agents": 4,
  "agent_command": "copilot",
  "agent_flags": "--allow-all"
}
```

The init script auto-detects which AI CLI you have installed.

## For Contributors

```bash
# Clone the source repo
git clone https://github.com/Vahidrostami/voronoi
cd voronoi

# Install in editable mode — changes are live instantly
pip install -e .

# Now test against any project
cd /tmp && mkdir test-project && cd test-project && git init
voronoi init     # ← uses your live source files, no rebuild needed

# Run tests
cd ~/voronoi
pytest
```

## Demos

Example scenarios in [demos/](demos/):

- **[Emergent Ecosystem](demos/emergent-ecosystem/)** — Multi-species simulation built by 6 agents in 3 waves

## Design

See [DESIGN.md](DESIGN.md) for architecture and design decisions.

## License

MIT — see [LICENSE](LICENSE).
