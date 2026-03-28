---
description: "Use when modifying the MCP server subpackage: validated tool interface for Beads task management and .swarm/ state files."
applyTo: "src/voronoi/mcp/**"
---
# MCP Server Module Instructions

Before modifying any file in `src/voronoi/mcp/`:

1. Read `docs/SPEC-INDEX.md` to find the exact section
2. Read `docs/ARCHITECTURE.md` §8 — the full MCP spec
3. If your change affects tool schemas, validation, or integration: update the spec FIRST

Key specs by file:
- `server.py` → ARCHITECTURE.md §8 (protocol handler, tool registry)
- `tools_beads.py` → ARCHITECTURE.md §8 (task lifecycle, findings, pre-registration)
- `tools_swarm.py` → ARCHITECTURE.md §8 (checkpoints, belief maps, success criteria, experiments)
- `validators.py` → ARCHITECTURE.md §8 (input validation, hash verification, enum enforcement)
- `__main__.py` → Entry point: `python -m voronoi.mcp`

Architecture:
- Per-workspace sidecar — each copilot instance launches its own MCP server
- Replaces free-text `bd update --notes` with schema-enforced tool calls
- 10 registered tools across 3 categories: task lifecycle, findings, state files
- Enforces invariants: INV-10 (pre-registration), INV-11 (data hashes), INV-15, INV-19

Critical rules:
- All inputs validated via `validators.py` before any side effects
- Data hashes computed and verified (SHA-256) — never trust caller-provided hashes
- Pre-registration format must match what science gates consume (DATA-STRUCTURES.md)
- TSV fields sanitized to prevent injection

Test file: `tests/test_mcp.py`
After changes: run `python -m pytest tests/test_mcp.py -x -q` first, then `python -m pytest tests/ -x -q`.
