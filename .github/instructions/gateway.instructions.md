---
description: "Use when modifying gateway modules: intent classification, Telegram routing, memory, knowledge recall, progress digests, report generation, codename generation, or handoff logic."
applyTo: "src/voronoi/gateway/**"
---
# Gateway Module Instructions

Before modifying any file in `src/voronoi/gateway/`:

1. Read `docs/SPEC-INDEX.md` to find the exact section
2. Read the relevant section of `docs/GATEWAY.md`
3. If your change affects behavior or public surface, update the spec FIRST

Key specs by file:
- `intent.py` → GATEWAY.md §2
- `router.py` → GATEWAY.md §3
- `config.py` → GATEWAY.md §4
- `memory.py` → GATEWAY.md §5
- `knowledge.py` → GATEWAY.md §6
- `literature.py` → GATEWAY.md §7
- `progress.py` → GATEWAY.md §8
- `report.py` → GATEWAY.md §9
- `codename.py` → GATEWAY.md §10
- `handoff.py` → GATEWAY.md §11

After changes: run `python -m pytest tests/ -x -q` and update tests if behavior changed.
