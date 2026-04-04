---
name: voronoi-design-decisions
description: "Use when brainstorming Voronoi design, reviewing architecture, or proposing changes. Contains load-bearing decisions, rejected alternatives, known weak spots, and cross-cutting constraints. Prevents re-proposing ideas that were already tried and rejected."
---

# Voronoi Design Decisions — Institutional Memory

## Why This File Exists

This is Voronoi's design memory. Before proposing any architectural change, check whether it was already considered and rejected. Before touching a load-bearing decision, understand why it exists.

---

## 1. Load-Bearing Decisions (Do Not Change Without Very Good Reason)

### Single Prompt Source of Truth (INV-01)
**Decision**: `prompt.py:build_orchestrator_prompt()` is the ONLY prompt builder. CLI and Telegram both call it.
**Why**: Ensures identical agent behavior regardless of entry point. Role files live on disk; prompt builder references them ("read this file NOW") instead of inlining.
**What breaks if violated**: CLI and Telegram agents diverge silently.

### File-Mediated State (INV-04) — `.swarm/` Files
**Decision**: ALL orchestrator state externalized to `.swarm/` files between OODA cycles.
**Why**: Without this, context compaction (`/compact`) destroys critical decisions. Checkpoint survives because it's on disk, not in context. Read at cycle start costs ~300 tokens to restore full state.
**What breaks if violated**: Orchestrator loses strategic context after compaction; 30h investigations restart from scratch.

### Three Nested Loops
**Decision**: Outer (dispatcher, Python) → Middle (orchestrator, LLM) → Inner (worker verify, LLM).
**Why**: Outer loop is reliable/deterministic, never loses state. Middle loop is creative but needs external memory. Inner loop is fast/focused/autonomous. Collapsing to two loops puts reliability + creativity in the same LLM, which loses context.
**What breaks if violated**: Context explosion, no restart recovery, no worker autonomy.

### Role Files Are Source of Truth (INV-02)
**Decision**: Agent roles live ONLY in `src/voronoi/data/agents/*.agent.md`. Python references, never copies.
**Why**: Copilot CLI auto-discovers `.github/agents/`. Prompt builder says "read this file" (~20 tokens) vs inlining the role (~2K tokens × 30 dispatches = 60K wasted tokens).
**What breaks if violated**: Role drift between .agent.md and Python strings; 450K token overhead observed in real investigation.

### Orchestrator Never Enters Worktrees (INV-03)
**Decision**: Dispatch and monitor only. If agent fails, dispatch a new agent (e.g., Methodologist).
**Why**: Prevents "therapist agent" syndrome — orchestrator tries to debug everything, loses strategic direction. Observed: orchestrator wrote 240+ lines of code inline during inv-1 (anti-pattern).
**What breaks if violated**: Orchestrator becomes a debugger, burns context on implementation instead of strategy.

### Adaptive Rigor for DISCOVER, Fixed for PROVE
**Decision**: DISCOVER starts at analytical rigor, escalates when hypotheses crystallize. PROVE starts at scientific/experimental from the start.
**Why**: Real science is iterative. You don't pre-register before you know what you're looking at.
**What breaks if violated**: Premature rigor gates kill exploratory serendipity; missing rigor gates let bad science through.

### Baseline-First Gate (INV-09)
**Decision**: First subtask is ALWAYS a baseline measurement. All experiments blocked until baseline completes.
**Why**: Without baseline, "30% improvement" has no denominator. All results become incomparable.
**Cost**: ~15 min overhead per investigation. Worth it.

### Atomic Queue Claiming (INV-06)
**Decision**: `next_ready()` marks investigation as `running` in the same transaction as SELECT.
**Why**: Prevents double-dispatch under concurrent access (Telegram + CLI). Two lines of code for atomicity.
**What breaks if violated**: Race condition; two dispatchers grab the same investigation.

---

## 2. Rejected Alternatives (Already Tried or Considered)

| Proposal | Why Rejected | Lesson |
|----------|-------------|--------|
| Seven-mode matrix (BUILD/INVESTIGATE/EXPLORE/HYBRID × 4 rigor) | Artificial distinctions. "Figure out why X is slow" doesn't fit cleanly. | Two modes (DISCOVER/PROVE) + adaptive rigor is simpler and handles all cases. |
| Separate prompt builders for CLI vs Telegram | Behavior divergence within weeks. | Single source of truth is non-negotiable. |
| Store roles in Python code / dataclass fields | Unmaintainable duplication. Copilot CLI can't auto-discover. | Keep `.agent.md` files; prompt builder references them. |
| Orchestrator sleep-polling for worker completion | 15+ cycles observed in inv-1. Burns 30%+ of context for zero information. | Exit cleanly after dispatch. Dispatcher polls externally. |
| Orchestrator writes worker code inline | 240+ lines of `encoder.py` during inv-1. Context burned, strategic focus lost. | Never >20 lines inline. Delegate to workers. |
| `bd list --json` for cycle events | Returns ALL tasks (50+ with notes = 10–25K tokens). | Use targeted `bd query "status!=closed AND updated>30m"` (500–2K tokens). |
| Keep state only in conversation context | Restart read 17 files (790K tokens) to produce 7K output. 99% read, 1% work. | Checkpoint-first: externalize to disk, read ~300 tokens at cycle start. |
| Simulator/mock data bypass | Temptation to replace real LLM calls with fake data. | INV-16: Fewer real data points > any number of fake ones. |
| Redis/in-memory store for state | Faster, cleaner API — but requires external infrastructure. | Files are boring, reliable, don't need setup. Concurrent access is rare. |
| Two-loop system (drop dispatcher) | Collapses reliability onto orchestrator, which loses context under pressure. | Three loops: Python for reliability, LLM for strategy, LLM for focus. |

---

## 3. Known Weak Spots

| Area | Problem | Severity | Location |
|------|---------|----------|----------|
| Resume prompt ambiguity | Checkpoint may say `phase=converged, 7/13 met` while `success-criteria.json` says `0/13 met` during restart. False failure loops. | High | `dispatcher.py:_build_resume_prompt()` |
| Sentinel audit enforcement | INV-40 says "cannot be bypassed" but nothing structurally prevents orchestrator from deleting `sentinel-audit.json`. | Medium | `dispatcher.py` / `science.py` |
| Beads vs Investigation granularity | Different update semantics. Beads doesn't track investigation-level state. Can cause stale progress digests. | Medium | `queue.db` (global) vs `.beads/` (per-workspace) |
| Context thresholds vs actual overflow | Stated overflow risk is 6–10h, but thresholds fire at 12h/20h/28h. Advisory only. | Medium | `dispatcher.py` |
| Convergence failure classification | `blocked` status isn't persisted to `convergence.json`. On restart, orchestrator may not know it's blocked. | Medium | `dispatcher.py:check_convergence()` |
| Paradigm stress threshold | Count contradictions ≥ 3 → flag. No principled threshold. May miss subtle tensions or false-trigger. | Low | `swarm-orchestrator.agent.md` |
| Sleep-polling enforcement | Anti-sleep-polling rule is in prompt, not structural. LLM can ignore it. | Low | `prompt.py` |

---

## 4. Cross-Cutting Constraints (Must Change Together)

When changing any item in the left column, ALL components in the right column must be updated in the same commit:

| If You Change | Also Update |
|---------------|-------------|
| Checkpoint schema | `OrchestratorCheckpoint` dataclass, `prompt.py` (injection), dispatcher resume logic, tests |
| Belief map schema | `CONFIDENCE_TIERS`, orchestrator + investigator prompts, MCP tool schema, convergence logic, tests |
| Role registry (add/remove role) | `.agent.md` file, `prompt.py` role mapping, `swarm-orchestrator.agent.md` role table, activation matrix in AGENT-ROLES.md, tests |
| Rigor levels | `Science.rigor`, gate matrix (SCIENCE.md), convergence criteria, agent prompts, intent classifier, dispatcher, tests |
| `.swarm/` file formats | Science loader, dispatcher recovery, compact.py, MCP tools, checkpoint format, tests |
| Investigation state machine | State enum in `queue.py`, dispatcher transitions, API handlers, progress reporting, Telegram messaging, tests |
| Pre-registration fields | `PreRegistration` dataclass, investigator prompt, MCP tool, validator logic, convergence gate, tests |
| Convergence thresholds | `convergence.py`, dispatcher completion, orchestrator prompts, evaluator scoring, tests |
| Artifact contract rules | Worker prompt, verify loop, merge-agent.sh, dispatcher merge gate, INV-19/20/21, tests |
| Verify loop iterations | `build_worker_prompt()`, dispatcher retry logic, verify log schemas, escalation thresholds |

---

## 5. Design Tensions (Understood Trade-Offs)

| Tension | Why Not Simplified | Accepted Cost |
|---------|-------------------|---------------|
| Three loops vs one | One loop = context explosion + no recovery | Inter-loop handoff complexity |
| Checkpoint + code-assembled workers | Skipping = 600K cumulative tokens | ~1.5K LOC in prompt.py + science/ |
| Belief map + experiments.tsv + Beads findings (3 files) | Consolidated = 50+ task dump per read | Three files to maintain |
| Plan review gate (Analytical+) | Skip = orchestrator makes preventable design errors | ~15–30 min overhead |
| File-mediated state vs Redis | Redis needs infrastructure in every investigation workspace | Slower than Redis (but concurrent access is rare) |
