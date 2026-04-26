# CLI Specification

> CLI commands, project scaffolding, demo management, server control.

**TL;DR**: Entry point `voronoi` → subcommands: `init` (scaffold), `upgrade`, `demo {list|run|clean}`, `server {init|start|status|prune|config|extend-timeout}`, `clean`, `version`. `init` copies `.github/` roles+skills+prompts + `scripts/`. User-owned: CLAUDE.md, AGENTS.md (never overwritten). All in `src/voronoi/cli.py`.

## 1. Entry Point

```
voronoi = "voronoi.cli:main"
```

Registered as a console script in `pyproject.toml`.

## 2. Command Tree

```
voronoi
├── init                       # Scaffold voronoi into current directory
├── upgrade                    # Upgrade framework files
├── clean                      # Remove all voronoi artifacts
├── version                    # Print version info
├── demo
│   ├── list                   # List available demos
│   ├── run <name>             # Run a demo
│   │   ├── --safe             # Safe mode (resource limits)
│   │   └── --dry-run          # Show what would happen
│   └── clean                  # Remove demo artifacts
│       └── --all              # Remove the entire demo directory
└── server
    ├── init                   # Initialize ~/.voronoi/
    ├── start                  # Start dispatcher + Telegram bridge
    ├── status                 # Show server status
    ├── prune                  # Clean stale investigations
    ├── config                 # View/edit server config
    └── extend-timeout         # Set review budget for a running investigation
```

## 3. `voronoi init`

### Purpose

Scaffolds Voronoi framework into the current directory. Makes a project agent-ready.

### What It Creates

```
.github/
├── agents/           # 19 role files
├── prompts/          # 6 invocable prompts
├── skills/           # Domain knowledge packages
├── instructions/     # Per-path instruction files
├── hooks/            # Copilot CLI hooks (made executable)
└── mcp-config.json   # Per-workspace MCP sidecar config

scripts/              # Infrastructure scripts (made executable)
CLAUDE.md             # Agent constitution
AGENTS.md             # Compatibility alias
.env.example          # Template for secrets
```

### Behavior

1. Creates `.github/` subdirs (`agents/`, `prompts/`, `skills/`, `instructions/`, `hooks/`) with framework files
2. Writes `.github/mcp-config.json` pointing at the same Python interpreter that ran `voronoi init`
3. Copies `scripts/` directory (all `.sh` files made executable)
4. Copies `CLAUDE.md` and `AGENTS.md` (skips if already exist — user-owned)
5. Copies `.env.example`
6. Initializes git repo if not already initialized
7. Runs `swarm-init.sh`, which initializes Beads with `bd init --quiet --server`; if the installed `bd` CLI does not support server mode, the command prints an upgrade warning because worker and dispatcher processes must share one `.beads/` store

### User-Owned Files

Files in `USER_OWNED = {"CLAUDE.md", "AGENTS.md"}` are NEVER overwritten on upgrade. Users may customize these.

### Data Directory Resolution

`_find_data_dir()` locates framework files:
1. **Editable install** — `find_data_dir()` returns `src/voronoi/data/` (canonical location)
2. **Pip install** — `find_data_dir()` returns bundled `data/` inside the installed package

---

## 4. `voronoi upgrade`

### Purpose

Updates framework files while preserving user edits.

### Behavior

1. Copies runtime agents/prompts/skills from package data → project `.github/` — overwrites with latest
2. Refreshes `.github/mcp-config.json` with the current interpreter path
3. Copies `scripts/` — overwrites with latest
4. Skips user-owned files (`CLAUDE.md`, `AGENTS.md`)

---

## 5. `voronoi demo`

### Demo Registry

| Name | Description | Mode | Rigor |
|------|-------------|------|-------|
| `computational-triage` | Evidence encoding as a scaling axis for multi-agent LLM reasoning | PROVE | SCIENTIFIC |
| `compilation-threshold-hunt` | Same hypothesis as `epistemic-trajectories` — swarm designs the experiment, surprise-budget protocol | PROVE | SCIENTIFIC |
| `coupled-decisions` | 5 coupled levers, planted ground truth in 100K transactions | DISCOVER | SCIENTIFIC |
| `emergent-ecosystem` | 4 species on 100×100 grid, each agent builds one | DISCOVER | ADAPTIVE |
| `epistemic-trajectories` | Phase transitions in LLM multi-source reasoning across capability tiers | PROVE | SCIENTIFIC |
| `forgetting-cure` | 4 anti-forgetting strategies, head-to-head MNIST benchmark | DISCOVER | SCIENTIFIC |

### `voronoi demo list`

Lists available demos with name, description, and whether a `PROMPT.md` exists.

### `voronoi demo run <name>`

1. Copies demo files to target directory (or current dir)
2. Reads `PROMPT.md` from demo
3. Builds orchestrator prompt via `build_orchestrator_prompt()`
4. Writes the full orchestrator prompt to `.swarm/orchestrator-prompt.txt`
5. Launches Copilot CLI with a short bootstrap prompt that tells the agent to read `.swarm/orchestrator-prompt.txt` first, avoiding OS argv limits for large demo prompts

**Flags**:
- `--safe` — Enables resource limits (passed to prompt builder)
- `--dry-run` — Prints the prompt that would be sent, doesn't execute

### `voronoi demo clean`

Removes demo artifacts from the current directory.

**Flags**:
- `--all` — Removes the entire demo directory, not just output

---

## 6. `voronoi server`

### `voronoi server init`

1. Creates `~/.voronoi/` directory
2. Creates `config.json` with defaults
3. Copies `.env.example` to `~/.voronoi/.env`
4. Creates `objects/`, `active/`, and `tmp/` directories

Beads is **not** initialized at the server level — each investigation workspace gets its own `.beads/` directory when provisioned (see §5 Workspace in SERVER.md).

### `voronoi server start`

1. Loads config from `~/.voronoi/config.json`
2. Loads `.env` for bot token
3. Exports `TMPDIR`, `TMP`, and `TEMP` to `~/.voronoi/tmp`
4. Starts Telegram bridge (`telegram-bridge.py`) if token present
5. Starts dispatcher loop (10s poll interval)

By default this runs in the foreground. Use `voronoi server start --daemon` on remote hosts or SSH sessions to detach the bridge and write logs to `~/.voronoi/logs/telegram-bridge.log`.

The bridge now auto-restarts after unexpected transient polling failures with exponential backoff. Fatal configuration errors such as invalid bot tokens still fail fast.

### `voronoi server status`

Shows:
- Running investigations (count, names)
- Queued investigations
- Disk usage in `~/.voronoi/`
- tmux sessions

### `voronoi server prune`

Cleans up:
- Completed investigations older than `workspace_retention_days`
- Their sibling `*-swarm/` worktree directories
- Orphaned `*-swarm/` directories whose main workspace has already gone away
- Stale tmux sessions

`--force` is required before anything is removed. Running, queued, paused, and review-state investigations are preserved; prune only removes terminal investigations (`complete`, `failed`, or `cancelled`) past the retention window. If cleanup is blocked by live `bd`, MCP, or agent processes, prune reports the likely locking PIDs instead of silently leaving the directory behind.

### `voronoi server config`

View and edit `~/.voronoi/config.json`.

### `voronoi server extend-timeout`

Set an explicit wall-clock review budget for a running investigation **without restarting** the server. Investigations have no default wall-clock kill; this command is an operator opt-in budget. When the budget is reached, the dispatcher parks the run for partial review rather than marking it failed.

```bash
voronoi server extend-timeout <investigation> <hours>
```

- `<investigation>`: Investigation ID (e.g. `3` or `#3`) or workspace name substring.
- `<hours>`: Total review budget in hours (not additional hours).

Writes `<workspace>/.swarm/timeout_hours` which the dispatcher reads on the next poll cycle. Writing `0`, `off`, `none`, or `disabled` manually disables the budget for that run.

**Example:** Set a 72h review budget while an investigation is running:
```bash
voronoi server extend-timeout coupled-decisions 72
```

You can also write the file manually:
```bash
echo 72 > ~/.voronoi/active/<workspace-name>/.swarm/timeout_hours
```

---

## 7. Framework Constants

```python
FRAMEWORK_DIRS: list[str] = ["scripts"]
TEMPLATE_FILES: list[str] = ["CLAUDE.md", "AGENTS.md"]
GITHUB_SUBDIRS: list[str] = ["agents", "prompts", "skills", "instructions", "hooks"]
USER_OWNED: set[str] = {"CLAUDE.md", "AGENTS.md"}
```

## 8. Dependencies

| Module | Used for |
|--------|----------|
| `voronoi.__version__` | Version display |
| `voronoi.server.prompt.build_orchestrator_prompt` | Demo and server prompt building |
| `voronoi.server.runner.ServerConfig` | Server subcommands |

All other dependencies are stdlib: `argparse`, `json`, `os`, `shutil`, `subprocess`, `sys`, `time`, `pathlib`.
