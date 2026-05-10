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

Five specialized agents work ON Voronoi (not inside investigations):

| Agent | Role | When to Use |
|-------|------|-------------|
| **Catalyst** | Design critic, brainstorming | "Review this design", "How should we...", UX critique |
| **Surgeon** | Implementation | "Implement X", "Fix Y", "Add Z", code changes |
| **Auditor** | Spec-code-test-doc verification | After multi-file changes, before releases, drift checks |
| **Detective** | Bug hunting, adversarial analysis | "Find bugs in X", security review, pre-release audit |
| **Simplify** | Complexity reduction, dead-code cleanup | "Simplify X", "reduce complexity", "merge micro-files", "remove dead code" |

Handoff chains:
- Catalyst → Surgeon ("implement this design")
- Surgeon → Auditor ("verify my changes")
- Detective → Surgeon ("fix this bug")
- Auditor → Surgeon ("fix this drift")
- Catalyst/Surgeon → Simplify ("reduce complexity without behavior changes")
- Simplify → Surgeon ("implement a simplification plan that changes behavior, public surface, or specs")
- Simplify → Catalyst ("resolve architecture/design judgment before simplifying")
- Simplify → Auditor ("verify simplification did not create spec/test/doc drift")

## Code Complexity Rules

These rules apply during simplification and refactoring work. Flag violations before expanding the affected code.

- Soft max file length: 300 lines. If a touched file stays over 300 lines, explain why it remains cohesive.
- Soft max function length: 40 lines. If a touched function stays over 40 lines, explain why extraction would make it worse.
- A module that imports from more than 3 sibling modules may be misplaced; flag the ownership question before adding another sibling import.
- Dead code rule: if a function or class has no callers in `src/`, `tests/`, `docs/`, or `.github/`, delete it only after confirming it is not public runtime surface.
- After refactoring, run relevant targeted tests and `python -m pytest tests/ -x -q`; report line-count delta and test results.
- Use the `simplify` skill for code simplification, dead-code removal, micro-file merges, and maintainability refactors.

## What NOT to Do

- Don't modify files in `src/voronoi/data/agents/` unless changing investigation agent behavior
- Don't confuse dev `.github/` with runtime `data/` content
- Don't run `bd` commands in this repo — Beads is a runtime tool for investigation workspaces
- Don't add runtime content to `.github/` — it belongs in `src/voronoi/data/`
- Don't skip tests — every code change must pass `python -m pytest tests/ -x -q`
- Don't commit code without updating the corresponding spec if behavior changed
