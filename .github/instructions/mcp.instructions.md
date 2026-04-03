---
description: "Use when modifying the MCP server subpackage: validated tool interface for Beads task management and .swarm/ state files."
applyTo: "src/voronoi/mcp/**"
---
# MCP Server Module Instructions

Before modifying any file in `src/voronoi/mcp/`:

1. Read `docs/SPEC-INDEX.md` — find the spec section and test file for the module you're changing
2. Read `docs/ARCHITECTURE.md` §8 — the full MCP spec
3. If your change affects tool schemas, validation, or integration: update the spec FIRST

Architecture:
- Per-workspace sidecar — each copilot instance launches its own MCP server
- Replaces free-text `bd update --notes` with schema-enforced tool calls
- Entry point: `python -m voronoi.mcp`

Critical rules:
- All inputs validated via `validators.py` before any side effects
- Data hashes computed and verified (SHA-256) — never trust caller-provided hashes
- Pre-registration format must match what science gates consume (DATA-STRUCTURES.md)
- TSV fields sanitized to prevent injection
- Check `docs/INVARIANTS.md` for INV-10, INV-11, INV-15, INV-19

After changes: run the module's test file first (see SPEC-INDEX), then `python -m pytest tests/ -x -q`.
