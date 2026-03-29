---
description: "Use when modifying runtime content shipped to investigation workspaces: agent role definitions, skills, prompts, runtime scripts, demo investigations, or workspace templates."
applyTo: "src/voronoi/data/**"
---
# Runtime Data Instructions

`src/voronoi/data/` is the **canonical location** for all runtime content. Changes here affect every investigation workspace.

## What lives here

| Directory | Content | Spec |
|-----------|---------|------|
| `agents/` | Agent role definitions (`.agent.md`) | AGENT-ROLES.md |
| `skills/` | Domain knowledge packages (`SKILL.md`) | AGENT-ROLES.md §6 |
| `prompts/` | Runtime prompts (spawn, merge, standup, progress, teardown) | SERVER.md §4 |
| `scripts/` | Shell scripts (spawn-agent.sh, etc.) | ARCHITECTURE.md §6 |
| `demos/` | Demo investigations | CLI.md §5 |
| `templates/` | CLAUDE.md + AGENTS.md for workspaces | ARCHITECTURE.md §5 |

## Rules

- These files are shipped with `pip install voronoi` — changes affect all users
- Agent roles are the source of truth (INV-02) — never duplicate in Python code
- `voronoi init` copies agents/prompts/skills → target `.github/`, scripts → target `scripts/`
- Do NOT add dev-only content here — that goes in `.github/`

After changes: run `python -m pytest tests/ -x -q`.
