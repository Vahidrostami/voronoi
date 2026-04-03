# Workflows Specification

> End-to-end workflows: investigate, explore, build, demo. What happens from question to deliverable.

**TL;DR**: BUILD = decompose→parallel builders→critic review→merge. EXPLORE = scout→explore options→statistician→synthesize. INVESTIGATE = scout→theorize→baseline(hard gate)→pre-reg→parallel experiments→EVA→review gates→synthesize→evaluate→converge. Two loops: inner (per-agent verify) + outer (orchestrator OODA).

## 1. Workflow Selection

The intent classifier maps user input to one of two science modes:

| Mode | Rigor | Trigger Examples |
|------|-------|-----------------|
| DISCOVER | Adaptive | "why", "figure out", "compare", "build", "explore", "what if", open questions |
| PROVE | Scientific/Experimental | "test whether", "prove hypothesis", "A/B test", detailed PROMPT.md with pre-registered design |

**Key principle**: Open question → DISCOVER. Specific hypothesis → PROVE. When in doubt, DISCOVER — the orchestrator escalates rigor as hypotheses emerge.

---

## 2. DISCOVER Workflow (Adaptive Rigor)

### Philosophy

DISCOVER is free scientific exploration. The user gives an open question; agents explore creatively, form hypotheses, and pursue multiple paths in parallel. Rigor adapts dynamically — starts light, escalates when testable hypotheses crystallize.

### Roles Active
All 12 roles available. Orchestrator casts dynamically based on what it finds.

### Adaptive Rigor Escalation

```
Phase 1: Explore (analytical-level rigor)
  → Scout + Builder + Explorer run in parallel
  → No pre-registration required
  → Critic reviews inline

Phase 2: Hypothesize (rigor escalates when belief map has testable hypotheses)
  → Theorist engaged
  → Statistician engaged
  → Pre-registration now required for hypothesis tests

Phase 3: Test (scientific-level rigor)
  → Methodologist reviews experimental design
  → Investigators run pre-registered experiments
  → Full review gates active
```

### Steps

1. **Classify** — Intent classifier returns `DISCOVER` + `ADAPTIVE`
2. **Enqueue** — Investigation queued with mode=discover
3. **Dispatch** — Workspace provisioned, orchestrator launched
4. **Free Exploration** — Orchestrator reads question, dispatches Scout + any relevant initial agents in parallel. No rigid sequence.
5. **Hypothesis Formation** — As agents report back, orchestrator forms belief map. SERENDIPITY events can redirect exploration.
6. **Plan Review** — At Analytical+ rigor, before dispatching structured investigation work, the orchestrator submits its task decomposition for review. Critic reviews the plan (at Scientific+: Critic + Theorist; at Experimental: + Methodologist). Reviewer writes verdict to `.swarm/plan-review.json`. Orchestrator revises if verdict is REVISE or RESTRUCTURE, then proceeds. One round only.
7. **Rigor Escalation** — When hypotheses are testable, orchestrator engages Methodologist + Statistician. Pre-registration kicks in.
8. **Parallel Investigation** — Multiple agents pursue different hypotheses simultaneously
9. **Inner Loop** — Each agent: execute → verify → retry (self-healing)
10. **OODA Outer Loop** — Orchestrator observes findings, updates belief map, decides next actions
11. **Review Gates** — Statistician + Critic review findings (activated when rigor escalated)
12. **Synthesis** — Synthesizer assembles deliverable
13. **Evaluation** — Evaluator scores output

### Convergence
All active hypotheses resolved OR orchestrator judges exploration complete + eval score ≥ 0.75.

### Deliverable
Report with findings, evidence chain, and recommendations. If scope warrants, scientific manuscript.

### SERENDIPITY Protocol

When an agent finds something unexpected:
1. Agent flags `SERENDIPITY:<description>` in Beads notes
2. Orchestrator reads this during OODA Observe
3. Orchestrator decides: pivot investigation, spawn follow-up agents, or note and continue
4. Unexpected findings are never discarded — they're recorded even if not pursued

---

## 3. PROVE Workflow (Scientific/Experimental Rigor)

### Philosophy

PROVE is structured hypothesis testing. The user provides a specific, testable hypothesis (or a detailed PROMPT.md). Full science gates from the start. No exploration phase — go straight to rigorous validation.

### Roles Active
All 12 roles from the start.

### Steps

1. **Classify** — `PROVE` + `SCIENTIFIC` (or `EXPERIMENTAL` if replication signals detected)
2. **Scout Phase** — Prior knowledge, SOTA anchoring, gap identification
3. **Theory Phase** — Theorist proposes causal models and competing theories
4. **Hypothesis Generation** — Orchestrator initializes belief map with hypotheses
5. **Plan Review** — Orchestrator submits task decomposition for review before any experiments run. At Scientific rigor: Critic + Theorist review. At Experimental: Critic + Theorist + Methodologist. Reviewer(s) dispatched with `TYPE:plan-review` in task notes. Verdict written to `.swarm/plan-review.json`. Orchestrator revises plan if verdict is REVISE or RESTRUCTURE. One round only — no iterative loops.
6. **Baseline** — First subtask is ALWAYS a baseline measurement (hard gate)
7. **Pre-Registration** — Each investigator pre-registers: hypothesis, method, controls, stat test, sample size, power analysis, sensitivity plan
8. **Methodologist Review** — Mandatory — approves or revises experimental design
9. **Dispatch Investigators** — Parallel experiments in worktrees
10. **Inner Loop** — Each investigator:
   - Execute experiment
   - Verify: runs without crash, metric extracted
   - Self-verification: test loop (up to 3 retries), produces check, metric consistency
   - EVA: manipulation check, artifact check, sanity check
   - If DESIGN_INVALID → escalate to Methodologist
   - Commit raw data with SHA-256
   - Sensitivity analysis (2+ parameter variations)
   - Create FINDING in Beads
11. **OODA Loop** — Orchestrator reads findings, updates belief map, checks convergence
12. **Statistician Review** — Independent recomputation, interpretation metadata
13. **Critic Review** — Partially blinded adversarial review
14. **Synthesis** — Claim-evidence registry → deliverable (report or manuscript)
15. **Evaluation** — CCSA scoring with structured feedback
16. **Convergence** — All hypotheses resolved, no paradigm stress, eval ≥ 0.75

### Human Review Gates (PROVE mode)

At key decision points, the investigation pauses for review:

| Gate | When | What the Human Sees |
|------|------|--------------------|  
| **Plan review** | After orchestrator decomposes into tasks, before baseline | Task decomposition, dependency graph, scope assessment, reviewer verdict |
| **Pre-registration** | After pre-reg complete, before running experiments | Hypothesis, method, N, design summary |
| **Convergence** | After findings collected, before finalizing deliverable | Findings summary, eval score, convergence status |

### Additional Experimental Gates

| Gate | Description |
|------|-------------|
| Mandatory Methodologist review | Design review is blocking, not advisory |
| Replication | High-impact findings MUST be replicated |
| Pre-reg compliance audit | Verify experiment matched pre-registration |
| Power analysis documented | Required and verified |

### Convergence
All hypotheses resolved + competing theory ruled out + novel prediction tested + no PARADIGM_STRESS + eval score ≥ 0.75. For EXPERIMENTAL rigor: + all high-impact findings replicated + pre-reg compliance verified.

### DESIGN_INVALID Recovery Flow

```
Investigator finds DESIGN_INVALID
     │
     ▼
Orchestrator dispatches Methodologist for post-mortem
     │
     ▼
Methodologist diagnoses root cause + prescribes redesign
     │
     ▼
Orchestrator creates new experiment task (REVISE type)
     │
     ▼
New task validates fix first, then runs full experiment
```

### Deliverable
Scientific report or manuscript with:
- Evidence chain (claim → finding traceability)
- Belief map evolution
- Interpreted findings
- Negative results section
- Limitations

---

## 4. Demo Workflow

### CLI Path

```bash
voronoi demo run forgetting-cure
```

1. `cmd_demo()` locates demo in `demos/` directory
2. Copies demo files to target directory
3. Reads `PROMPT.md` from demo
4. Builds orchestrator prompt with demo's mode/rigor
5. Launches Copilot CLI with prompt

### Telegram Path

```
/voronoi demo run forgetting-cure
```

1. `handle_demo()` in router enqueues investigation with `demo_source` set
2. Dispatcher picks up, provisions workspace
3. `_copy_demo_files()` copies demo `PROMPT.md` and other files
4. Builds prompt, launches in tmux
5. Progress updates sent to Telegram

### Demo Structure

```
demos/<name>/
├── PROMPT.md          # Investigation brief (the "question")
└── README.md          # Human-readable description
```

---

## 7. Telegram Messaging Experience

The dispatcher sends narrative digest updates to Telegram — batched every ~30 seconds instead of per-event streaming.

### Message Types

| Type | When | Key Content |
|------|------|-------------|
| **Launch** | Investigation starts | `*Codename* is live.` — mode, rigor, question snippet |
| **Digest** | Every ~30s while events exist | What happened + where we are + progress bar + track assessment |
| **Alert** | DESIGN_INVALID, paradigm stress, stall | `*Codename* — heads up:` warning |
| **Restart** | Agent crash, auto-retry | `*Codename* — crashed. Restarting (1/2).` + log tail |
| **Completion** | Investigation done | Teaser with headline finding + all findings + PDF attachment |
| **Failure** | Unrecoverable crash/timeout | Reason + tasks done + log tail |

### Digest Structure

Each digest is a single narrative message:

```
*Dopamine* — 2h 15min

✅ Finished: baseline measurement
✅ Finished: EWC agent
💡 Finding: EWC outperforms baseline (d=1.47)

Investigating — running 2 experiments in parallel
████████████░░░░░░░░ 60%  12/20 tasks · ~45min left

Experiments: 3 keep, 1 crash, 0 discard
Success: 2/4 criteria met

2 agents working right now
```

### Track Assessment

Digest includes a track assessment when things need attention:

| Status | Trigger | Display |
|--------|---------|---------|
| `on_track` | Normal progress | (nothing shown) |
| `watch` | 70%+ tasks done but 0 criteria met, or eval < 0.5 | Gentle heads-up |
| `off_track` | DESIGN_INVALID open, or eval < 0.3 | Bold warning |

### Inline Buttons

The Telegram bridge adds contextual buttons to messages:

| After... | Buttons |
|----------|---------|
| Workflow launch | [📊 Status] [🛑 Abort] |
| Status response | [📋 Tasks] [⚡ Ready] [🩺 Health] |
| Digest update | [Progress] [Guide] [Abort] |
| Completion | [Details] [Belief Map] |

### Conversational Handlers

| Natural language | Handler | What it returns |
|-----------------|---------|-----------------|
| "what's up" / "status" | `handle_whatsup()` | Per-investigation overview with agents, tasks, phase |
| "how's it going" | `handle_howsitgoing()` | Experiment progress, success criteria, belief map, track status |
| Free text question | `handle_free_text()` | Classifies intent → auto-dispatches to right workflow |
| Greetings (hi, hello) | `_is_greeting()` | Welcome message with capability overview |

### Phase Sequence

```
starting → scouting → planning → plan-review → investigating → reviewing → synthesizing → converging → complete
```

Each phase has conversational descriptions per mode (not just labels), e.g.:
- investigate/scouting: "Doing some background research first."
- build/planning: "Breaking the work into pieces."

### Abort & Pivot

| Action | Mechanism |
|--------|-----------|
| `/voronoi abort` | Cancels queued + writes `.swarm/abort-signal` to all running workspaces |
| `/voronoi pivot <guidance>` | Appends operator guidance to all active workspaces |
| `/voronoi guide <message>` | Same as pivot — adds context for orchestrator |

### Group Chat Support

- **Private chats**: All messages processed
- **Group chats**: Only responds when @mentioned or when replying to a bot message

---

## 8. Two Loops Architecture

Every workflow runs two nested loops:

### Inner Loop (per agent, fast)

```
Execute → Test Loop (up to 3 retries) → Self-Review Checklist → [FAIL: VERIFY_EXHAUSTED] → [PASS: done]
```

The self-verification protocol (test loop + checklist + incremental Beads commit) runs before every task close. Workers log each step to `.swarm/events.jsonl` for observability.

- Handles execution errors autonomously
- Max retries vary by role (2-5)
- Only escalates after exhausting self-repair

### Outer Loop (orchestrator, deliberate)

```
Observe → Orient → Decide → Act → [not converged: repeat]
```

- Handles strategic decisions
- Which hypotheses to pursue
- When to change direction
- When to converge

### Why Two Loops

The inner loop prevents agent execution failures from cluttering the orchestrator's strategic view. The orchestrator only sees "task complete" or "task exhausted after N attempts" — never individual test failures or lint errors.

---

## 9. Task Dependency Graph

Tasks form a directed acyclic graph, not a flat queue.

### Baseline-First Invariant

Every investigation epic's first subtask is a baseline measurement. All experimental tasks are blocked until baseline completes.

```
Orchestrator
     │
     ├── Baseline (sequential, first)
     │
     ├── EWC (blocked by Baseline)
     ├── Replay (blocked by Baseline)
     │
     └── Hybrid (blocked by EWC + Replay)
```

### Dependency Enforcement

- Beads tracks task dependencies
- `bd ready` returns only unblocked tasks
- Workers check `REQUIRES` at startup — report BLOCKED if missing
- Merge rejected if `PRODUCES` missing

---

## 10. Multi-Run Iteration

### Philosophy

Science is iterative. The user fires a question, Voronoi runs autonomously, then the PI reviews results, raises objections, and triggers another round. The Claim Ledger is the durable scientific state that survives across runs.

### Lifecycle

```
Run 1: question → agents → findings → convergence → REVIEW
  ↓ PI feedback: "lock C1, challenge C2: N too small"
Run 2: warm-start brief → agents → new findings → convergence → REVIEW
  ↓ PI feedback: "looks good"
Run 2: REVIEW → COMPLETE
```

### Key Mechanisms

| Mechanism | Where | What it does |
|-----------|-------|-------------|
| `review` status | queue.py | Pauses after convergence for PI feedback |
| `pi_feedback` field | queue.py | Stores PI feedback separately from the question (never mutates question) |
| Claim Ledger | claims.py | Cross-run scientific state with provenance |
| Warm-Start Brief | prompt.py | Loads prior claims + PI feedback into new round |
| Continuation dispatch | dispatcher.py | Detects `parent_id`, reuses workspace, calls `prepare_continuation()` |
| Workspace reuse | dispatcher.py | Same git repo, archived `.swarm/`, git tags at boundaries |
| Immutability | gates.py | Locked claims' artifacts can't be modified |
| Self-critique | claims.py | Auto-identifies weaknesses before showing PI |

### Workspace Handoff Between Runs

When `/continue` is triggered:
1. Dispatcher detects `inv.parent_id` is set and existing `workspace_path` exists on disk
2. Dispatcher calls `prepare_continuation()` on the prior round's run state:
   a. Git tag `run-<N>-complete` marks the boundary
   b. `.swarm/` state archived to `.swarm/archive/run-<N>/`
  c. Stale run-state files cleared from active `.swarm/` for the fresh orchestrator
    This includes `deliverable.md`, `events.jsonl`, checkpoint, convergence, and eval artifacts so the next round does not inherit a false-complete state or replay old events.
   d. Belief map, experiments.tsv, success criteria carried forward
   e. Worktrees pruned
   f. Locked claims' artifacts written as `file_unchanged` invariants
3. `_voronoi_init()` refreshes templates (agents, skills, scripts)
4. `_build_prompt()` calls `build_warm_start_context()` to inject claim ledger, PI feedback, immutable paths, and artifact manifest into the orchestrator prompt
5. If workspace directory is missing (user cleaned up), falls back to fresh provisioning with a warning

### Runs Are Additive

New runs add experiments, code, and data to the workspace. They never regenerate what prior runs established — unless the PI challenged it. Locked claims create immutability zones. The paper is the only artifact rewritten each round.

### Telegram Commands

| Command | When | Effect |
|---------|------|--------|
| `/voronoi review [codename]` | During or after run | Show Claim Ledger |
| `/voronoi continue <codename> [feedback]` | After review | Start new round with feedback |
| `/voronoi claims [codename]` | Any time | Show claim state |
