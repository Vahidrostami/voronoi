---
name: voronoi-api
description: >
  Use for navigating Voronoi runtime APIs available inside investigation
  workspaces, including prompt helpers, science validators, citation coverage,
  manifest checks, and utility modules.
user-invocable: true
disable-model-invocation: false
---

# Voronoi API

Use this skill when a worker needs to call Voronoi's packaged Python helpers instead of reimplementing validation or science checks.

## Procedure

1. Prefer existing modules under `voronoi.science`, `voronoi.server`, and `voronoi.gateway` over ad hoc scripts.
2. Inspect the function signature before calling a helper.
3. Use packaged validators for claim ledgers, manifests, citation coverage, fabrication checks, and interpretation checks when available.
4. Keep imports optional for generated artifacts that must run outside the Voronoi environment.
5. Record the helper call and output artifact in task notes.

## Output

Provide:

- helper module and function used
- input artifact paths
- output artifact paths
- validation result
