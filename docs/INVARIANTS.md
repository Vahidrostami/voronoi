# System Invariants

> Rules that MUST never be violated. Reference during code review, debugging, and development.

**TL;DR**: 30 invariants. Key ones: prompt.py is sole prompt builder (INV-01). Roles only in .github/ files (INV-02). Orchestrator never enters worktrees (INV-03). Atomic queue claiming (INV-06). Rigor only escalates (INV-08). Baseline-first (INV-09). EVA before finding (INV-12). No simulation bypass (INV-16). Push before session end (INV-25).

## 1. Architectural Invariants

### INV-01: Single Prompt Source of Truth
`prompt.py` is the ONLY module that builds orchestrator prompts. CLI and Telegram MUST both call `build_orchestrator_prompt()`. No other module may construct prompts.

### INV-02: Role Files Are Source of Truth
Agent role definitions live ONLY in `.github/agents/*.agent.md`. The prompt builder REFERENCES these files (tells orchestrator "read this file"). Python code MUST NOT duplicate or inline role definitions.

### INV-03: Orchestrator Never Enters Worktrees
The orchestrator dispatches and monitors. It MUST NOT modify files in a worker's git worktree. If an agent fails, dispatch a new agent or a Methodologist — never fix the code directly.

### INV-04: File-Mediated State
Orchestrator state MUST be externalized to `.swarm/` files between OODA cycles. This prevents context loss on compaction. State that lives only in the orchestrator's context window = state that will be lost.

### INV-05: Communication Through Git + Beads Only
Agents MUST NOT use custom IPC, shared memory, sockets, or any other communication mechanism. All inter-agent communication flows through: git (code, data), Beads (tasks, findings), and `.swarm/` files (orchestrator state).

---

## 2. Queue Invariants

### INV-06: Atomic Queue Claiming
`next_ready()` MUST mark an investigation as `running` in the same transaction as the `SELECT`. This prevents double-dispatch under concurrent access. Uses `BEGIN IMMEDIATE`.

### INV-07: Investigation State Machine
Investigations MUST follow the state machine: `queued → running → {complete | failed | cancelled}`. No other transitions are valid. A `complete` investigation MUST NOT be re-queued.

---

## 3. Science Invariants

### INV-08: Adaptive Rigor (DISCOVER) / Fixed Rigor (PROVE)
In DISCOVER mode, rigor starts at analytical level and escalates dynamically when testable hypotheses emerge. The orchestrator CAN escalate rigor (analytical → scientific) but MUST NOT downgrade it once escalated. In PROVE mode, rigor is scientific or experimental from the start and MUST NOT be downgraded.

### INV-09: Baseline-First
Every investigation epic's first subtask MUST be a baseline measurement. All experimental tasks MUST be blocked until the baseline completes. No exceptions.

### INV-10: Pre-Registration Before Execution
At Scientific+ rigor, investigators MUST pre-register hypothesis, method, controls, and stat test BEFORE running experiments. Post-hoc deviations MUST be documented as `PRE_REG_DEVIATION`.

### INV-11: Raw Data Preservation
All raw data files MUST be committed to `data/raw/` with SHA-256 hash computed immediately after collection. Hash recorded in finding metadata. Data MUST NOT be summarized without preserving the source.

### INV-12: EVA Before Finding
At Analytical+ rigor, investigators MUST pass the Experimental Validity Audit (manipulation check + artifact check + sanity check) before committing a finding. `DESIGN_INVALID` findings MUST NOT enter the evidence store.

### INV-13: No Paradigm Stress at Convergence
At Scientific+ rigor, convergence MUST NOT be declared while paradigm stress is active. The orchestrator must either resolve contradictions or revise the working theory.

### INV-14: Statistician Independence
The Statistician MUST independently recompute statistics from raw data. NEVER trust agent-reported numbers alone. Every quantitative claim in a finding MUST include: effect size, confidence interval, sample size, and statistical test.

### INV-15: Claim-Evidence Traceability
At Analytical+ rigor, every claim in the deliverable MUST trace to specific finding IDs via `.swarm/claim-evidence.json`. Orphan findings and unsupported claims are audit flags.

---

## 4. Anti-Fabrication Invariants

### INV-16: No Simulation Bypass
MUST NOT create files that replace real LLM/tool calls with random sampling (`*sim*`, `*mock*`, `*fake*`). MUST NOT hardcode detection probabilities or effect sizes that the experiment is supposed to measure. Fewer real data points > any number of fake ones.

### INV-17: Experiment Scripts Committed
All experiment scripts MUST be committed to `experiments/` alongside raw data in `data/raw/`. Statistics MUST be computed programmatically — never manually reported.

### INV-18: Honest Failure Reporting
If an experiment fails, report honestly. MUST NOT re-run until a "nice" result appears. Negative results are equally valuable as positive results.

---

## 5. Artifact Contract Invariants

### INV-19: PRODUCES Verified Before Close
A task MUST NOT be closed until all files declared in `PRODUCES` actually exist on disk.

### INV-20: REQUIRES Checked Before Start
A worker MUST check `REQUIRES` at startup. If any required file is missing, report BLOCKED and STOP. Do not attempt to work without prerequisites.

### INV-21: GATE Validates Before Start
If a task declares `GATE`, the validation file MUST exist AND contain PASS verdicts before work begins.

---

## 6. Verify Loop Invariants

### INV-22: Inner Before Outer
Workers MUST exhaust their internal verify loop (test, lint, artifact checks) before escalating to the orchestrator. The orchestrator should not see individual test failures — only "complete" or "exhausted after N attempts."

### INV-23: Verify Logs Persisted
Every verify iteration MUST be logged to `.swarm/verify-log-<task-id>.jsonl`. This provides structured diagnostics if the agent fails.

### INV-24: Context Management
Error output MUST be summarized before re-injection into the verify loop (last 50 lines, not full output). Previous attempt logs referenced by file path, not pasted inline.

### INV-24b: Worker Self-Verification Before Close
A worker MUST run the self-verification protocol (test loop + produces check + metric consistency check) before closing any task. Workers that skip verification MUST NOT have their tasks accepted. The protocol is injected into every worker prompt by `build_worker_prompt()`.

### INV-24c: Incremental Findings Commit
Workers MUST write observations to Beads notes as they occur, not only at task completion. This prevents loss of intermediate observations if the agent's context fills up or the agent crashes.

---

## 7. Git Invariants

### INV-25: Push Before Session End
If a remote named `origin` exists, work MUST be pushed before ending a session. If no remote exists, the agent MUST keep local commits and explicitly record `NO_REMOTE` rather than inventing a remote. NEVER say "ready to push when you are" — push when a remote exists, otherwise report the missing remote.

### INV-26: Worktree Isolation
Each worker agent operates in its own git worktree. Workers MUST NOT modify files in other worktrees or in the main workspace.

---

## 8. Simplicity Invariants

### INV-27: Simplicity Criterion
All else equal, simpler is better:
- Small improvement + big complexity = REJECT
- Small improvement from deleting code = ALWAYS KEEP
- Equal results + simpler code = KEEP (simplification win)
- The Critic evaluates complexity cost in its review

---

## 9. Security Invariants

### INV-28: User Allowlist
Telegram bot MUST enforce `user_allowlist` before processing any command from external users.

### INV-29: No Secrets in Prompts
Bot tokens, API keys, and other secrets MUST NOT be included in orchestrator or worker prompts. They are passed via environment variables only.

### INV-30: Sandbox Resource Limits
When Docker sandbox is enabled, containers MUST have CPU, memory, and timeout limits. Network isolation MUST be configurable.
