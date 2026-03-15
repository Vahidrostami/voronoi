# Workflows Specification

> End-to-end workflows: investigate, explore, build, demo. What happens from question to deliverable.

**TL;DR**: BUILD = decompose→parallel builders→critic review→merge. EXPLORE = scout→explore options→statistician→synthesize. INVESTIGATE = scout→theorize→baseline(hard gate)→pre-reg→parallel experiments→EVA→review gates→synthesize→evaluate→converge. Two loops: inner (per-agent verify) + outer (orchestrator OODA).

## 1. Workflow Selection

The intent classifier maps user input to a workflow:

| Mode | Rigor | Trigger Examples |
|------|-------|-----------------|
| BUILD | Standard | "build", "implement", "deploy", "refactor", "create" |
| EXPLORE | Analytical | "which best", "compare", "evaluate", "tradeoffs" |
| INVESTIGATE | Scientific | "why", "root cause", "hypothesis", "investigate" |
| INVESTIGATE | Experimental | "A/B test", "controlled trial", "p-value target" |
| HYBRID | Scientific | "figure out and fix", "paper", "manuscript" |

**Invariant**: When in doubt, classify higher. Gates can be skipped but not added retroactively.

---

## 2. Build Workflow (Standard Rigor)

### Roles Active
Builder, Critic, Worker

### Steps

1. **Classify** — Intent classifier returns `BUILD` + `STANDARD`
2. **Enqueue** — Investigation queued with mode=build
3. **Dispatch** — Workspace provisioned, orchestrator launched
4. **Decompose** — Orchestrator breaks task into subtasks with dependency graph
5. **Dispatch Workers** — Each subtask → Builder agent in own worktree
6. **Verify Loop** — Each builder: code → test → lint → retry (max 5)
7. **Code Review** — Critic reviews each completed branch
8. **Merge** — `merge-agent.sh` integrates branches to main
9. **Complete** — All tasks closed, tests passing

### Convergence
All tasks closed + tests passing on main.

### Deliverable
Working code on main branch.

---

## 3. Explore Workflow (Analytical Rigor)

### Roles Active
Scout, Explorer, Statistician, Critic, Synthesizer, Evaluator + (Builder if implementation needed)

### Steps

1. **Classify** — `EXPLORE` + `ANALYTICAL`
2. **Scout Phase** — Scout researches prior knowledge, SOTA, existing solutions
3. **Decompose** — Orchestrator identifies options to evaluate
4. **Explore** — Explorer agents evaluate each option:
   - Comparison matrices
   - Pros/cons with evidence
   - Benchmarks where applicable
5. **Statistical Review** — Statistician reviews any quantitative claims
6. **Synthesis** — Synthesizer assembles comparison deliverable
7. **Evaluation** — Evaluator scores: Completeness, Coherence, Strength, Actionability
8. **Convergence Check**

### Convergence
Statistician reviewed + no contradictions + eval score ≥ 0.75.

### Deliverable
Comparison report with recommendations, backed by evidence.

---

## 4. Investigate Workflow (Scientific Rigor)

### Roles Active
All 11 roles.

### OODA Loop

The orchestrator runs iterative OODA cycles until convergence.

```
OBSERVE → ORIENT → DECIDE → ACT → (repeat until converged)
```

### Steps

1. **Classify** — `INVESTIGATE` + `SCIENTIFIC`
2. **Scout Phase** — Prior knowledge, SOTA anchoring, gap identification
3. **Theory Phase** — Theorist proposes causal models and competing theories
4. **Hypothesis Generation** — Orchestrator initializes belief map with hypotheses
5. **Baseline** — First subtask is ALWAYS a baseline measurement (hard gate)
6. **Pre-Registration** — Each investigator pre-registers: hypothesis, method, controls, stat test, sample size, power analysis, sensitivity plan
7. **Methodologist Review** — Approves or revises experimental design (advisory but recorded)
8. **Dispatch Investigators** — Parallel experiments in worktrees
9. **Inner Loop** — Each investigator:
   - Execute experiment
   - Verify: runs without crash, metric extracted
   - EVA: manipulation check, artifact check, sanity check
   - If DESIGN_INVALID → escalate to Methodologist
   - Commit raw data with SHA-256
   - Sensitivity analysis (2+ parameter variations)
   - Create FINDING in Beads
10. **OODA Observe** — Orchestrator reads findings, belief map, experiment ledger
11. **OODA Orient** — Update strategic context, check paradigm stress, convergence
12. **OODA Decide** — Information-gain priority, review gates, replication needs
13. **OODA Act** — Merge completed work, spawn new agents, update belief map
14. **Statistician Review** — Independent recomputation, interpretation metadata
15. **Critic Review** — Partially blinded adversarial review
16. **Synthesis** — Claim-evidence registry → deliverable (report or manuscript)
17. **Evaluation** — CCSA scoring
18. **Convergence** — All hypotheses resolved, no paradigm stress, eval ≥ 0.75

### Convergence
All hypotheses resolved + competing theory ruled out + novel prediction tested + no PARADIGM_STRESS + eval score ≥ 0.75.

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

## 5. Experiment Workflow (Experimental Rigor)

### Roles Active
All 11 roles + replication.

### Additional Gates (beyond Scientific)

| Gate | Description |
|------|-------------|
| Mandatory Methodologist review | Design review is blocking, not advisory |
| Replication | High-impact findings MUST be replicated |
| Pre-reg compliance audit | Verify experiment matched pre-registration |
| Power analysis documented | Required and verified |

### Convergence
All Scientific criteria + all high-impact findings replicated + pre-reg compliance verified.

---

## 6. Demo Workflow

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
starting → scouting → planning → investigating → reviewing → synthesizing → converging → complete
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
Execute → Verify → [FAIL: retry with error context] → [PASS: done]
```

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
