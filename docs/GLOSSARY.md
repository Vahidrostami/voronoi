# Glossary

> Terms, acronyms, and concepts used across the Voronoi project.

**TL;DR**: Quick definitions for all Voronoi-specific terms: roles, workflows, science concepts, infrastructure, artifact contracts, signals. Check here if any term in the specs is unclear.

## Roles & Agents

| Term | Definition |
|------|-----------|
| **Orchestrator** | The central agent running the OODA loop. Lives in the main workspace, dispatches workers, monitors convergence. |
| **Worker** | Any agent running in a git worktree. Includes Builder, Investigator, Scout, etc. |
| **Builder** | Worker agent that implements code. Verify: tests + lint + PRODUCES. |
| **Scout** | Worker that researches prior knowledge and SOTA before investigation. |
| **Investigator** | Worker that runs pre-registered experiments with raw data and EVA. |
| **Explorer** | Worker that evaluates options with comparison matrices. |
| **Statistician** | Review agent that independently recomputes statistics from raw data. |
| **Critic** | Adversarial review agent. Partially blinded at Scientific+ rigor. |
| **Synthesizer** | Agent that assembles claim-evidence registry and deliverable. |
| **Evaluator** | Scores the deliverable using CCSA formula. |
| **Theorist** | Builds causal models and detects paradigm stress. Scientific+ only. |
| **Methodologist** | Reviews experimental designs and conducts power analysis. Scientific+ only. |

## Workflows & Modes

| Term | Definition |
|------|-----------|
| **Mode** | The type of workflow: BUILD, INVESTIGATE, EXPLORE, HYBRID, STATUS, RECALL, GUIDE. |
| **Rigor Level** | The depth of scientific gates: STANDARD, ANALYTICAL, SCIENTIFIC, EXPERIMENTAL. |
| **OODA Loop** | Observe → Orient → Decide → Act. The orchestrator's deliberate outer loop. |
| **Inner Loop** | Per-agent fast loop: Execute → Verify → Retry. Handles execution errors. |
| **Outer Loop** | Orchestrator's OODA cycle. Handles strategic decisions. |
| **Verify Loop** | The inner loop's test-lint-artifact check cycle with retry. |

## Science Framework

| Term | Definition |
|------|-----------|
| **Pre-Registration** | Locking down experimental design before execution to prevent post-hoc rationalization. |
| **Belief Map** | Tracks hypothesis probabilities across OODA cycles. Drives information-gain prioritization. |
| **Convergence** | Determination that an investigation is complete. Criteria vary by rigor level. |
| **Paradigm Stress** | Findings contradict the working theory — valuable signal that mental model needs revision. |
| **EVA** | Experimental Validity Audit — catches experiments that run but don't test what they claim. |
| **DESIGN_INVALID** | EVA flag indicating the experiment's independent variable wasn't actually varied. |
| **Metric Contract** | Structured agreement between orchestrator and worker about success criteria. |
| **Baseline-First** | Hard gate: every investigation starts with a baseline measurement before any experiments. |
| **Claim-Evidence** | Traceability registry mapping deliverable claims to specific finding IDs. |
| **Finding** | A structured experimental result with effect size, CI, N, stat test, and data hash. |
| **CCSA** | Evaluator scoring formula: Completeness, Coherence, Strength, Actionability. |

## Infrastructure

| Term | Definition |
|------|-----------|
| **Beads (bd)** | Dependency-aware task tracking tool. Dolt-backed. Used for all task management. |
| **Worktree** | Git worktree — isolated working directory sharing `.git` with the main repo. |
| **tmux** | Terminal multiplexer. Each agent runs in its own tmux window. |
| **`.swarm/`** | Directory containing orchestrator state files (belief map, journal, deliverable, etc.). |
| **`.github/`** | Directory containing agent roles, prompts, and skills. Copilot auto-discovers these. |
| **Dispatcher** | Server component that polls queue, provisions workspaces, launches agents, monitors progress. |
| **Queue** | SQLite-backed investigation lifecycle manager (`queue.db`). |
| **Sandbox** | Docker container providing execution isolation per investigation. |
| **Codename** | Brain-themed name assigned to each investigation (Dopamine, Serotonin, etc.). |

## Artifact Contracts

| Term | Definition |
|------|-----------|
| **PRODUCES** | Files a task MUST create before closing. |
| **REQUIRES** | Files that MUST exist before a task starts. |
| **GATE** | Validation file that must exist AND contain PASS before work begins. |

## Anti-Fabrication

| Term | Definition |
|------|-----------|
| **Anti-Fabrication** | System for detecting fabricated results: checks data files, hashes, scripts, patterns. |
| **Anti-Simulation** | Gate preventing substitution of real experiments with random number generators. |
| **Data Hash** | SHA-256 hash of raw data files, computed immediately after collection. |

## File Formats

| Term | Definition |
|------|-----------|
| **Experiment Ledger** | `.swarm/experiments.tsv` — append-only TSV of all experiment attempts. |
| **Lab Notebook** | `.swarm/lab-notebook.json` — narrative continuity across OODA cycles. |
| **Strategic Context** | `.swarm/strategic-context.md` — decision rationale, dead ends, remaining gaps. |
| **Journal** | `.swarm/journal.md` — investigation journal. |
| **Verify Log** | `.swarm/verify-log-<id>.jsonl` — per-task iteration history for verify loop. |

## Signals & Events

| Term | Definition |
|------|-----------|
| **VERIFY_EXHAUSTED** | Worker used all retry attempts without passing verification. |
| **BUILD_COMPLETE** | Builder's completion promise — tests pass, lint clean, PRODUCES verified. |
| **EXPERIMENT_COMPLETE** | Investigator's completion promise — passed EVA, data committed. |
| **SCOUT_COMPLETE** | Scout's completion promise — brief written, sources cited. |
| **REVIEW_COMPLETE** | Critic's completion promise — all checklist items evaluated. |
| **SYNTHESIS_COMPLETE** | Synthesizer's completion promise — registry complete, no orphans. |
| **PARADIGM_STRESS** | Active contradictions between findings and working theory. |
| **DIMINISHING_RETURNS** | Last 2 improvement rounds improved < 5% each — deliver as-is. |
| **SERENDIPITY:HIGH** | Unexpected discovery flagged for attention. |
| **PRE_REG_DEVIATION** | Deviation from pre-registered design — must be documented. |
| **STRATEGIC_MISALIGNMENT** | Task assumptions no longer hold. |

## Abbreviations

| Abbr | Full |
|------|------|
| bd | Beads (task tracker) |
| CI | Confidence Interval |
| EVA | Experimental Validity Audit |
| CCSA | Completeness, Coherence, Strength, Actionability |
| OODA | Observe, Orient, Decide, Act |
| SOTA | State of the Art |
| EWC | Elastic Weight Consolidation |
| CLS | Complementary Learning Systems |
| WAL | Write-Ahead Logging (SQLite) |
