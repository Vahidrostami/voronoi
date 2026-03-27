---
description: "Use when modifying server modules: investigation queue, dispatcher, prompt builder, workspace provisioning, sandbox, runner, events, or publisher."
applyTo: "src/voronoi/server/**"
---
# Server Module Instructions

Before modifying any file in `src/voronoi/server/`:

1. Read `docs/SPEC-INDEX.md` to find the exact section
2. Read the relevant section of `docs/SERVER.md`
3. If your change affects behavior or public surface, update the spec FIRST

Key specs by file:
- `queue.py` → SERVER.md §2
- `dispatcher.py` → SERVER.md §3
- `prompt.py` → SERVER.md §4
- `workspace.py` → SERVER.md §5
- `sandbox.py` → SERVER.md §6
- `runner.py` → SERVER.md §7
- `publisher.py` → SERVER.md §8
- `events.py` → CONTEXT-MANAGEMENT.md §10

Critical invariants:
- `prompt.py` is the SOLE prompt builder — INV-01 in INVARIANTS.md
- Role files are source of truth — INV-02
- Orchestrator never enters worktrees — INV-03

After changes: run `python -m pytest tests/ -x -q` and update tests if behavior changed.
