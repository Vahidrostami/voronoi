# Voronoi — Specification Documents

This directory contains the **complete technical specification** for Voronoi. These specs are the source of truth for agentic development — agents read these before implementing, and reference them during further development.

## How to Use These Specs

1. **Start here**: Read [SPEC-INDEX.md](SPEC-INDEX.md) (~70 lines) — it maps your task to the right spec + section
2. **Scan the TL;DR**: Each spec has a TL;DR at the top (~2 lines). Read that first.
3. **Read one section**: Jump to the specific section number from the index. Do NOT read the whole file.
4. **During development**: Reference the spec for API signatures, data structures, and error handling
5. **After coding**: Verify your implementation matches the spec

## Document Index

| Document | Scope | When to read |
|----------|-------|-------------|
| **[SPEC-INDEX.md](SPEC-INDEX.md)** | **Task → spec + section lookup** | **Always read first (~70 lines)** |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System-level architecture, layers, data flow, deployment | Starting any work on Voronoi |
| [GATEWAY.md](GATEWAY.md) | Gateway layer: intent, routing, memory, knowledge, reporting | Working on Telegram/user-facing features |
| [SERVER.md](SERVER.md) | Server layer: queue, dispatcher, workspace, sandbox, prompt | Working on investigation lifecycle |
| [SCIENCE.md](SCIENCE.md) | Science framework: rigor gates, belief maps, convergence, EVA | Working on evidence/investigation logic |
| [CLI.md](CLI.md) | CLI commands, project scaffolding, demo management | Working on CLI or `voronoi` command |
| [AGENT-ROLES.md](AGENT-ROLES.md) | 12 agent roles, activation rules, verify loops | Working on agent orchestration |
| [DATA-STRUCTURES.md](DATA-STRUCTURES.md) | All dataclasses, schemas, file formats, DB schemas | Implementing or consuming data |
| [WORKFLOWS.md](WORKFLOWS.md) | End-to-end workflows: discover, prove, demo | Understanding user journeys |
| [INVARIANTS.md](INVARIANTS.md) | System-wide invariants that must never be violated | Code review, debugging |
| [GLOSSARY.md](GLOSSARY.md) | Terms, acronyms, concepts used across the project | Onboarding, disambiguation |

## Spec Conventions

- **MUST** / **MUST NOT** — hard requirements (violation = bug)
- **SHOULD** / **SHOULD NOT** — strong recommendations (violation needs justification)
- **MAY** — optional behavior
- Signatures use Python type hints exactly as in source
- File paths are relative to repo root unless prefixed with `~/`
