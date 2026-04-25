---
name: simplify
description: "Use when asked to reduce code complexity, simplify code, refactor safely, merge micro-files, remove dead code, shrink functions, reduce coupling, clean modules, or improve maintainability in src/voronoi/."
---

# Code Simplification Playbook

## When to Use

Use this skill for maintenance work whose primary goal is simpler code rather than new behavior:

- Reduce complexity in a module or subsystem
- Remove dead code or unused public symbols
- Merge tiny files with unclear independent responsibility
- Split a module that has no single responsibility
- Reduce duplicate logic or needless abstraction
- Prepare a measurable refactoring plan

## Core Rule

Simplification is successful only when behavior is preserved and the improvement is measurable. Prefer a small, proven simplification over a broad rewrite.

## Step 1 - Audit Before Touching

Read the whole target module and its tests. From `docs/SPEC-INDEX.md`, identify the relevant spec section before changing source. Also read `CLAUDE.md` and any matching instruction file under `.github/instructions/` for the touched path, such as `server.instructions.md`, `gateway.instructions.md`, `mcp.instructions.md`, `science.instructions.md`, `cli.instructions.md`, `data.instructions.md`, or `testing.instructions.md`.

Record:

- Public functions, classes, constants, and CLI-visible names
- Imports from sibling modules
- Callers found with `rg "symbol_name" src tests docs .github`
- Tests that cover the behavior
- Any documented paths or invariants that mention the target
- Docs/spec/instruction files read and what constraint each one adds

If the target responsibility cannot be stated in one sentence, decide whether it needs splitting rather than merging.

## Step 2 - Define Success Criteria

Before editing, write objective constraints for the task. Use the smallest set that fits:

- Maximum line count for touched files
- Maximum function length for touched functions
- Symbols to preserve exactly
- Tests that must pass after each checkpoint
- Import/coupling relationship to remove
- Dead code to delete only after caller proof

For cross-module work, create a task list and update it checkpoint by checkpoint.

## Step 2.5 - Decide Plan, Implement, or Hand Off

Use this gate before editing:

- **Plan-only**: use when the request is broad, the target package has unclear ownership, tests are missing, or the proposed work might change architecture/public surface.
- **Simplify implements**: use when the task is behavior-preserving, scoped, tested, and routine: dead-code deletion with caller proof, one-use helper cleanup, duplicate logic removal, private helper movement, or obvious micro-file consolidation.
- **Hand off to Surgeon**: use when implementation changes behavior, public signatures, CLI surfaces, specs, schemas, data contracts, or cross-package flow.
- **Hand off to Catalyst**: use when the simplification depends on an architecture/design judgment rather than local maintainability evidence.
- **Hand off to Auditor**: use after implementation, or after a plan that touches docs, specs, invariants, public surface, file moves, or multiple packages.

The default for a whole package request is plan-only first. The default for a single private helper with caller proof is Simplify implementation.

## Step 3 - Measure Baseline

Capture enough baseline data to prove the work improved maintainability:

```bash
wc -l path/to/file.py
rg "^def |^class |^[A-Z_]+ =" path/to/file.py
rg "from voronoi\.|from \.|import voronoi" path/to/file.py
```

For package-wide simplification, also count files:

```bash
rg --files src/voronoi/<package>
```

Do not optimize for line count alone. A smaller file with worse ownership is not simpler.

## Step 4 - Choose the Refactoring Level

Prefer routine, consistency-oriented refactorings that agents handle well:

- Delete proven-dead code
- Inline one-use helpers that obscure flow
- Extract repeated logic into an existing local helper pattern
- Collapse pass-through wrappers with no semantic value
- Move private helpers closer to their only caller
- Merge micro-files only when ownership is obvious

Treat these as ask-first work:

- Public API renames
- CLI behavior changes
- Gateway/server architecture changes
- Changes to `src/voronoi/data/`
- Signature-only reshaping that does not reduce real complexity

## Step 5 - Edit in Safe Checkpoints

Make one logical simplification at a time. After each meaningful source edit:

1. Run the narrow relevant test from `docs/SPEC-INDEX.md`.
2. If a file was moved, renamed, or deleted, search for stale references in `src/`, `tests/`, `docs/`, and `.github/`.
3. If behavior or public surface changed, update the relevant spec before code or in the same checkpoint.
4. If tests fail, fix the checkpoint before continuing.
5. If a checkpoint reveals broader behavior or architecture impact, stop and hand off rather than expanding scope.

When the user requested commits, keep each commit to one safe checkpoint. Otherwise, report checkpoint boundaries in the final answer and do not commit.

## Step 6 - Verify and Compare

Before completion:

```bash
python -m pytest tests/ -x -q
git diff --stat
git diff --check
```

If any source file changed, run the targeted test files identified from `docs/SPEC-INDEX.md` before the full suite. If any file was moved, renamed, or deleted, search for stale references in `src/`, `tests/`, `docs/`, and `.github/`.

Report:

- What got simpler, with before/after metrics
- Which public behavior was preserved
- Which tests passed
- Any residual complexity deliberately left for a later pass

## Hard Boundaries

- Do not add features.
- Do not change runtime investigation content in `src/voronoi/data/` unless explicitly asked.
- Do not delete code without caller proof.
- Do not continue through failing tests.
- Do not commit or push unless the user explicitly requested git operations.
