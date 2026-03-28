---
description: "Use when modifying any Python source file in the voronoi package. Ensures tests are run and updated."
applyTo: "src/voronoi/**/*.py"
---
# Source Code Change Protocol

After modifying any Python file in `src/voronoi/`:

1. **Find the test file**: `tests/test_<module_name>.py`
2. **Run it**: `python -m pytest tests/test_<module_name>.py -x -q`
3. **Run full suite**: `python -m pytest tests/ -x -q`
4. **If you changed behavior**: update or add tests in the same commit
5. **If you changed architecture or public surface**: update the spec first (read `docs/SPEC-INDEX.md` to find which doc)
