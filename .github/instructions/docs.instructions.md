---
description: "Use when modifying spec documents in docs/. Ensures code and tests stay in sync with spec changes."
applyTo: "docs/**/*.md"
---
# Spec Document Change Protocol

When modifying any spec in `docs/`:

1. Use the Module → Spec Mapping table at the bottom of `docs/SPEC-INDEX.md` to identify which source files implement this spec
2. Update the source code to match the new spec — in the same commit
3. Update or add tests for any behavior change — in the same commit
4. If you added or removed lines, the `Lines` column in `docs/SPEC-INDEX.md` is now stale. Run `python scripts/check-spec-index.py --print-ranges` and update every affected row — in the same commit
5. Run: `python -m pytest tests/ -x -q`
6. If the change affects invariants, cross-check with `docs/INVARIANTS.md`
