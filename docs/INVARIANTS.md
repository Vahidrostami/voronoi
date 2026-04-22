# System Invariants

> Rules that MUST never be violated. Reference during code review, debugging, and development.

...nvariants. Key ones: prompt.py is sole prompt builder (INV-01). Roles only in .github/ files (INV-02). Orchestrator never enters worktrees (INV-03). Atomic queue claiming (INV-06). Rigor only escalates (INV-08). Baseline-first (INV-09). EVA before finding (INV-12). No simulation bypass (INV-16). Push before session end (INV-25). Plan review before dispatch at Analytical+ (INV-35b). Experiment contract before workers (INV-39). Sentinel audit cannot be bypassed (INV-40). Missing contract warning (INV-41). Tribunal clear before convergence (INV-42). Directional verification on findings (INV-43). Every completion writes a run manifest (INV-44). Paper-track citation integrity (INV-45). Hypothesis-tranche parallelism (INV-46). Red Team verdict before Scientific+ convergence (INV-47).

## 1. Architectural Invariants

### INV-01: Single Prompt Source of Truth
`prompt.py` is the ONLY module that builds orchestrator prompts. CLI and Telegram MUST both call `build_orchestrator_prompt()`. No other module may construct prompts.

### INV-02: Role Files Are Source of Truth
Agent role definitions live ONLY in `src/voronoi/data/agents/*.agent.md` (copied to `.github/agents/` in investigation workspaces). The prompt builder REFERENCES these files (tells orchestrator "read this file"). Python code MUST NOT duplicate or inline role definitions.

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
Investigations MUST follow the state machine defined in SERVER.md §2:
- `queued → running` (via `next_ready()`, atomic)
- `queued → cancelled` (via `cancel()`, pre-launch cancellation)
- `running → {complete | failed | paused | review | cancelled}`
- `running → queued` (via `requeue()`, recovery only — unprovisioned claims with no workspace_path)
- `paused | failed → running` (via `resume()`)
- `review → complete` (via `accept()`)
- `review | complete → new queued` (via `continue_investigation()`, creates a NEW investigation)

A `complete` investigation MUST NOT be re-queued directly. Continuation creates a new investigation with `parent_id` linking to the original (same `lineage_id`, incremented `cycle_number`).

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

### INV-47: Claims Are Propositions, Not Tasks
A Claim Ledger entry MUST be a proposition about the world (a testable assertion), not a task directive. Statements that begin with a bare imperative verb (`Analyze`, `Investigate`, `Run`, `Check`, `Explore`, `Examine`, `Study`, `Review`, `Assess`, `Evaluate`, `Test`, `Verify`, `Look`, `Find`, `Identify`, `Determine`, `Survey`) AND contain no relational marker (`>`, `<`, `=`, `vs`, `causes`, `predicts`, `increases`, `decreases`, `is`, `are`, ...) MUST be rejected by `ClaimLedger.add_claim` with `ValueError`. Exact duplicates (after normalization — lowercase, collapsed whitespace, stripped trailing punctuation) MUST also be rejected. Enforced by `voronoi.science.claims.validate_claim_statement` and mirrored at the MCP boundary by `require_claim_statement`. The dispatcher's Beads-to-Ledger sync MUST additionally require task titles to **start** with a `FINDING:` / `FINDING -` / `FINDING —` prefix before synthesizing a claim — substring matches on "findings" in arbitrary task titles are banned.

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

### INV-31: No Secrets in Logs or Workspace Files
Auth tokens (GH_TOKEN, GITHUB_TOKEN, COPILOT_GITHUB_TOKEN) MUST NOT appear in tmux pane logs or agent log files. Token injection into tmux shells MUST use environment file mechanisms (`tmux set-environment`) instead of inline `export VAR=value` in send-keys commands that are captured by `pipe-pane` logging.

Secrets MUST NOT be written to any path under the investigation workspace (the git repo at `<base_dir>/active/inv-<id>-<slug>/`). Multiple code paths run `git add -A` over the workspace (orchestrator commit directive, scribe, teardown), and the GitHub publisher pushes the resulting tree to `voronoi-lab/*` with `--force`; a workspace-resident `.tmux-env` would exfiltrate operator credentials. The tmux launcher MUST write the env file to a sibling location outside the repo (e.g. `<base_dir>/active/.tmux-env-<session>`) and the launched shell MUST `rm -f` it immediately after sourcing.

### INV-32: Human Gate Pause Enforcement
When a human gate is pending (`.swarm/human-gate.json` with `status: "pending"`), the dispatcher MUST kill the tmux session to halt the agent. A gate-pending dead session MUST NOT be routed through crash-retry logic. The agent resumes only after the gate is approved or revised.

The orchestrator prompt MUST instruct the agent to **park and exit** at the gate — write the gate file, write a checkpoint with `active_workers: []` and `phase: "awaiting-human-gate"`, and terminate. The orchestrator MUST NOT sleep, poll, or re-read the gate file in-session; doing so violates the checkpoint-and-exit lifecycle and burns context. The dispatcher-side polling watchdog MAY force-restart orchestrators observed running `sleep` in their pane.

### INV-33: Belief Map Schema
`.swarm/belief-map.json` MUST store `hypotheses` as a JSON array of objects (not an object map keyed by ID). Both the Python loader (`load_belief_map`) and the shell convergence gate MUST validate the schema on load and migrate non-conforming data.

### INV-34: Negative-Result Completion
An investigation that produces valid experimental results that falsify the hypothesis is a completed investigation, not a failed one. The convergence system MUST support a `negative_result` status distinct from `failed` and `exhausted`.

---

## 10. Iterative Science Invariants

### INV-35: Locked Claim Immutability
Locked claims' supporting artifacts (code, data, results) MUST NOT be modified in subsequent runs. Enforced by `file_unchanged` invariant check in the convergence gate. The dispatcher writes these invariants automatically during workspace continuation preparation.

### INV-36: Claim Ledger Lineage Scoping
The Claim Ledger is scoped to a lineage (parent_id chain). A new unrelated question MUST create a new ledger. Claims MUST NOT contaminate across lineages. The `lineage_id` field on Investigation determines which ledger to use.

### INV-37: Model Prior Disclosure
Claims tagged `model_prior` MUST NOT appear as established findings in deliverables without explicit disclosure. The prompt builder flags these for the orchestrator. The Claim Ledger tracks provenance to ensure this.

### INV-38: Continuation Artifact Preservation
Continuation runs MUST NOT regenerate data that locked claims depend on. New data MUST be created in separate files/directories. The warm-start brief lists immutable paths and instructs the orchestrator accordingly.

### INV-35b: Plan Review Before Dispatch (Analytical+)
At Analytical rigor and above, the orchestrator MUST submit its task decomposition for plan review BEFORE dispatching investigation workers. The Critic (and at higher rigor, Theorist and Methodologist) reviews the plan and writes a verdict to `.swarm/plan-review.json`. The orchestrator MUST revise the plan if the verdict is REVISE or RESTRUCTURE. Only one review round is permitted — no iterative loops. At Standard rigor (build tasks), plan review is skipped.

---

## 11. Experiment Sentinel Invariants

### INV-39: Experiment Contract Before Workers
At Analytical rigor and above, the orchestrator MUST write `.swarm/experiment-contract.json` after experiment design and BEFORE dispatching investigation workers. The contract declares the independent variable, conditions, and machine-readable validity checks. The dispatcher enforces this structurally — it does not rely on the orchestrator to validate outputs.

### INV-40: Sentinel Audit Cannot Be Bypassed
The dispatcher Sentinel runs autonomously. The orchestrator MUST NOT delete, modify, or ignore `.swarm/sentinel-audit.json`. If the Sentinel flags a critical failure, the orchestrator MUST treat it as a DESIGN_INVALID event and dispatch a Methodologist for post-mortem — it MUST NOT proceed to the next phase or declare convergence while sentinel failures are unresolved.

### INV-41: Missing Contract Warning
At Analytical+ rigor, if experiment-type tasks exist but no `.swarm/experiment-contract.json` has been written after 1 hour, the dispatcher MUST warn and write a `sentinel_violation` directive. The orchestrator MUST NOT dispatch additional experiment workers until the contract is written.

### INV-42: Tribunal Clear Before Convergence
At Analytical+ rigor, convergence is BLOCKED while any tribunal verdict has status `anomaly_unresolved` or `artifact`. Enforced by `check_tribunal_clear()` in `convergence.py`. The orchestrator MUST address unresolved anomalies (dispatch follow-up experiments or revise the causal model) before convergence can proceed.

### INV-43: Directional Verification on Findings
At Analytical+ rigor, every hypothesis with a significant finding MUST be classified as `confirmed`, `refuted_reversed`, or `inconclusive` based on comparison of observed effect direction vs pre-registered `expected_direction`. A significant result in the opposite direction is `refuted_reversed`, NOT `confirmed`. Convergence is blocked while any `refuted_reversed` hypothesis has no tribunal explanation. Enforced by `has_reversed_hypotheses()` in `convergence.py`.

---

## 12. Deliverable Invariants

### INV-44: Every Completion Writes a Run Manifest
Every investigation that reaches `_handle_completion` (success, negative result, exhaustion, build-mode completion) MUST produce `.swarm/run-manifest.json`. The CLI demo path (`voronoi demo run …`) MUST also write a manifest after the orchestrator subprocess exits. This is the canonical machine-readable record of the run's claims, experiments, artifacts, and provenance.

The manifest is a **derived** artifact — it never contradicts its sources (`.swarm/convergence.json`, `.swarm/eval-score.json`, `.swarm/belief-map.json`, `.swarm/claim-evidence.json`, Claim Ledger). Manifest-writing is best-effort and MUST NOT block the completion pipeline; failure is logged but not raised.

The manifest is written **after** the status transition so it captures finalized ledger state (promoted claims, self-critique, continuation proposals). The narrow race window between `queue.complete()` / `queue.review()` and `_write_run_manifest()` — where a process crash could leave a completed investigation with no manifest — is accepted risk; the manifest is a derived artifact and can be regenerated on demand from `.swarm/` state via `build_manifest_from_workspace()`.

Enforced by `InvestigationDispatcher._write_run_manifest()` (server path) and by `cmd_demo()` post-subprocess (CLI demo path). Schema at `docs/MANIFEST.md`.

### INV-45: Paper-Track Citation Integrity
Every `\cite{...}` key in a paper-track manuscript's `paper.tex` MUST resolve to an entry in `.swarm/manuscript/citation-ledger.json` with `verified: true`. AND at least 90% of verified ledger entries must be `\cite`d somewhere in `paper.tex` (the citation-integration rate must be ≥ `DEFAULT_COVERAGE_TARGET = 0.90`). Orphan `\cite` keys are treated as hallucinated references — zero tolerance, regardless of integration rate. Enforced by `voronoi.science.citation_coverage.check_coverage()` at Scribe verify-loop step 6 and after every Refiner review round. A failing gate reverts the latest Refiner round. Applies only when `.swarm/manuscript/citation-ledger.json` exists (i.e., paper-track was activated via `/voronoi paper`).

### INV-46: Hypothesis-Tranche Parallelism
The dispatcher unit of parallelism is a **hypothesis tranche** — one hypothesis arm plus its controls and sensitivity variants — NOT an individual worker. The orchestrator may run up to `max_agents_per_investigation` tranches in parallel (default 6). When a tranche completes, its slot is filled by a NEW tranche rather than by additional variants of an already-resolved arm. This enforces the principle that parallelism serves hypothesis-space coverage, not throughput of a single arm. Enforced by `server/prompt.py` (orchestrator prompt teaches tranche semantics) and by `server/runner.py`/`server/dispatcher.py` default configuration.

### INV-47: Red Team Verdict Before Convergence (Scientific+)
At rigor levels `scientific` and `experimental`, `check_convergence()` MUST NOT return `converged=True` unless `<workspace>/.swarm/red-team-verdict.json` exists, is valid JSON, and has `verdict ∈ {pass, pass_with_caveats}`. A `fatal_flaw` verdict is a hard blocker with the verdict's `reason` surfaced in `ConvergenceResult.blockers`. The Red Team agent (`src/voronoi/data/agents/red-team.agent.md`) is invoked with a **cold context** via `build_red_team_prompt()` — it reads only `deliverable.md`, `claim-ledger.json`, and raw artifacts under `output/`, never investigation history. Adaptive rigor skips this gate (cost/speed). Enforced by `voronoi.science.convergence._check_red_team_verdict()`.

### INV-48: Continuation Requires New Information
`handle_continue_investigation` MUST refuse to enqueue a new round when ALL of the following hold: (a) feedback is empty, (b) the prior workspace's `.swarm/convergence.json` has `gate_passed=true`, (c) a manuscript deliverable exists (`paper.tex`, `deliverable.md`, or `.swarm/manuscript/paper.tex`), AND (d) the claim ledger has no pending objections. Re-running a fully-converged investigation with zero new information merely replays the Scribe/Evaluator finisher chain and produces no belief-map delta. The refusal message points the operator at `/voronoi deliberate`, an explicit `challenge Cn: <reason>`, a free-text scope change, or `/voronoi complete`. Enforced by `voronoi.gateway.handlers_mutate._has_continuation_signal()`.

### INV-49: Checkpoint Reconciled Against Beads Before Restart
`InvestigationDispatcher._has_active_workers` MUST NOT trust `orchestrator-checkpoint.active_workers` alone. Before deciding that workers are done, it cross-checks `bd list --status in_progress --json` and augments the worker-candidate list with any task IDs that are in-progress in Beads but absent from the checkpoint. Without this reconciliation, a stale checkpoint with `active_workers=[]` while a real worker (e.g. Scribe) is still in-progress caused the dispatcher to restart the orchestrator and spawn a duplicate finisher. Enforced by `InvestigationDispatcher._bd_in_progress_task_ids()` feeding into `_has_active_workers()`.

### INV-50: Stop-and-Fix Directive Blocks Dispatch Structurally
When `.swarm/dispatcher-directive.json` contains `{"action": "stop_and_fix"}`, `spawn-agent.sh` MUST refuse to spawn any task whose title does not match the methodologist/post-mortem/revise/fix-contract/sentinel pattern, returning exit 1 and marking the task BLOCKED in Beads. This is the structural counterpart to INV-40 (prompt-level enforcement of sentinel audits): an orchestrator that ignores the sentinel directive in its prompt is caught at dispatch time, so no new workers can burn hours on invalid data.

### INV-51: Paradigm Stress Counts Refuted Hypotheses
`check_paradigm_stress` MUST count hypotheses with `status == "refuted"` in `belief-map.json` as equivalent stress events alongside pairwise finding contradictions. The threshold of 3 total stress events is preserved. This closes a blind spot where refuted paper-level hypotheses (contradicting abstract-level claims) silently accumulated at `paradigm_stress=0`, preventing auto-deliberation and paradigm pivots.

### INV-52: Ledger Load-Time Shape Validation
`_dict_to_ledger` MUST apply `validate_claim_statement` to every incoming claim and drop those that fail (logging a WARNING with the claim ID and reason). This quarantines legacy ledgers — produced before the Beads-to-Ledger launderer was fixed — whose statements are bare imperatives like `"Analyze pricing dataset"`. Surviving claim IDs are preserved and `_next_claim_id` is bumped so the counter never collides with a dropped-but-referenced ID.
