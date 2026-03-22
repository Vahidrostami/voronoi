# Voronoi Development Instructions

> Instructions for agents/developers working **on** the Voronoi codebase itself.
> NOT for investigation agents — those use `src/voronoi/data/templates/CLAUDE.md`.

## Build, Test, and Development

- Python 3.10+, type hints, dataclasses
- Install: `pip install -e ".[dev,telegram,report,dashboard]"`
- Tests: `python -m pytest tests/ -x -q`
- No runtime dependencies for core package (rich, telegram, fpdf2 are optional extras)

## Project Structure

```
src/voronoi/           # Package code
├── cli.py             # CLI entry point (init, demo, server)
├── beads.py           # Beads wrapper (bd subprocess calls)
├── utils.py           # Shared utilities (field extraction, note parsing)
├── gateway/           # Intent classification, routing, memory, knowledge, reporting
├── server/            # Queue, dispatcher, prompt builder, workspace, events
├── science/           # Gates, convergence, fabrication, belief maps
└── data/              # Runtime files shipped with pip install
    ├── templates/     # CLAUDE.md + AGENTS.md for investigation workspaces
    ├── agents/        # .agent.md role definitions (synced from .github/agents/)
    ├── skills/        # SKILL.md files (synced from .github/skills/)
    ├── prompts/       # .prompt.md files (synced from .github/prompts/)
    └── scripts/       # Runtime shell scripts (spawn, merge, convergence gate)
```

## Key Architecture Rules

- `prompt.py` is the SOLE prompt builder — CLI and Telegram both call `build_orchestrator_prompt()`
- Agent roles live in `.github/agents/*.agent.md` — prompt builder references, never duplicates
- `sync-package-data.sh` copies `.github/` → `src/voronoi/data/` before `pip install .`
- Editable installs (`pip install -e .`) read from repo root; packaged installs read from `data/`

## File Audience Separation

| Files | Audience | Shipped with pip? |
|-------|----------|:-:|
| `CLAUDE.md` (this file) | Developers working ON Voronoi | No |
| `docs/*.md` | Developers working ON Voronoi | No |
| `src/voronoi/data/templates/CLAUDE.md` | Investigation agents working WITH Voronoi | Yes |
| `src/voronoi/data/agents/` | Investigation agents (and Copilot during dev via `.github/` symlink) | Yes |

## Specs — Developer Reference

Detailed specs live in `docs/`. Read only what you need:
1. Start with `docs/SPEC-INDEX.md` (~70 lines) — maps your task to the right spec
2. For dataclass signatures → `docs/DATA-STRUCTURES.md`
3. For rules that must not be violated → `docs/INVARIANTS.md`

## Task Tracking

For **dev work on this repo**, use the VS Code todo list / Copilot task tracking — not `bd`.

Beads (`bd`) is a **runtime tool only** — it tracks tasks inside investigation workspaces that Voronoi spawns at runtime. Do not run `bd` commands in this repo root for dev planning.

## Docs Freshness — MANDATORY

After any change that affects the public surface, behaviour, or architecture, you MUST update the relevant files **in the same commit**:

| Changed area | Files to update |
|---|---|
| CLI commands, server flags, Telegram commands | `README.md` (Commands table), `docs/CLI.md` |
| Architecture, module layout, data flow | `README.md` (Architecture section), `docs/ARCHITECTURE.md`, `DESIGN.md` |
| Dataclass fields / signatures | `docs/DATA-STRUCTURES.md` |
| Invariants or critical rules | `docs/INVARIANTS.md` |
| Gateway / routing / prompts | `docs/GATEWAY.md` |
| Science gates, rigor levels | `docs/SCIENCE.md` |
| Server loop, dispatcher, workspace | `docs/SERVER.md` |
| Workflows, OODA, agent lifecycle | `docs/WORKFLOWS.md` |

If a change does **not** affect any documented surface, no doc update is needed — but when in doubt, update.

## Git Discipline — MANDATORY

- ALWAYS push before ending a session
- Commit early and often with clear messages
- If push fails, rebase and retry until it succeeds
