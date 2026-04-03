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
│   │   ├── --dry-run          # Show what would happen
│   │   └── --all              # Run all demos
│   └── clean                  # Remove demo artifacts
└── server
    ├── init                   # Initialize ~/.voronoi/
    ├── start                  # Start dispatcher + Telegram bridge
    ├── status                 # Show server status
    ├── prune                  # Clean stale investigations
    ├── config                 # View/edit server config
    └── extend-timeout         # Extend timeout for a running investigation
```

## 3. `voronoi init`

### Purpose

Scaffolds Voronoi framework into the current directory. Makes a project agent-ready.

### What It Creates

```
.github/
├── agents/           # 12 role definitions
├── prompts/          # 6 invocable prompts
├── skills/           # Domain knowledge packages
└── mcp-config.json   # Per-workspace MCP sidecar config

scripts/              # Infrastructure scripts (made executable)
CLAUDE.md             # Agent constitution
AGENTS.md             # Compatibility alias
.env.example          # Template for secrets
```

### Behavior

1. Creates `.github/` subdirs (`agents/`, `prompts/`, `skills/`) with framework files
2. Writes `.github/mcp-config.json` pointing at the same Python interpreter that ran `voronoi init`
3. Copies `scripts/` directory (all `.sh` files made executable)
4. Copies `CLAUDE.md` and `AGENTS.md` (skips if already exist — user-owned)
5. Copies `.env.example`
6. Initializes git repo if not already initialized

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
| `coupled-decisions` | 5 coupled levers, planted ground truth in 100K transactions | INVESTIGATE | SCIENTIFIC |
| `emergent-ecosystem` | 4 species on 100×100 grid, each agent builds one | BUILD | STANDARD |
| `forgetting-cure` | 4 anti-forgetting strategies, head-to-head MNIST benchmark | INVESTIGATE | SCIENTIFIC |

### `voronoi demo list`

Lists available demos with name, description, and whether a `PROMPT.md` exists.

### `voronoi demo run <name>`

1. Copies demo files to target directory (or current dir)
2. Reads `PROMPT.md` from demo
3. Builds orchestrator prompt via `build_orchestrator_prompt()`
4. Launches Copilot CLI with the prompt

**Flags**:
- `--safe` — Enables resource limits (passed to prompt builder)
- `--dry-run` — Prints the prompt that would be sent, doesn't execute
- `--all` — Runs all demos sequentially

### `voronoi demo clean`

Removes demo artifacts from the current directory.

---

## 6. `voronoi server`

### `voronoi server init`

1. Creates `~/.voronoi/` directory
2. Creates `config.json` with defaults
3. Copies `.env.example` to `~/.voronoi/.env`
4. Creates `objects/`, `active/`, and `tmp/` directories

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
- Orphaned worktrees
- Stale tmux sessions

### `voronoi server config`

View and edit `~/.voronoi/config.json`.

### `voronoi server extend-timeout`

Extend (or set) the timeout for a running investigation **without restarting** the server.

```bash
voronoi server extend-timeout <investigation> <hours>
```

- `<investigation>`: Investigation ID (e.g. `3` or `#3`) or workspace name substring.
- `<hours>`: New **total** timeout in hours (not additional hours).

Writes `<workspace>/.swarm/timeout_hours` which the dispatcher reads on the next poll cycle.

**Example:** Extend a 48h investigation to 72h while it's running:
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
FRAMEWORK_FILES: list[str] = ["CLAUDE.md", "AGENTS.md", ".env.example"]
GITHUB_SUBDIRS: list[str] = ["agents", "prompts", "skills"]
USER_OWNED: set[str] = {"CLAUDE.md", "AGENTS.md"}
```

## 8. Dependencies

| Module | Used for |
|--------|----------|
| `voronoi.__version__` | Version display |
| `voronoi.server.prompt.build_orchestrator_prompt` | Demo and server prompt building |
| `voronoi.server.runner.ServerConfig` | Server subcommands |

All other dependencies are stdlib: `argparse`, `json`, `os`, `shutil`, `subprocess`, `sys`, `time`, `pathlib`.
