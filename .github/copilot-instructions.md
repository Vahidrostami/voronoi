# Copilot Instructions — Voronoi Development

You are helping develop the Voronoi multi-agent orchestration framework.
Read [CLAUDE.md](../CLAUDE.md) for full project conventions.

## Key Rules

- Python 3.10+, type hints, dataclasses
- No runtime dependencies for core package (rich, telegram, fpdf2 are optional extras)
- Tests: `python -m pytest tests/ -x -q`
- Install: `pip install -e ".[dev,telegram,report,dashboard]"`

## Spec-Driven Development — MANDATORY

Before changing any module:
1. Read `docs/SPEC-INDEX.md` — find which spec covers the area you're changing
2. Read ONLY the relevant section of that spec
3. If your change affects behavior, architecture, or public surface: **update the spec FIRST**, then implement
4. Spec and code changes go in the **same commit**
5. After code changes, run `python -m pytest tests/ -x -q` — fix any failures before committing
6. If you added or changed behavior, update or add tests in `tests/` in the same commit

Do NOT skip the spec lookup. The spec is the source of truth for how voronoi works.

## Architecture Awareness

- `src/voronoi/data/` is the **single canonical location** for all runtime content (agents, prompts, skills, scripts, demos, templates)
- `.github/` is for **development** tooling only (CI workflows, Copilot dev config)
- `prompt.py` is the SOLE prompt builder — both CLI and Telegram use `build_orchestrator_prompt()`
- Agent roles live in `src/voronoi/data/agents/*.agent.md` — prompt builder references, never duplicates
- `scripts/sync-package-data.sh` at repo root is a dev-only build tool (copies `.env.example`)

## What NOT to Do

- Don't modify files in `src/voronoi/data/agents/` unless changing investigation agent behavior
- Don't confuse dev `.github/` with runtime `data/` content
- Don't run `bd` commands in this repo — Beads is a runtime tool for investigation workspaces
- Don't add runtime content to `.github/` — it belongs in `src/voronoi/data/`
- Don't skip tests — every code change must pass `python -m pytest tests/ -x -q`
- Don't commit code without updating the corresponding spec if behavior changed
