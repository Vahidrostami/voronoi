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
├── scripts/           # Infrastructure plumbing (spawn, merge, teardown)
├── .github/           # Agent definitions, prompts & skills for Copilot
│   ├── agents/        # Specialized agent personas (orchestrator, worker, etc.)
│   ├── prompts/       # Slash commands (/swarm, /standup, /merge, etc.)
│   └── skills/        # Reusable domain knowledge modules
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
You ─► /swarm "Build X" ─► Copilot (orchestrator)
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

1. **Plan** — Copilot reads your prompt, decomposes into tasks with dependencies (Beads)
2. **Dispatch** — Each unblocked task gets its own git worktree + worker agent
3. **Monitor** — Copilot watches agent progress, handles failures with judgment
4. **Merge** — Completed work lands on main via `merge-agent.sh`, unblocking the next wave
5. **Repeat** — Until done

The orchestration is Copilot's native reasoning — not a bash state machine. Shell scripts handle only deterministic plumbing (git worktrees, tmux sessions, merges).

## Demos

Run a demo end-to-end:

```bash
voronoi demo list                          # see available demos
voronoi demo run coupled-decisions         # launch a demo
voronoi demo run coupled-decisions --safe  # restrict agent tools
voronoi demo run coupled-decisions --dry-run  # copy files only
```

Example scenarios in [demos/](demos/):

- **[Coupled Decisions](demos/coupled-decisions/)** — Multi-agent reasoning over coupled commercial levers with planted ground truth
- **[Emergent Ecosystem](demos/emergent-ecosystem/)** — Multi-species simulation built by 6 agents in 3 waves
- **[Forgetting Cure](demos/forgetting-cure/)** — Brain-inspired anti-forgetting strategies for continual learning

## Upgrade

When a new version ships:

```bash
pip install --upgrade voronoi
cd my-project
voronoi upgrade
```

This replaces `scripts/` and `.github/{agents,prompts,skills}` with the latest versions. Your `CLAUDE.md` is preserved (that's your customization point).

## Scripts

Voronoi ships 6 shell scripts — all pure infrastructure plumbing:

| Script | Purpose |
|--------|---------|
| `swarm-init.sh` | One-time setup: git, Beads, tmux, `.swarm-config.json` |
| `spawn-agent.sh` | Create git worktree + tmux window, launch agent CLI |
| `merge-agent.sh` | Merge agent branch to main, push, clean up |
| `teardown.sh` | Kill tmux session, prune worktrees/branches |
| `notify-telegram.sh` | Optional Telegram notifications |
| `sync-package-data.sh` | Copy framework files for `pip install .` packaging |

Plus 2 optional Python utilities: `dashboard.py` (live monitoring) and `telegram-bridge.py` (Telegram command bridge).

## Prerequisites

- **Python 3.10+**
- **[Beads (bd)](https://github.com/steveyegge/beads)** — dependency-aware task tracking
- **[tmux](https://github.com/tmux/tmux)** — terminal multiplexer for agent sessions
- **[GitHub CLI (gh)](https://cli.github.com/)** — GitHub integration (optional)
- **[Copilot CLI](https://githubnext.com/projects/copilot-cli/)** — AI coding agent

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

## Design

See [DESIGN.md](DESIGN.md) for architecture and design decisions.

## License

MIT — see [LICENSE](LICENSE).
