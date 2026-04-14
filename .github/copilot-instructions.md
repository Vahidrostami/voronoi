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

Read `CLAUDE.md` for full architecture rules. The key principles:

- `src/voronoi/data/` is the canonical location for all runtime content — `.github/` is dev tooling only
- `prompt.py` is the sole prompt builder — both CLI and Telegram use `build_orchestrator_prompt()`
- Agent roles live in `src/voronoi/data/agents/*.agent.md` — prompt builder references, never duplicates
- Use `list_dir` and `docs/SPEC-INDEX.md` to discover project structure and module mappings — don't memorize them

## Dev Agent Roster

Four specialized agents work ON Voronoi (not inside investigations):

| Agent | Role | When to Use |
|-------|------|-------------|
| **Catalyst** | Design critic, brainstorming | "Review this design", "How should we...", UX critique |
| **Surgeon** | Implementation | "Implement X", "Fix Y", "Add Z", code changes |
| **Auditor** | Spec-code-test-doc verification | After multi-file changes, before releases, drift checks |
| **Detective** | Bug hunting, adversarial analysis | "Find bugs in X", security review, pre-release audit |

Handoff chains:
- Catalyst → Surgeon ("implement this design")
- Surgeon → Auditor ("verify my changes")
- Detective → Surgeon ("fix this bug")
- Auditor → Surgeon ("fix this drift")

## What NOT to Do

- Don't modify files in `src/voronoi/data/agents/` unless changing investigation agent behavior
- Don't confuse dev `.github/` with runtime `data/` content
- Don't run `bd` commands in this repo — Beads is a runtime tool for investigation workspaces
- Don't add runtime content to `.github/` — it belongs in `src/voronoi/data/`
- Don't skip tests — every code change must pass `python -m pytest tests/ -x -q`
- Don't commit code without updating the corresponding spec if behavior changed
