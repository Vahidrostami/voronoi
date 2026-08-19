# Spec Quick Reference

> Read THIS file first. Then read ONLY the **Lines** range for your row — never the whole spec.

## Which Spec Do I Need?

> The **Lines** column is the exact range to pass to a file read. It is verified by
> `python scripts/check-spec-index.py` — do not hand-edit it without rerunning that.

| If you're working on... | Read this | Section | Lines |
|------------------------|-----------|---------|-------|
| **Anything** (first time) | [ARCHITECTURE.md](ARCHITECTURE.md) | §1-2 (Overview + Layers) | L7-L115 |
| CLI commands, `voronoi init/demo/server` | [CLI.md](CLI.md) | §2-6 | L15-L214 |
| Intent classification, `/voronoi` commands | [GATEWAY.md](GATEWAY.md) | §2 (Intent) | L29-L106 |
| Telegram routing, command handlers | [GATEWAY.md](GATEWAY.md) | §3 (Router) | L107-L208 |
| Free-text classification, greetings | [GATEWAY.md](GATEWAY.md) | §3 (Router — Free-Text Pipeline) | L107-L208 |
| Conversation memory, chat context | [GATEWAY.md](GATEWAY.md) | §5 (Memory) | L245-L297 |
| Knowledge recall, past findings | [GATEWAY.md](GATEWAY.md) | §6 (Knowledge) | L298-L369 |
| Progress digests, track assessment | [GATEWAY.md](GATEWAY.md) | §8 (Progress) | L401-L567 |
| Mid-investigation Q&A, `/voronoi ask` | [GATEWAY.md](GATEWAY.md) | §8b (Ask Handler) | L568-L654 |
| Report/manuscript/PDF generation | [GATEWAY.md](GATEWAY.md) | §9 (Report) | L655-L732 |
| Telegram bridge, inline buttons, groups | [GATEWAY.md](GATEWAY.md) | §12 (Telegram Bridge) | L790-L860 |
| Ops diagnostics via Telegram | [GATEWAY.md](GATEWAY.md) | §13 (Ops Commands) | L861-L903 |
| Investigation queue, lifecycle | [SERVER.md](SERVER.md) | §2 (Queue) | L35-L188 |
| Dispatcher, launching agents | [SERVER.md](SERVER.md) | §3 (Dispatcher — API + Lifecycle) | L377-L405 |
| Progress monitoring, phase detection | [SERVER.md](SERVER.md) | §3 (Dispatcher — Progress Polling) | L406-L432, L522-L536 |
| Agent restart, abort, recovery | [SERVER.md](SERVER.md) | §3 (Dispatcher — Completion/Recovery) | L580-L658 |
| Orchestrator prompt building | [SERVER.md](SERVER.md) | §4 (Prompt) | L659-L766 |
| Workspace provisioning, cloning | [SERVER.md](SERVER.md) | §5 (Workspace) | L767-L854 |
| Docker sandbox isolation | [SERVER.md](SERVER.md) | §6 (Sandbox) | L855-L917 |
| Server config, env vars | [SERVER.md](SERVER.md) | §7 (Config) | L918-L971 |
| Rigor gates, which gates when | [SCIENCE.md](SCIENCE.md) | §2 (Gate Matrix) | L27-L49 |
| Pre-registration, belief maps | [SCIENCE.md](SCIENCE.md) | §3-4 | L50-L179 |
| Convergence detection | [SCIENCE.md](SCIENCE.md) | §5 | L180-L335 |
| EVA (experiment validity) | [SCIENCE.md](SCIENCE.md) | §8 | L390-L439 |
| Metric contracts, baselines | [SCIENCE.md](SCIENCE.md) | §9 | L440-L499 |
| Experiment Sentinel | [SCIENCE.md](SCIENCE.md) | §10 | L500-L634 |
| Anti-fabrication checks | [SCIENCE.md](SCIENCE.md) | §11 | L635-L688 |
| Locked-claim schema, PROVE question-locking, fidelity gate | [SCIENCE.md](SCIENCE.md) | §24 | L1332-L1499 |
| Agent roles, who does what | [AGENT-ROLES.md](AGENT-ROLES.md) | §1-3 | L7-L355 |
| Verify loop protocol | [AGENT-ROLES.md](AGENT-ROLES.md) | §4 | L356-L402 |
| Any dataclass or schema | [DATA-STRUCTURES.md](DATA-STRUCTURES.md) | §1-5 (by layer) | L7-L524 |
| `.swarm/` file formats | [DATA-STRUCTURES.md](DATA-STRUCTURES.md) | §7 | L585-L1089 |
| Beads note conventions | [DATA-STRUCTURES.md](DATA-STRUCTURES.md) | §9 | L1168-L1265 |
| End-to-end workflow | [WORKFLOWS.md](WORKFLOWS.md) | §2-4 (by mode) | L20-L211 |
| Telegram messaging experience | [WORKFLOWS.md](WORKFLOWS.md) | §7 (Telegram) | L212-L304 |
| Context management, memory tiers | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §2-3 | L11-L72 |
| Orchestrator checkpoint | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §4 | L73-L147 |
| Targeted Beads queries | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §5 | L148-L168 |
| Code-assembled worker prompts | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §6 | L169-L219 |
| Per-agent context budget | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §3 | L32-L72 |
| System rules, code review | [INVARIANTS.md](INVARIANTS.md) | All (64 invariants) | L1-L279 |
| Worker self-verification protocol | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §8 | L229-L251 |
| Token budget tracking | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §9 | L252-L268 |
| Structured event log | [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) | §10 | L269-L287 |
| Human review gates (Scientific+) | [SCIENCE.md](SCIENCE.md) | §5 (Convergence) | L180-L335 |
| Claim Ledger, provenance, objections | [SCIENCE.md](SCIENCE.md) | §17 (Claim Ledger) | L815-L925 |
| Directional verification, triviality | [SCIENCE.md](SCIENCE.md) | §18 (Interpretation) | L926-L1020 |
| Judgment Tribunal, tribunal verdicts | [SCIENCE.md](SCIENCE.md) | §18 (Interpretation) | L926-L1020 |
| Continuation proposals | [SCIENCE.md](SCIENCE.md) | §18 (Interpretation) | L926-L1020 |
| Run Manifest, structured deliverable | [MANIFEST.md](MANIFEST.md) | — | L1-L304 |
| Run Manifest source-of-truth map, validation | [SCIENCE.md](SCIENCE.md) | §19 (Run Manifest) | L1021-L1065 |
| `.swarm/run-manifest.json` format | [DATA-STRUCTURES.md](DATA-STRUCTURES.md) | §7 (run-manifest) | L1007-L1045 |
| Deliberation mode | [GATEWAY.md](GATEWAY.md) | §14 (Deliberation) | L904-L941 |
| Iterative science, review/continue | [WORKFLOWS.md](WORKFLOWS.md) | §10 (Multi-Run Iteration) | L423-L506 |
| Structured evaluator feedback | [SCIENCE.md](SCIENCE.md) | §5 (Convergence) | L180-L335 |
| Hybrid BM25+keyword search | [GATEWAY.md](GATEWAY.md) | §6 (Knowledge) | L298-L369 |
| Term definitions | [GLOSSARY.md](GLOSSARY.md) | — | L1-L127 |
| Paper-track manuscript production (Outliner, Lit-Synth, Figure-Critic, Refiner) | [AGENT-ROLES.md](AGENT-ROLES.md) | §2-3 (Paper-track) | L31-L53, L283-L355 |
| Citation-coverage gate (≥0.90 integration, zero orphans) | [SCIENCE.md](SCIENCE.md) | §20 (Citation Coverage) | L1066-L1134 |
| Evidence-gated epoch scaling, adaptive agent cap | [SCIENCE.md](SCIENCE.md) | §21 (Epoch Scaling) | L1135-L1188 |
| Structured failure diagnosis, continuation diagnostics | [SCIENCE.md](SCIENCE.md) | §22 (Failure Diagnosis) | L1189-L1234 |
| `.swarm/epoch-state.json` format | [SCIENCE.md](SCIENCE.md) | §21 | L1135-L1188 |
| `.swarm/failure-diagnosis.json` format | [SCIENCE.md](SCIENCE.md) | §22 | L1189-L1234 |
| `/voronoi paper <codename>` manuscript command | [GATEWAY.md](GATEWAY.md) | §3 (Router) | L107-L208 |
| `.swarm/manuscript/` state contract | [DATA-STRUCTURES.md](DATA-STRUCTURES.md) | §7 (manuscript) | L699-L809 |

## How to Use Specs

1. Read this index to find the right spec + section
2. Read ONLY the **Lines** range for that row — never the whole file
3. If you need a dataclass signature → check DATA-STRUCTURES.md
4. If you're unsure about a rule → check INVARIANTS.md
5. If a term is unclear → check GLOSSARY.md

## Module → Spec → Test Mapping

> **Single source of truth.** All instruction files, agents, and skills reference
> this table instead of maintaining their own copies. If you add a module, add a
> row here — everything else discovers it automatically.

| Source file | Spec | Section | Lines | Test file(s) |
|-------------|------|---------|-------|--------------|
| `src/voronoi/cli.py` | CLI.md | §2-6 | L15-L214 | `test_cli.py`, `test_server_cli.py` |
| `src/voronoi/beads.py` | ARCHITECTURE.md | §5 | L203-L223 | `test_beads.py` |
| `src/voronoi/utils.py` | *(shared utilities)* | — | — | `test_utils.py` |
| `src/voronoi/gateway/intent.py` | GATEWAY.md | §2 | L29-L106 | `test_intent.py` |
| `src/voronoi/gateway/router.py` | GATEWAY.md | §3 | L107-L208 | `test_bridge.py` |
| `src/voronoi/gateway/handlers_query.py` | GATEWAY.md | §3 | L107-L208 | `test_bridge.py` |
| `src/voronoi/gateway/handlers_mutate.py` | GATEWAY.md | §3 | L107-L208 | `test_bridge.py` |
| `src/voronoi/gateway/handlers_workflow.py` | GATEWAY.md | §3 | L107-L208 | `test_bridge.py` |
| `src/voronoi/gateway/config.py` | GATEWAY.md | §4 | L209-L244 | `test_config.py` |
| `src/voronoi/gateway/memory.py` | GATEWAY.md | §5 | L245-L297 | `test_memory.py` |
| `src/voronoi/gateway/knowledge.py` | GATEWAY.md | §6 | L298-L369 | `test_knowledge.py` |
| `src/voronoi/gateway/literature.py` | GATEWAY.md | §7 | L370-L400 | `test_literature.py` |
| `src/voronoi/gateway/progress.py` | GATEWAY.md | §8 | L401-L567 | `test_progress.py` |
| `src/voronoi/gateway/report.py` | GATEWAY.md | §9 | L655-L732 | `test_report.py` |
| `src/voronoi/gateway/evidence.py` | GATEWAY.md | §9 | L655-L732 | `test_report.py` |
| `src/voronoi/gateway/pdf.py` | GATEWAY.md | §9 | L655-L732 | `test_report.py` |
| `src/voronoi/gateway/codename.py` | GATEWAY.md | §10 | L733-L752 | `test_codename.py` |
| `src/voronoi/gateway/handoff.py` | GATEWAY.md | §11 | L753-L789 | `test_handoff.py` |
| `src/voronoi/data/scripts/telegram-bridge.py` | GATEWAY.md | §12 | L790-L860 | — |
| `src/voronoi/data/scripts/dashboard.py` | CLI.md | — | — | — |
| `src/voronoi/data/scripts/spawn-agent.sh` | ARCHITECTURE.md | §6 | L224-L281 | `test_runtime_scripts.py` |
| `src/voronoi/data/scripts/merge-agent.sh` | ARCHITECTURE.md | §6 | L224-L281 | `test_runtime_scripts.py` |
| `src/voronoi/data/scripts/health-check.sh` | ARCHITECTURE.md | §6b | L282-L313 | `test_health_check.py` |
| `src/voronoi/server/queue.py` | SERVER.md | §2 | L35-L188 | `test_queue.py` |
| `src/voronoi/server/dispatcher/_launch.py` | SERVER.md | §3 | L396-L405 | `test_dispatcher.py` |
| `src/voronoi/server/dispatcher/_recovery.py` | SERVER.md | §3 | L595-L658 | `test_dispatcher.py` |
| `src/voronoi/server/dispatcher/_progress.py` | SERVER.md | §3 | L406-L432 | `test_dispatcher.py` |
| `src/voronoi/server/dispatcher/_audits.py` | SERVER.md | §3 | L465-L498 | `test_dispatcher.py` |
| `src/voronoi/server/dispatcher/_stalls.py` | SERVER.md | §3 | L433-L464 | `test_dispatcher.py` |
| `src/voronoi/server/dispatcher/_liveness.py` | SERVER.md | §3 | L537-L559 | `test_dispatcher.py` |
| `src/voronoi/server/dispatcher/_completion.py` | SERVER.md | §3 | L560-L594 | `test_dispatcher.py` |
| `src/voronoi/server/tmux.py` | SERVER.md | §3 | L305-L344 | `test_dispatcher.py` |
| `src/voronoi/server/snapshot.py` | SERVER.md | §3 | L242-L304 | `test_snapshot.py` |
| `src/voronoi/server/prompt.py` | SERVER.md | §4 | L659-L766 | `test_unified_prompt.py`, `test_worker_prompt.py` |
| `src/voronoi/server/workspace.py` | SERVER.md | §5 | L767-L854 | `test_workspace.py` |
| `src/voronoi/server/sandbox.py` | SERVER.md | §6 | L855-L917 | `test_sandbox.py` |
| `src/voronoi/server/runner.py` | SERVER.md | §7 | L918-L971 | `test_runner.py` |
| `src/voronoi/server/events.py` | CONTEXT-MANAGEMENT.md | §10 | L269-L287 | `test_events.py` |
| `src/voronoi/server/publisher.py` | SERVER.md | §8 | L972-L994 | `test_publisher.py` |
| `src/voronoi/server/repo_url.py` | SERVER.md | §9 | L995-L1026 | `test_repo_url.py` |
| `src/voronoi/server/compact.py` | CONTEXT-MANAGEMENT.md | §12 | L379-L402 | `test_compact.py` |
| `src/voronoi/server/provenance.py` | SCIENCE.md / DATA-STRUCTURES.md | §17 / §7 | L815-L925 / L1046-L1089 | `test_provenance.py` |
| `src/voronoi/science/claims.py` | SCIENCE.md | §17 | L815-L925 | `test_claims.py` |
| `src/voronoi/science/gates.py` | SCIENCE.md | §2, §10 | L27-L49, L500-L634 | `test_science.py` |
| `src/voronoi/science/convergence.py` | SCIENCE.md | §5 | L180-L335 | `test_science.py` |
| `src/voronoi/science/fabrication.py` | SCIENCE.md | §11 | L635-L688 | `test_science.py` |
| `src/voronoi/science/consistency.py` | SCIENCE.md | §6-7 | L336-L389 | `test_science.py` |
| `src/voronoi/science/interpretation.py` | SCIENCE.md | §18 | L926-L1020 | `test_interpretation.py` |
| `src/voronoi/science/manifest.py` | SCIENCE.md / MANIFEST.md | §19 / all | L1021-L1065 / L1-L304 | `test_manifest.py` |
| `src/voronoi/science/citation_coverage.py` | SCIENCE.md | §20 | L1066-L1134 | `test_citation_coverage.py` |
| `src/voronoi/science/lab_kg.py` | SCIENCE.md | §23 | L1235-L1331 | `test_lab_kg.py` |
| `src/voronoi/science/locked_claim.py` | SCIENCE.md | §24 | L1332-L1499 | `test_locked_claim.py` |
| `src/voronoi/mcp/server.py` | ARCHITECTURE.md | §8 | L343-L416 | `test_mcp.py` |
| `src/voronoi/mcp/tools_beads.py` | ARCHITECTURE.md | §8 | L343-L416 | `test_mcp.py` |
| `src/voronoi/mcp/tools_swarm.py` | ARCHITECTURE.md | §8 | L343-L416 | `test_mcp.py` |
| `src/voronoi/mcp/validators.py` | ARCHITECTURE.md | §8 | L343-L416 | `test_mcp.py` |

## Cross-Cutting Tests

Tests that span several modules and so have no single row above. Every file in
`tests/` must appear either here or in the table above — enforced by
`tests/test_spec_index.py`.

| Test file | Covers |
|-----------|--------|
| `test_demo_pipeline.py` | End-to-end demo: Telegram → router → queue → dispatcher → workspace |
| `test_runtime_customizations.py` | Compatibility of shipped Copilot runtime customizations in `src/voronoi/data/` |
| `test_spec_index.py` | This index — module coverage, stale references, and `Lines` accuracy |
