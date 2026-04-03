---
description: "Use when modifying server modules: investigation queue, dispatcher, prompt builder, workspace provisioning, sandbox, runner, events, or publisher."
applyTo: "src/voronoi/server/**"
---
# Server Module Instructions

Before modifying any file in `src/voronoi/server/`:

1. Read `docs/SPEC-INDEX.md` — find the spec section and test file for the module you're changing
2. Read the relevant section of the spec
3. If your change affects behavior or public surface, update the spec FIRST
4. Check `docs/INVARIANTS.md` if touching `prompt.py` (INV-01), role files (INV-02), or orchestrator dispatch (INV-03)

After changes: run `python -m pytest tests/ -x -q` and update tests if behavior changed.
