"""Voronoi MCP Server — validated tool interface for Beads + .swarm/ state.

Provides typed, schema-enforced MCP tools that replace free-text ``bd update
--notes`` conventions.  Each tool validates inputs at the boundary so agents
cannot produce malformed metadata, skip required fields, or fabricate data
hashes.

Run as: ``python -m voronoi.mcp``
"""
