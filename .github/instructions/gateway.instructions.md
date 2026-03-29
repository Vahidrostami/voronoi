---
description: "Use when modifying gateway modules: intent classification, Telegram routing, memory, knowledge recall, progress digests, report generation, codename generation, or handoff logic."
applyTo: "src/voronoi/gateway/**"
---
# Gateway Module Instructions

Before modifying any file in `src/voronoi/gateway/`:

1. Read `docs/SPEC-INDEX.md` — find the spec section and test file for the module you're changing
2. Read the relevant section of the spec
3. If your change affects behavior or public surface, update the spec FIRST

After changes: run `python -m pytest tests/ -x -q` and update tests if behavior changed.
