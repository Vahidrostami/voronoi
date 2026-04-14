---
description: "Use when moving, renaming, or deleting any file or directory in src/voronoi/. Ensures all hardcoded path references across docs and configs are updated."
applyTo: "src/voronoi/**"
---
# Structure Change Protocol

If you moved, renamed, or deleted a file or directory:

1. **Grep all docs for stale references** to the old path:
   ```bash
   grep -r "old/path" docs/ CLAUDE.md DESIGN.md README.md .github/ --include="*.md"
   ```

2. **Check SPEC-INDEX.md** — update the Module → Spec → Test Mapping table if any row references the old path

3. **Check INVARIANTS.md** — update any invariant that references the old path or module name

4. **Check pyproject.toml** — update `[tool.pytest]`, `[project.scripts]`, or `packages` if relevant

5. **Check DESIGN.md tree listings** — update any code-fenced directory trees

6. Update all references in the same commit as the move/rename/delete.
