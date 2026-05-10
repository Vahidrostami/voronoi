---
name: observability
description: >
  Use for inspecting Voronoi investigation state, event logs, progress files,
  tmux/worker status, .swarm artifacts, and Beads task traces without changing
  investigation behavior.
user-invocable: true
disable-model-invocation: false
---

# Observability

Use this skill when you need to understand what an investigation is doing or why it appears stuck.

## Procedure

1. Inspect `.swarm/` state files before reading long logs.
2. Check the active task graph with targeted Beads queries for ready, blocked, and recently updated tasks.
3. Review structured event logs and progress artifacts before worker chatter.
4. Compare expected phase against existing artifacts: novelty gate, pre-registration, raw data, claim ledger, convergence, manuscript state.
5. Summarize state as facts, unknowns, and next observable signal.

## Output

Provide:

- current phase
- active or blocked workers
- newest meaningful artifact
- missing expected artifact
- recommended next observation or operator action
