# Spec Quick Reference

> Read THIS file first. Then read ONLY the section you need from the linked spec.

## Which Spec Do I Need?

| If you're working on... | Read this | Section |
|------------------------|-----------|---------|
| **Anything** (first time) | [ARCHITECTURE.md](ARCHITECTURE.md) | §1-2 (Overview + Layers) |
| CLI commands, `voronoi init/demo/server` | [CLI.md](CLI.md) | §2-6 |
| Intent classification, `/voronoi` commands | [GATEWAY.md](GATEWAY.md) | §2 (Intent) |
| Telegram routing, command handlers | [GATEWAY.md](GATEWAY.md) | §3 (Router) |
| Free-text classification, greetings | [GATEWAY.md](GATEWAY.md) | §3 (Router — Free-Text Pipeline) |
| Conversation memory, chat context | [GATEWAY.md](GATEWAY.md) | §5 (Memory) |
| Knowledge recall, past findings | [GATEWAY.md](GATEWAY.md) | §6 (Knowledge) |
| Progress digests, track assessment | [GATEWAY.md](GATEWAY.md) | §8 (Progress) |\n| Mid-investigation Q&A, `/voronoi ask` | [GATEWAY.md](GATEWAY.md) | §8b (Ask Handler) |
| Report/manuscript/PDF generation | [GATEWAY.md](GATEWAY.md) | §9 (Report) |
| Telegram bridge, inline buttons, groups | [GATEWAY.md](GATEWAY.md) | §12 (Telegram Bridge) |
| Ops diagnostics via Telegram | [GATEWAY.md](GATEWAY.md) | §13 (Ops Commands) |
| Investigation queue, lifecycle | [SERVER.md](SERVER.md) | §2 (Queue) |
| Dispatcher, launching agents | [SERVER.md](SERVER.md) | §3 (Dispatcher) |
| Progress monitoring, phase detection | [SERVER.md](SERVER.md) | §3 (Dispatcher — Progress Polling) |
| Agent restart, abort, recovery | [SERVER.md](SERVER.md) | §3 (Dispatcher — Completion/Recovery) |
| Orchestrator prompt building | [SERVER.md](SERVER.md) | §4 (Prompt) |
| Workspace provisioning, cloning | [SERVER.md](SERVER.md) | §5 (Workspace) |
| Docker sandbox isolation | [SERVER.md](SERVER.md) | §6 (Sandbox) |
| Server config, env vars | [SERVER.md](SERVER.md) | §7 (Config) |
| Rigor gates, which gates when | [SCIENCE.md](SCIENCE.md) | §2 (Gate Matrix) |
| Pre-registration, belief maps | [SCIENCE.md](SCIENCE.md) | §3-4 |
| Convergence detection | [SCIENCE.md](SCIENCE.md) | §5 |
| EVA (experiment validity) | [SCIENCE.md](SCIENCE.md) | §8 |
| Metric contracts, baselines | [SCIENCE.md](SCIENCE.md) | §9 |
| Anti-fabrication checks | [SCIENCE.md](SCIENCE.md) | §10 |
| Agent roles, who does what | [AGENT-ROLES.md](AGENT-ROLES.md) | §1-3 |
| Verify loop protocol | [AGENT-ROLES.md](AGENT-ROLES.md) | §4 |
| Any dataclass or schema | [DATA-STRUCTURES.md](DATA-STRUCTURES.md) | §1-5 (by layer) |
| `.swarm/` file formats | [DATA-STRUCTURES.md](DATA-STRUCTURES.md) | §7 |
| Beads note conventions | [DATA-STRUCTURES.md](DATA-STRUCTURES.md) | §9 |
| End-to-end workflow | [WORKFLOWS.md](WORKFLOWS.md) | §2-5 (by mode) |
| Telegram messaging experience | [WORKFLOWS.md](WORKFLOWS.md) | §7 (Telegram) |
| Context management, memory tiers | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §2-3 |
| Orchestrator checkpoint | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §4 |
| Targeted Beads queries | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §5 |
| Code-assembled worker prompts | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §6 |
| Per-agent context budget | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §3 |
| System rules, code review | [INVARIANTS.md](INVARIANTS.md) | All (41 invariants) |
| Worker self-verification protocol | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §8 |
| Token budget tracking | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §9 |
| Structured event log | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §10 |
| Human review gates (Scientific+) | [SCIENCE.md](SCIENCE.md) | §5 (Convergence) |
| Claim Ledger, provenance, objections | [SCIENCE.md](SCIENCE.md) | §17 (Claim Ledger) |
| Iterative science, review/continue | [WORKFLOWS.md](WORKFLOWS.md) | §9 (Multi-Run Iteration) |
| Structured evaluator feedback | [SCIENCE.md](SCIENCE.md) | §5 (Convergence) |
| Hybrid BM25+keyword search | [GATEWAY.md](GATEWAY.md) | §6 (Knowledge) |
| Term definitions | [GLOSSARY.md](GLOSSARY.md) | — |

## How to Use Specs

1. Read this index to find the right spec + section
2. Read ONLY that section (use line ranges, not the whole file)
3. If you need a dataclass signature → check DATA-STRUCTURES.md
4. If you're unsure about a rule → check INVARIANTS.md
5. If a term is unclear → check GLOSSARY.md

## Module → Spec → Test Mapping

> **Single source of truth.** All instruction files, agents, and skills reference
> this table instead of maintaining their own copies. If you add a module, add a
> row here — everything else discovers it automatically.

| Source file | Spec | Section | Test file(s) |
|-------------|------|---------|--------------|
| `src/voronoi/cli.py` | CLI.md | §2-6 | `test_cli.py` |
| `src/voronoi/beads.py` | ARCHITECTURE.md | §5 | `test_beads.py` |
| `src/voronoi/utils.py` | *(shared utilities)* | — | `test_utils.py` |
| `src/voronoi/gateway/intent.py` | GATEWAY.md | §2 | `test_intent.py` |
| `src/voronoi/gateway/router.py` | GATEWAY.md | §3 | `test_bridge.py` |
| `src/voronoi/gateway/handlers_query.py` | GATEWAY.md | §3 | `test_bridge.py` |
| `src/voronoi/gateway/handlers_mutate.py` | GATEWAY.md | §3 | `test_bridge.py` |
| `src/voronoi/gateway/handlers_workflow.py` | GATEWAY.md | §3 | `test_bridge.py` |
| `src/voronoi/gateway/config.py` | GATEWAY.md | §4 | `test_config.py` |
| `src/voronoi/gateway/memory.py` | GATEWAY.md | §5 | `test_memory.py` |
| `src/voronoi/gateway/knowledge.py` | GATEWAY.md | §6 | `test_knowledge.py` |
| `src/voronoi/gateway/literature.py` | GATEWAY.md | §7 | `test_literature.py` |
| `src/voronoi/gateway/progress.py` | GATEWAY.md | §8 | `test_progress.py` |
| `src/voronoi/gateway/report.py` | GATEWAY.md | §9 | `test_report.py` |
| `src/voronoi/gateway/evidence.py` | GATEWAY.md | §9 | `test_report.py` |
| `src/voronoi/gateway/pdf.py` | GATEWAY.md | §9 | `test_report.py` |
| `src/voronoi/gateway/codename.py` | GATEWAY.md | §10 | `test_codename.py` |
| `src/voronoi/gateway/handoff.py` | GATEWAY.md | §11 | `test_handoff.py` |
| `src/voronoi/data/scripts/telegram-bridge.py` | GATEWAY.md | §12 | — |
| `src/voronoi/data/scripts/dashboard.py` | CLI.md | — | — |
| `src/voronoi/server/queue.py` | SERVER.md | §2 | `test_queue.py` |
| `src/voronoi/server/dispatcher.py` | SERVER.md | §3 | `test_dispatcher.py` |
| `src/voronoi/server/tmux.py` | SERVER.md | §3 | `test_dispatcher.py` |
| `src/voronoi/server/snapshot.py` | SERVER.md | §3 | `test_snapshot.py` |
| `src/voronoi/server/prompt.py` | SERVER.md | §4 | `test_unified_prompt.py`, `test_worker_prompt.py` |
| `src/voronoi/server/workspace.py` | SERVER.md | §5 | `test_workspace.py` |
| `src/voronoi/server/sandbox.py` | SERVER.md | §6 | `test_sandbox.py` |
| `src/voronoi/server/runner.py` | SERVER.md | §7 | `test_runner.py` |
| `src/voronoi/server/events.py` | CONTEXT-MANAGEMENT.md | §10 | `test_events.py` |
| `src/voronoi/server/publisher.py` | SERVER.md | §8 | `test_publisher.py` |
| `src/voronoi/server/repo_url.py` | SERVER.md | §9 | `test_repo_url.py` |
| `src/voronoi/server/compact.py` | CONTEXT-MANAGEMENT.md | §12 | `test_compact.py` |
| `src/voronoi/science/claims.py` | SCIENCE.md | §16 | `test_claims.py` |
| `src/voronoi/science/gates.py` | SCIENCE.md | §2, §10 | `test_science.py` |
| `src/voronoi/science/convergence.py` | SCIENCE.md | §5 | `test_science.py` |
| `src/voronoi/science/fabrication.py` | SCIENCE.md | §11 | `test_science.py` |
| `src/voronoi/science/consistency.py` | SCIENCE.md | — | `test_science.py` |
| `src/voronoi/mcp/server.py` | ARCHITECTURE.md | §8 | `test_mcp.py` |
| `src/voronoi/mcp/tools_beads.py` | ARCHITECTURE.md | §8 | `test_mcp.py` |
| `src/voronoi/mcp/tools_swarm.py` | ARCHITECTURE.md | §8 | `test_mcp.py` |
| `src/voronoi/mcp/validators.py` | ARCHITECTURE.md | §8 | `test_mcp.py` |
