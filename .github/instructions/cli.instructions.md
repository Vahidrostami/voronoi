---
description: "Use when modifying the CLI entry point: init, upgrade, demo, server, or clean commands."
applyTo: "src/voronoi/cli.py"
---
# CLI Module Instructions

Before modifying `src/voronoi/cli.py`:

1. Read `docs/CLI.md` for the full CLI spec
2. If adding/changing commands or flags, update `docs/CLI.md` and `README.md` (Commands table) FIRST

Key architecture rules:
- `find_data_dir()` returns `src/voronoi/data/` — the single canonical location
- `voronoi init` copies from `data/` into target project's `.github/` and `scripts/`
- FRAMEWORK_DIRS, GITHUB_SUBDIRS, TEMPLATE_FILES control what gets copied
- Guard: never init inside the voronoi source repo itself

Test file: `tests/test_cli.py`
After changes: run `python -m pytest tests/test_cli.py -x -q` first, then full suite.
