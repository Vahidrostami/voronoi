---
description: "Use when modifying science modules: convergence detection, fabrication checks, rigor gates, or science helpers."
applyTo: "src/voronoi/science/**"
---
# Science Module Instructions

Before modifying any file in `src/voronoi/science/`:

1. Read `docs/SPEC-INDEX.md` to find the exact section
2. Read the relevant section of `docs/SCIENCE.md`
3. If your change affects gate behavior, rigor levels, or convergence: update the spec FIRST

Key specs by file:
- `gates.py` → SCIENCE.md §2 (Gate Matrix)
- `convergence.py` → SCIENCE.md §5
- `fabrication.py` → SCIENCE.md §10
- `_helpers.py` → SCIENCE.md (shared utilities)

After changes: run `python -m pytest tests/test_science.py -x -q` first, then `python -m pytest tests/ -x -q`.
