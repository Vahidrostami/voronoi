---
description: "Use when modifying science modules: convergence detection, fabrication checks, rigor gates, or science helpers."
applyTo: "src/voronoi/science/**"
---
# Science Module Instructions

Before modifying any file in `src/voronoi/science/`:

1. Read `docs/SPEC-INDEX.md` — find the spec section and test file for the module you're changing
2. Read the relevant section of the spec
3. If your change affects gate behavior, rigor levels, or convergence: update the spec FIRST

After changes: run the module's test file first (see SPEC-INDEX), then `python -m pytest tests/ -x -q`.
