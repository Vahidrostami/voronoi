# Universal Agent Swarm — Science-First Design

## Project Name: `agent-swarm-template`

A production-ready template repository for orchestrating multiple AI agents working in parallel. Designed from first principles around scientific rigor — because science needs everything engineering needs (parallel execution, isolation, merging, task tracking) plus hypothesis management, experimental rigor, statistical validation, theory building, and bias prevention. If you design for science, engineering works by skipping the science-specific gates. No extra cost, no configuration.

**The user types one prompt.** The system classifies, adapts, and executes.

---

## 1. Design Philosophy

**Science is a superset of engineering.** An engineering workflow is just a scientific workflow with the rigor gates turned off. By building the full scientific pipeline first, engineering mode falls out naturally as a simplified path through the same system.

**Zero additional user burden.** The user types `/swarm <prompt>` exactly as before. The system auto-detects workflow mode and rigor level. The same 6 commands work unchanged. Richer output appears only when the task warrants it.

**Evidence over opinion.** Every quantitative claim must come with effect size, confidence interval, sample size, and statistical test. Raw data is always preserved. Findings are reviewed before they enter the knowledge store. Negative results are valued equally with positive results.

**Convergence over completion.** Engineering is done when all tasks close. Science is done when all hypotheses are resolved, the causal model accounts for all observations, and at least one novel prediction has been confirmed.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  UX LAYER — One prompt, same 6 commands, zero config        │
├─────────────────────────────────────────────────────────────┤
│  CLASSIFIER — Intent → Workflow Mode + Rigor Level          │
├─────────────────────────────────────────────────────────────┤
│  WORKFLOW ENGINE — OODA loop with science-aware decisions    │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────────┐ │
│  │ Observe │→│  Orient  │→│  Decide  │→│  Act            │ │
│  │ state,  │ │ classify │ │ based on │ │ spawn, merge,   │ │
│  │ findings│ │ events,  │ │ mode +   │ │ replan, notify, │ │
│  │ data    │ │ check    │ │ evidence │ │ record findings │ │
│  │         │ │ paradigm │ │          │ │                 │ │
│  └─────────┘ └──────────┘ └──────────┘ └─────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  ROLE REGISTRY — 9 roles, auto-selected by task type        │
│  Builder · Investigator · Scout · Critic · Synthesizer      │
│  Explorer · Theorist · Methodologist · Statistician         │
├─────────────────────────────────────────────────────────────┤
│  EVIDENCE SYSTEM — Findings, raw data, journal, beliefs     │
├─────────────────────────────────────────────────────────────┤
│  INFRASTRUCTURE — Worktrees · Beads · tmux · git            │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Repository Structure

```
agent-swarm-template/
├── README.md                          # Quick start guide
├── DESIGN.md                          # This file
├── LICENSE                            # MIT
├── CLAUDE.md                          # Agent constitution (read by all agents)
├── AGENTS.md                          # Compatibility alias → CLAUDE.md
├── .claude/
│   ├── settings.json                  # Claude Code project settings
│   ├── commands/                      # Claude Code slash commands
│   │   ├── swarm.md                   # Main orchestrator
│   │   ├── standup.md                 # Daily standup
│   │   ├── progress.md               # Quick progress check
│   │   ├── spawn.md                   # Spawn a single agent
│   │   ├── merge.md                   # Merge completed branches
│   │   └── teardown.md               # Clean up everything
│   └── hooks/
│       └── session-start.sh           # Auto-runs bd prime on session start
├── .github/
│   ├── agents/                        # GitHub Copilot custom agents
│   │   ├── swarm-orchestrator.agent.md
│   │   ├── worker-agent.agent.md
│   │   ├── theorist.agent.md          # Causal model builder
│   │   ├── methodologist.agent.md     # Experimental design reviewer
│   │   └── statistician.agent.md      # Quantitative rigor gatekeeper
│   ├── skills/                        # GitHub Copilot agent skills
│   │   ├── task-planning/SKILL.md
│   │   ├── git-worktree-management/SKILL.md
│   │   ├── beads-tracking/SKILL.md
│   │   ├── agent-standup/SKILL.md
│   │   ├── branch-merging/SKILL.md
│   │   ├── investigation-protocol/SKILL.md  # Hypothesis → experiment → finding
│   │   └── evidence-system/SKILL.md         # Findings, journal, belief maps
│   ├── prompts/                       # GitHub Copilot reusable prompts
│   │   ├── swarm.prompt.md
│   │   ├── standup.prompt.md
│   │   ├── spawn.prompt.md
│   │   ├── merge.prompt.md
│   │   ├── progress.prompt.md
│   │   └── teardown.prompt.md
│   └── workflows/
│       ├── daily-standup.yml          # Automated daily standup
│       └── agent-ci.yml              # CI for agent branches
├── scripts/
│   ├── swarm-init.sh                  # One-time project setup
│   ├── spawn-agent.sh                 # Create worktree + tmux + launch agent
│   ├── spawn-agent-generic.sh         # Generic agent (research/non-code)
│   ├── standup.sh                     # Run standup across all agents
│   ├── merge-agent.sh                 # Merge a completed agent branch
│   ├── merge-agent-generic.sh         # Assemble output from generic agent
│   ├── autopilot.sh                   # Autonomous daemon
│   ├── plan-tasks.sh                  # LLM-powered task decomposition
│   ├── quality-gate.sh               # Pluggable validation
│   ├── dashboard.py                   # Rich terminal UI
│   ├── teardown.sh                    # Nuclear cleanup
│   └── cron-standup.sh               # Cron-compatible standup runner
├── templates/
│   ├── agent-prompt.md                # Template for worker agent prompts
│   ├── investigator-prompt.md         # Template for investigator prompts
│   ├── standup-report.md              # Template for standup output
│   └── epic-template.md              # Template for epic planning
├── .swarm/                            # Created at swarm init
│   └── journal.md                     # Investigation journal
└── .beads/                            # Created by bd init (gitignored)
    └── beads.db                       # Beads database
```

---

## 4. The Classifier

When `/swarm <prompt>` is invoked, the orchestrator determines two things:

### Workflow Mode

| Mode | Description | Example |
|------|-------------|---------|
| **Build** | Implement software artifacts | "Build a REST API with auth" |
| **Investigate** | Answer questions with evidence | "Why is our API latency 3x higher?" |
| **Explore** | Evaluate options against criteria | "Which database should we migrate to?" |
| **Hybrid** | Multiple phases with mode transitions | "Figure out the bottleneck and fix it" |

### Rigor Level

The classifier also determines how much scientific rigor the work requires. This controls which gates and roles activate.

| Rigor Level | Description | Activates | Example |
|-------------|-------------|-----------|---------|
| **Standard** | Ship working software | Builder, Critic | "Build a REST API with auth" |
| **Analytical** | Data-informed decisions | + Scout, Statistician | "Optimize our checkout conversion" |
| **Scientific** | Hypothesis-driven investigation with evidence standards | + Methodologist, Theorist, all gates | "Why is protein X misfolding in condition Y?" |
| **Experimental** | Formal experiments with controls, pre-registration, replication | Full rigor pipeline | "Test whether intervention X causes effect Y" |

**The user never sees rigor levels.** The classifier infers from the prompt. Signal words: "test whether" → Experimental. "Find out why" → Scientific. "Improve" → Analytical. "Build" → Standard.

**Build mode always uses Standard rigor.** Investigate mode defaults to Scientific. Explore defaults to Analytical. Hybrid inherits the highest rigor level of its constituent phases. The orchestrator can escalate rigor mid-flight if findings suggest the problem is harder than initially classified.

| Signal | Rigor | Mode |
|--------|-------|------|
| "build", "create", "implement", "ship" | Standard | Build |
| "optimize", "improve", "increase" | Analytical | Hybrid |
| "why", "investigate", "root cause", "diagnose" | Scientific | Investigate |
| "test whether", "experiment", "validate hypothesis" | Experimental | Investigate |
| "compare", "evaluate", "which should" | Analytical | Explore |
| "research X then build Y", "figure out and fix" | Scientific→Standard | Hybrid |

When in doubt, classify higher — gates can be skipped but can't be added retroactively.

### Scout Activation by Mode

The Scout's "Phase 0" behavior depends on the classified mode:

| Mode | Scout? | Reason |
|------|--------|--------|
| **Build** | **No** (unless prompt is ambiguous) | Requirements are explicit; no prior-knowledge search needed |
| **Investigate** | **Yes** — mandatory | Must survey existing knowledge BEFORE hypothesis generation |
| **Explore** | **Yes** — mandatory | Must identify known evaluations and prior art |
| **Hybrid** | **Yes** — mandatory | Investigation/explore phases need grounding |

Build mode skips Scout because the user's prompt IS the specification. If the classifier detects significant ambiguity in a Build prompt (e.g., "build something that handles auth well"), it can optionally dispatch Scout to clarify requirements before planning.

### Misclassification Correction

The user can override the classifier at two points:

1. **At plan presentation.** The orchestrator always shows the detected mode and rigor before asking for confirmation:
   ```
   Swarm: Classified as: Investigate / Scientific rigor
          [Override: /swarm --mode build]
   ```
   The user can re-invoke with an explicit `--mode` or `--rigor` flag.

2. **Mid-flight.** The user says "this is simpler than you think, just build it" or "this actually needs investigation." The orchestrator reclassifies, preserves completed work, and adjusts gates for remaining tasks.

Escalation (Standard -> Analytical -> Scientific) happens automatically when evidence suggests higher rigor is needed. De-escalation requires explicit user confirmation because dropping gates loses safety guarantees.

---

## 5. Role Registry — 9 Roles

### Builder 🔨

Implements code in isolated worktree.

- Activated by: Build tasks at any rigor level.

### Investigator 🔬

Tests a specific hypothesis or answers a specific question by running experiments, collecting data, and reporting results with evidence.

- Activated by: Investigation tasks at Analytical+ rigor.
- Must submit experimental design for Methodologist review before execution at Scientific+ rigor.
- Must attach raw data files to findings, not just summaries.
- Must pre-register expected outcomes.

### Scout 🔍

Researches existing knowledge before other agents start. Searches codebase, docs, logs, and (with web search) external literature.

- Activated by: Phase 0 of Investigate, Explore, and Hybrid workflows. NOT activated for pure Build mode (see §4 Scout Activation by Mode).
- At Scientific+ rigor, Scout runs BEFORE hypothesis generation (not after).
- Produces a structured knowledge brief with: known results, related work, failed approaches, open questions, AND suggested initial hypotheses with rationale.
- Re-activates when any finding is surprising — searching for whether it's a known phenomenon.

### Critic ⚖️

Stress-tests output. For code: edge cases, security, performance. For findings: methodology, confounds, alternative explanations.

- Activated by: Before any merge (Standard+) or finding acceptance (Analytical+).
- **Build mode behavior:** The Critic runs as an inline review step within the orchestrator — not as a separate agent in its own worktree. It reads the Builder's diff, checks for edge cases/security/performance issues, and either approves (merge proceeds) or rejects with specific objections (Builder gets feedback and retries, up to 3 attempts before escalating to user). This keeps the agent count low for simple builds.
- **Investigation mode behavior:** The Critic runs as a full agent in its own worktree at Scientific+ rigor, performing adversarial audits — actively constructing the strongest case AGAINST each positive finding.
- Tracks confirmed-to-refuted ratio; flags if suspiciously high (>80%).

### Synthesizer 🧩

Reads results from multiple agents, produces unified view, identifies contradictions and consensus, recommends next steps.

- Activated by: When 2+ agents complete related tasks.
- At Scientific+ rigor: also produces an updated belief map (probability distribution over hypotheses given all evidence so far) and appends to the investigation journal.
- At Experimental rigor: performs meta-analysis across findings with effect sizes and confidence intervals.

### Explorer 🧭

Generates and evaluates options against criteria. Produces comparison matrices with tradeoffs.

- Activated by: Explore-mode tasks.

### Theorist 🧬

Constructs causal models from accumulated evidence. Identifies mechanisms (not just correlations), generates novel predictions, and detects when the working theory needs fundamental revision.

- Activated by: Scientific+ rigor, after Synthesizer produces a belief map.
- **Also activated for Investigation Bootstrap** (see §8): After the Scout's knowledge brief arrives and the orchestrator generates initial hypotheses, the Theorist is optionally dispatched to refine hypotheses, assign calibrated priors, and identify non-obvious hypotheses that the orchestrator might miss. At Scientific+ rigor this refinement is mandatory; at Analytical rigor the orchestrator's initial hypotheses are used directly.
- Responsibilities:
  - Takes synthesized findings and builds an explanatory model: "A + B happen because of mechanism X."
  - Generates testable predictions: "If X is true, we should also observe Y."
  - These predictions become NEW investigation tasks — closing the investigation loop.
  - Monitors for paradigm stress: if 3+ findings contradict the working model, flags for major replan.
- Convergence role: Investigation is not done when all hypotheses are tested. It's done when the Theorist's model accounts for all observations and at least one novel prediction has been confirmed.

### Methodologist 📐

Reviews experimental designs BEFORE execution. Ensures proper controls, adequate sample sizes, appropriate statistical tests, and awareness of confounds.

- Activated by: Scientific+ rigor, before any Investigator starts work.
- Responsibilities:
  - Reviews every investigation task's experimental design and must approve before the Investigator starts.
  - Checks for: control conditions, confounding variables, sample size adequacy, appropriate statistical test selection, pre-registration completeness.
  - Can reject a design with specific objections.
  - After experiments: compares pre-registered analysis plan to actual analysis. Flags deviations.
- Gate power: At Experimental rigor, no investigation proceeds without Methodologist approval. At Scientific rigor, Methodologist reviews are advisory (orchestrator can override with a note).
- **Batch review:** When multiple investigation tasks are created simultaneously, the Methodologist reviews all designs in a single pass (one agent invocation), returning approve/reject for each. This prevents the Methodologist from becoming a serial bottleneck. The orchestrator groups pending designs and dispatches one Methodologist review covering all of them.

### Statistician 📊

Quantifies uncertainty properly. Reviews all quantitative findings for statistical validity. Catches multiple comparison errors, p-hacking, and effect size inflation.

- Activated by: Analytical+ rigor, whenever quantitative findings are reported.
- Responsibilities:
  - Every quantitative finding must pass Statistician review before entering the knowledge store.
  - Reviews: confidence intervals, effect sizes, statistical test appropriateness, sample size adequacy, multiple comparison corrections.
  - When multiple investigators report in parallel, applies family-wise error rate adjustment (Bonferroni or Holm-Bonferroni).
  - Computes Bayes factors or posterior probabilities when priors are available from the Theorist's model.
  - Flags: insufficient power, inflated effect sizes, suspiciously clean results, p-values clustered just below 0.05.
- Output: Each reviewed finding gets a statistical quality score (0-1) that weights its influence on subsequent planning.

---

## 6. Task Schema

### Core Fields (all task types)

```
TASK_TYPE:    build | investigation | exploration | review | replication | theory
RIGOR:        standard | analytical | scientific | experimental
STATUS:       open | claimed | in_progress | review | closed | abandoned
RESULT:       success | negative | inconclusive | refuted | N/A
```

### Build Task

```bash
bd create "Implement user authentication" -t task -p 1 --parent <epic>
bd update <id> --description "TASK_TYPE:build | RIGOR:standard | SCOPE:src/auth/ | SPEC:JWT auth with OAuth"
bd update <id> --acceptance "Login, logout, refresh working with tests"
```

No additional gates beyond Critic review before merge.

### Investigation Task

```bash
bd create "Test whether Redis caching reduces API latency >50%" -t task -p 1 --parent <epic>
bd update <id> --description "TASK_TYPE:investigation | RIGOR:scientific"
bd update <id> --notes "HYPOTHESIS: Redis cache on /api/search cuts p95 from 800ms to <400ms"
bd update <id> --notes "METHOD: Benchmark 1000 requests with/without cache, measure p95/p99/mean"
bd update <id> --notes "CONTROLS: Same hardware, same dataset, cold-start vs warm-start runs"
bd update <id> --notes "EXPECTED_RESULT: p95 reduction >50%, CI width <15%"
bd update <id> --notes "CONFOUNDS: Network variance, background processes, cache warm-up time"
bd update <id> --notes "STAT_TEST: Two-sample t-test with Welch correction, alpha=0.05"
bd update <id> --notes "SAMPLE_SIZE: 1000 per condition (power >0.9 for d=0.5)"
bd update <id> --acceptance "Hypothesis confirmed or refuted with data, CI, effect size, raw data attached"
```

**Gates at Scientific+ rigor:**
1. Methodologist reviews design before Investigator starts
2. Investigator runs experiment and commits raw data
3. Statistician reviews quantitative results
4. Critic attempts to find alternative explanations
5. Only then does the finding enter the knowledge store

### Replication Task

```bash
bd create "Replicate: Redis cache latency reduction" -t task -p 2 --parent <epic>
bd update <id> --description "TASK_TYPE:replication | RIGOR:scientific | TARGET:<original-task-id>"
bd update <id> --notes "MUST use different implementation: if original used wrk, use k6 or custom script"
bd update <id> --notes "MUST use same hypothesis and acceptance criteria as original"
bd update <id> --acceptance "Independent confirmation or refutation of original finding"
```

**Replication policy (when the orchestrator triggers replication):**
- Any finding that would change the investigation direction
- Any finding with CI wider than 30% of the effect size
- Any finding that contradicts the Theorist's current model
- Any finding with statistical quality score < 0.7

### Theory Task

```bash
bd create "Construct causal model for API latency bottleneck" -t task -p 1 --parent <epic>
bd update <id> --description "TASK_TYPE:theory | RIGOR:scientific"
bd update <id> --notes "INPUT_FINDINGS: <finding-1-id>, <finding-2-id>, <finding-3-id>"
bd update <id> --notes "GOAL: Explain WHY the observed patterns exist, predict untested outcomes"
bd update <id> --acceptance "Causal model that accounts for all findings + at least 1 testable prediction"
```

### Exploration Task

```bash
bd create "Evaluate database migration options" -t task -p 1 --parent <epic>
bd update <id> --description "TASK_TYPE:exploration | RIGOR:analytical"
bd update <id> --notes "QUESTION: Which database should we migrate to?"
bd update <id> --notes "CRITERIA: latency, cost, migration-effort, ecosystem, scalability"
bd update <id> --notes "OPTIONS: PostgreSQL, CockroachDB, ScyllaDB, TiDB"
bd update <id> --acceptance "Comparison matrix with recommendation and evidence-backed justification"
```

### Review Task

```bash
bd create "Adversarial review: Redis cache finding" -t task -p 2 --parent <epic>
bd update <id> --description "TASK_TYPE:review | RIGOR:scientific | TARGET:<finding-task-id>"
bd update <id> --notes "REVIEW_TYPE: adversarial | FOCUS: methodology, confounds, alternative explanations"
bd update <id> --acceptance "Finding validated OR specific objections with evidence"
```

---

## 7. The Evidence System

### Layer 1: Findings (Structured Knowledge)

Findings are the unit of scientific knowledge. They live in Beads but follow a strict schema.

```bash
# Positive finding with full evidence trail
bd create "FINDING: Redis cache reduces p95 by 62% (plus/minus 8%)" -t task --parent <epic>
bd update <id> --notes "TYPE:finding | VALENCE:positive | CONFIDENCE:0.87"
bd update <id> --notes "SOURCE_TASK:<investigation-task-id>"
bd update <id> --notes "EFFECT_SIZE:0.62 | CI_95:[0.54, 0.70] | N:1000 | STAT_TEST:welch-t | P:0.0001"
bd update <id> --notes "DATA_FILE:results/cache-benchmark-2026-03-02.csv"
bd update <id> --notes "REPLICATED:no | STAT_QUALITY:0.91 | REVIEWED_BY:critic"
bd update <id> --notes "CONTRADICTS: | SUPPORTS:hypothesis-cache-is-bottleneck"

# Negative finding — equally important
bd create "FINDING: Connection pooling has no measurable effect on latency" -t task --parent <epic>
bd update <id> --notes "TYPE:finding | VALENCE:negative | CONFIDENCE:0.82"
bd update <id> --notes "EFFECT_SIZE:0.02 | CI_95:[-0.04, 0.08] | N:10000 | P:0.73"
bd update <id> --notes "DATA_FILE:results/pool-comparison-2026-03-02.csv"
bd update <id> --notes "IMPLICATION: Bottleneck is NOT connection overhead -> revise hypothesis space"
```

### Layer 2: Raw Data

Investigators commit raw data files to their worktree. Finding entries reference these files. The Critic and Statistician can access and re-analyze raw data independently.

Directory convention per agent worktree:
```
<worktree>/
├── src/           # Code (if build task)
├── experiments/   # Experiment scripts
├── data/
│   ├── raw/       # Raw experimental data (CSV, JSON)
│   ├── processed/ # Cleaned/transformed data
│   └── figures/   # Generated plots
└── report.md      # Structured summary of work done
```

### Layer 3: Investigation Journal

A single running document maintained by the Synthesizer. Provides narrative continuity across OODA cycles and sessions.

Location: `.swarm/journal.md`

```markdown
# Investigation Journal

## Cycle 7 — 2026-03-02 14:30 UTC
**State**: 3 hypotheses tested, 1 confirmed, 1 refuted, 1 inconclusive
**Key finding**: Cache is effective (62% p95 reduction), but connection pooling is not
the bottleneck we expected. This shifts our focus from I/O-bound to CPU-bound hypotheses.
**Working theory**: The latency is dominated by JSON serialization in the response
path (supported by profiling data from Agent 2, not yet formally tested).
**Next actions**: Dispatch investigator to test serialization hypothesis. If confirmed,
dispatch builder to implement binary protocol.
**Belief map**:
  - Cache bottleneck: CONFIRMED (0.87)
  - Connection overhead: REFUTED (0.82)
  - JSON serialization: UNTESTED (prior: 0.6 based on profiling data)
  - Database query complexity: UNTESTED (prior: 0.3)
```

The orchestrator reads the journal at session start. The Synthesizer appends after each cycle. The Theorist reads it when building causal models.

### Layer 4: Belief Map

A structured representation of the current state of knowledge. Updated by the Synthesizer after each round of results.

```bash
# Stored as a special Beads entry
bd create "BELIEF_MAP: API Latency Investigation" -t task --parent <epic>
bd update <id> --notes "UPDATED: cycle-7 | HYPOTHESES_TOTAL:6 | TESTED:3 | REMAINING:3"
bd update <id> --notes "H1:cache-bottleneck | STATUS:confirmed | P:0.87 | EVIDENCE:finding-12"
bd update <id> --notes "H2:connection-overhead | STATUS:refuted | P:0.18 | EVIDENCE:finding-14"
bd update <id> --notes "H3:json-serialization | STATUS:untested | PRIOR:0.6 | BASIS:profiling-data"
bd update <id> --notes "H4:db-query-complexity | STATUS:untested | PRIOR:0.3 | BASIS:scout-brief"
bd update <id> --notes "H5:network-latency | STATUS:abandoned | REASON:all-local-testing"
bd update <id> --notes "H6:gc-pauses | STATUS:untested | PRIOR:0.15 | BASIS:theorist-prediction"
```

The orchestrator uses the belief map to decide which hypothesis to investigate next (highest expected information gain: `prior * uncertainty`).

---

## 8. Workflow Engine — The OODA Loop

### Investigation Bootstrap (Fixes the "first cycle" problem)

Before the OODA loop starts, investigation/explore/hybrid workflows run a one-time bootstrap sequence:

```
=== BOOTSTRAP (runs once, before first OODA cycle) ===

1. Dispatch Scout
   Scout produces: knowledge brief (known results, related work,
   failed approaches, open questions, suggested hypotheses)

2. Orchestrator generates initial hypotheses
   Reads Scout brief. Produces 3-7 hypotheses with:
   - Plain-language description
   - Initial prior (0.0-1.0) based on Scout evidence
   - Basis for the prior ("deploy diff shows ORM change" -> 0.7)
   - Estimated testability (how cleanly can this be tested?)
   - Impact (how many downstream decisions depend on this?)

3. At Scientific+ rigor: dispatch Theorist to refine
   Theorist reviews orchestrator's hypotheses, may:
   - Adjust priors with calibration reasoning
   - Add non-obvious hypotheses (mechanistic reasoning)
   - Identify dependencies between hypotheses
   - Flag hypotheses that are actually the same thing stated differently
   At Analytical rigor: skip this step, use orchestrator's hypotheses directly.

4. Create initial belief map
   The orchestrator (or Theorist at Scientific+) creates the first
   BELIEF_MAP entry in Beads with all hypotheses and their priors.
   This belief map is the input to the information-gain formula
   that drives hypothesis prioritization in the OODA loop.

5. Create investigation tasks for top-priority hypotheses
   Rank by: uncertainty(H) * impact(H) * testability(H)
   Create tasks for the top N (up to max_agents worth).

6. At Scientific+ rigor: dispatch Methodologist for batch review
   Methodologist reviews all initial investigation designs in one pass.
   Approved designs proceed. Rejected designs get revised.

7. Enter OODA loop
```

Build mode skips bootstrap entirely — the orchestrator decomposes the prompt into build tasks and dispatches immediately.

### The Full Cycle

```
cycle_count = 0
max_cycles = config.rigor.max_investigation_cycles  # default: 20

while not converged(rigor_level) and cycle_count < max_cycles:

    === OBSERVE ===
    # Build mode short-circuit: skip evidence layers
    Read Beads status for all tasks
    if rigor > standard:
        Read knowledge store (new findings since last cycle)
        Read investigation journal (narrative context)
        Read belief map (current hypothesis state)
    Check git activity (commits, stalls, pushes)
    Check for user input

    === ORIENT ===
    Classify events:
      completion | finding | negative_result | failure | conflict |
      stall | replication_mismatch | paradigm_stress | user_input

    Run paradigm check (Scientific+ rigor):
      Count findings that contradict working model
      If contradictions >= 3: flag PARADIGM_STRESS

    Run bias check (Scientific+ rigor):
      confirmed / (confirmed + refuted) ratio
      If > 0.8 and sample > 5: flag CONFIRMATION_BIAS_WARNING

    Run convergence check:
      Standard: all build tasks closed?
      Analytical: all questions answered with data?
      Scientific: all hypotheses resolved + model validated?
      Experimental: all hypotheses resolved + replicated + model has confirmed prediction?

    === DECIDE ===
    Based on workflow mode + rigor level + current state:

    If BUILD mode:
      Standard pipeline: dispatch builders -> critic review -> merge
      On wave completion: rebase downstream agent branches onto main
        (see "Multi-Wave Rebase Protocol" below)

    If INVESTIGATE mode:
      1. Any findings awaiting Statistician review? -> dispatch Statistician
      2. Any findings awaiting Critic review? -> dispatch Critic
      3. Any findings awaiting replication? -> dispatch replication
      4. Any designs awaiting Methodologist review? -> dispatch Methodologist
      5. Time for synthesis? (2+ new findings since last) -> dispatch Synthesizer
      6. Time for theory? (synthesis updated belief map) -> dispatch Theorist
      7. Theorist produced new predictions? -> create investigation tasks
      8. Hypotheses ready to test? -> dispatch Investigators
      9. Need more hypotheses? -> dispatch Scout + generate from Theorist model
      10. Serendipity budget available + interesting lead? -> dispatch on unexpected finding

    If EXPLORE mode:
      Standard explore pipeline + Statistician review on quantitative comparisons

    If HYBRID mode:
      Detect current phase, apply appropriate mode logic
      Transition when phase convergence criteria met

    === ACT ===
    Spawn/restart agents
    Merge completed work
    Accept validated findings into knowledge store
    Update belief map
    Append to investigation journal
    Broadcast relevant findings to active agents
    Notify user only if: plan approval, strategic pivot, convergence, or paradigm stress

    cycle_count += 1

# If max_cycles reached without convergence:
#   Notify user: "Investigation reached cycle limit ({max_cycles}).
#   Current convergence: {X}%. Options:
#   A) Extend by N cycles
#   B) Accept current findings and close
#   C) Narrow scope to unresolved hypotheses only"
```

### Orchestrator Priority Queue

The DECIDE phase picks the most valuable next action. Priority order:

1. **Statistical review of pending findings** — Nothing enters the knowledge store unreviewed
2. **Methodological review of pending designs** — No experiments run unreviewed (Scientific+)
3. **Critic review of high-impact findings** — Findings that would change direction get adversarial review
4. **Replication of findings that triggered replan** — Verify before pivoting
5. **Synthesis** — When 2+ new findings are available
6. **Theory building** — When synthesis produced updated belief map
7. **New investigation dispatch** — Test the highest-information-gain hypothesis
8. **New build dispatch** — When investigation phase complete and builds are ready
9. **Serendipity pursuit** — When budget allows and a lead looks promising
10. **Scout re-check** — When a surprising finding warrants literature search

### Multi-Wave Rebase Protocol

When Build mode organizes work into sequential waves (Wave 1, Wave 2, etc.), downstream agents need upstream changes:

```
Wave 1 agents complete -> Critic review -> Merge to main
|
v
For each Wave 2 agent already spawned:
  1. Orchestrator runs: git -C <worktree> fetch origin main
  2. Orchestrator runs: git -C <worktree> rebase origin/main
  3. If conflict: orchestrator notifies agent to resolve, OR
     kills agent, respawns on fresh worktree from updated main

For Wave 2 agents not yet spawned:
  1. Spawn from current main (already includes Wave 1)
  2. No rebase needed
```

The orchestrator prefers spawning new agents from updated main over rebasing existing ones. Rebase is only used when an agent is already running and has uncommitted work that would be lost by respawning.

### Information-Gain Hypothesis Selection

When choosing which hypothesis to investigate next, the orchestrator uses:

```
priority(H) = uncertainty(H) * impact(H) * testability(H)
```

Where:
- `uncertainty(H)` = 1 - |prior - 0.5| * 2 (highest at 0.5 prior, zero at 0/1)
- `impact(H)` = number of downstream tasks/hypotheses that depend on H
- `testability(H)` = Methodologist's assessment of how cleanly H can be tested

This replaces simple priority ordering (P1/P2/P3) for investigation tasks. Build tasks still use simple priority.

### Serendipity Budget

Reserve 15% of agent capacity for pursuing unexpected leads. When an agent flags a `SERENDIPITY:HIGH` finding:

1. Orchestrator evaluates: is this plausibly important?
2. If yes AND budget available: snapshot the agent's worktree state, let it pursue the lead for up to 2 OODA cycles
3. If the lead produces a finding: absorb into the knowledge store and replan
4. If inconclusive after 2 cycles: restore snapshot, agent resumes original task
5. File the lead as a low-priority task for future investigation regardless

### Paradigm Check

Every ORIENT phase at Scientific+ rigor:

```
contradictions = count(findings where finding.contradicts(working_model))
if contradictions >= 3:
    flag PARADIGM_STRESS
    notify user: "Multiple findings contradict our working theory. Options:
      A) Revise the model (Theorist will attempt)
      B) Run targeted experiments to resolve contradictions
      C) Step back and re-scout for alternative frameworks"
```

This prevents the system from accumulating anomalies without addressing them — the scientific equivalent of technical debt.

---

## 9. Dependency Relationships

### Relationship Types

| Type | Description |
|------|-------------|
| **blocks** | B cannot start until A is closed |
| **informs** | A's results change how B should be done. B can start speculatively. If A contradicts B's assumptions, orchestrator restarts B |
| **validates** | B independently checks A's result (replication). Both run in parallel. If results disagree, dispatch Critic + Statistician |
| **competes** | A and B are alternative approaches. Orchestrator picks winner, kills loser |
| **requires_review** | B cannot start until a review agent (Methodologist, Statistician, or Critic) approves A's output. This is the gate mechanism |
| **predicts** | A (a theory task) predicts that B's result should be X. If B's result is not X, the theory needs revision. This closes the theory-experiment loop |

### How Gates Work

At Scientific+ rigor, certain task transitions require review:

```
Investigation task created
  -> REQUIRES_REVIEW: Methodologist (design approval)
  -> Investigator executes
  -> Finding produced
  -> REQUIRES_REVIEW: Statistician (quantitative validity)
  -> REQUIRES_REVIEW: Critic (adversarial review)
  -> Finding enters knowledge store
```

At Standard rigor (engineering), the gates are simpler:
```
Build task created
  -> Builder executes
  -> REQUIRES_REVIEW: Critic (code review, inline)
  -> If approved: Merge
  -> If rejected: Builder receives specific objections, retries (up to 3x)
  -> If 3 rejections: escalate to user with Critic's objections + Builder's attempts
```

The gates are the same mechanism; rigor level just controls how many activate.

---

## 10. Convergence Criteria

### Standard Rigor (Engineering)
All build tasks closed and merged. All tests passing.

### Analytical Rigor
All questions answered with quantitative evidence. Statistician has reviewed all findings. No unresolved contradictions.

### Scientific Rigor
1. All hypotheses resolved (confirmed, refuted, or abandoned with justification)
2. Theorist's causal model accounts for all confirmed findings
3. No PARADIGM_STRESS flags unresolved
4. At least one novel prediction from the model has been tested
5. Investigation journal has a complete narrative

### Experimental Rigor
All Scientific criteria PLUS:
6. All high-impact findings independently replicated
7. Pre-registration compliance verified for all experiments (Methodologist sign-off)
8. Meta-analysis of effect sizes across related findings
9. Comprehensive raw data archive committed

### Convergence Can Regress (and That's Correct)

In investigation workflows, the convergence percentage can decrease. This happens when:
- A new finding contradicts the working model (hypotheses reopen)
- The Theorist generates new predictions (adds untested hypotheses)
- Replication fails (a "confirmed" result reverts to "contested")

This is scientifically correct but must be communicated clearly to the user:

```
Convergence: 45% (was 65%)
  Reason: Replication of finding #12 produced different effect size.
  Impact: H1 status changed from CONFIRMED to CONTESTED.
  Action: Dispatching Critic + Statistician to reconcile.
```

The orchestrator always shows the direction of change, the reason, and what it's doing about it. Convergence is not a progress bar — it's a confidence meter.

### Replication Termination

To prevent infinite replication loops:

1. Each finding can be replicated at most **2 times** (original + 2 replications = 3 total measurements)
2. If 2/3 agree: majority result enters the knowledge store
3. If all 3 disagree: finding is marked `CONTESTED`, Critic + Statistician jointly audit all three, and the result is flagged for user attention
4. Replication of a replication is never triggered automatically
5. The user can manually request additional replications via `/swarm replicate <finding-id>`

---

## 11. GitHub Copilot Integration

### Custom Agents (`.github/agents/`)

Each `.agent.md` file defines a Copilot agent persona with YAML frontmatter:

| Agent | Role | User-Invokable |
|-------|------|-----------------|
| `swarm-orchestrator` | Central coordinator: classifies, plans, dispatches, monitors, merges | Yes |
| `worker-agent` | Individual worker executing a single task in isolation | No |
| `theorist` | Builds causal models from evidence, generates predictions | No |
| `methodologist` | Reviews experimental designs before execution | No |
| `statistician` | Reviews quantitative findings for statistical validity | No |

### Agent Skills (`.github/skills/`)

| Skill | Purpose |
|-------|---------|
| `task-planning` | Decomposing features into Beads epics and subtasks |
| `git-worktree-management` | Creating and managing isolated worktrees |
| `beads-tracking` | Using bd for task lifecycle management |
| `agent-standup` | Running progress reports across agents |
| `branch-merging` | Safely merging agent branches to main |
| `investigation-protocol` | Hypothesis to experiment to finding workflow |
| `evidence-system` | Managing findings, belief maps, journal, raw data |

### Reusable Prompts (`.github/prompts/`)

| Prompt | Trigger |
|--------|---------|
| `swarm` | Classify, plan, and dispatch multi-agent workload |
| `standup` | Daily standup report (enhanced for scientific projects) |
| `spawn` | Launch a single agent with appropriate role |
| `merge` | Merge completed branches + accept validated findings |
| `progress` | Quick status check (rigor-aware output) |
| `teardown` | Full cleanup |

---

## 12. Core Components

### CLAUDE.md — The Agent Constitution

Every agent reads this file on boot. It defines mandatory behavior for:
- Task tracking (Beads)
- Git discipline
- Multi-agent awareness
- Quality standards
- Evidence standards (Analytical+ rigor)
- Scientific integrity (Scientific+ rigor)
- Rigor gates

### Configuration (`.swarm-config.json`)

Generated by `swarm-init.sh`:

```json
{
  "project_name": "my-app",
  "project_dir": "/path/to/project",
  "swarm_dir": "/path/to/project-swarm",
  "tmux_session": "my-app-swarm",
  "max_agents": 4,
  "agent_command": "copilot",
  "agent_flags": "--allow-all",
  "agent_flags_safe": [
    "--allow-tool", "shell(git*)",
    "--allow-tool", "shell(python*)",
    "--allow-tool", "shell(bd*)",
    "--deny-tool", "shell(curl*)",
    "--deny-tool", "shell(ssh*)",
    "--deny-tool", "shell(sudo*)"
  ],
  "auto_merge": false,
  "branch_prefix": "agent-",
  "rigor": {
    "default": "auto",
    "serendipity_budget": 0.15,
    "replication_threshold": 0.7,
    "paradigm_stress_threshold": 3,
    "bias_alert_ratio": 0.8,
    "bias_alert_min_sample": 5,
    "max_investigation_cycles": 20,
    "require_pre_registration": "scientific",
    "require_methodologist": "scientific",
    "require_statistician": "analytical",
    "require_adversarial_review": "scientific"
  },
  "created": "2026-03-02T12:00:00Z"
}
```

### Scripts

| Script | Purpose |
|--------|---------|
| `swarm-init.sh` | One-time setup: checks deps, inits Beads, creates `.swarm/`, writes config |
| `spawn-agent.sh` | Creates worktree, opens tmux pane, launches agent |
| `spawn-agent-generic.sh` | Creates directory, opens tmux pane, launches agent (research/generic) |
| `standup.sh` | Queries Beads + git for comprehensive progress report |
| `merge-agent.sh` | Merges agent branch to main, cleans up worktree/tmux |
| `merge-agent-generic.sh` | Assembles output files from generic agent into project |
| `autopilot.sh` | Autonomous daemon: polls, merges, dispatches |
| `plan-tasks.sh` | LLM-powered task decomposition from prompt file |
| `quality-gate.sh` | Pluggable validation (tests, conflicts, custom hooks) |
| `dashboard.py` | Rich terminal UI for live swarm monitoring |
| `teardown.sh` | Removes all worktrees, kills tmux, prunes branches |
| `cron-standup.sh` | Cron-compatible wrapper: writes reports, posts issues |

### Safe Mode

By default, agents run with `--allow-all`. For unattended/server deployments, use safe mode:

```bash
./scripts/autopilot.sh --prompt PROMPT.md --safe
./scripts/spawn-agent.sh --safe <task-id> <branch> "<description>"
```

---

## 13. What the User Sees

### Scenario: Engineering Task

```
You: /swarm Build a full-stack SaaS with auth, billing, and dashboard

Swarm: Classified as: Build / Standard rigor
       [Override: /swarm --mode investigate or /swarm --rigor analytical]

  I'll build this in 3 parallel waves:
  Wave 1: Database schema + Auth service (2 agents)
  Wave 2: Billing integration + API layer (2 agents, after Wave 1)
  Wave 3: Dashboard frontend + Integration tests (2 agents, after Wave 2)

  Each wave includes code review before merge.
  When Wave 1 merges, Wave 2 agents spawn from updated main. Ready to go?

You: go

[Standard engineering workflow — builders + critic reviews]
[User can check /progress or /standup at any time]
[Wave 2 agents auto-spawn after Wave 1 merges — no user intervention]
[If Critic rejects a build: Builder retries with feedback, up to 3x]
[If 3 rejections: user gets notified with the specific issue]
```

### Scenario: Scientific Investigation

```
You: /swarm Figure out why our API latency spiked 3x after the last deploy

Swarm: Classified as: Investigate / Scientific rigor
       [Override: /swarm --mode build or /swarm --rigor standard]

  Phase 0 — Scout: Review deploy diff, recent metrics, error logs, and known
  latency patterns in our stack.

  Phase 1 — Based on scout findings, I'll generate hypotheses, assign priors,
  and test the most informative ones in parallel (2-3 investigators).
  Each experiment design gets Methodologist review.

  Phase 2 — Validated findings feed into a causal model. If the root cause is
  clear, I'll build the fix. If not, I'll test the next round of hypotheses.

  I'll keep you posted on major findings. Check /standup anytime. Ready?

You: go

[15 minutes later]
Swarm: Update — Scout found the deploy changed the ORM query builder.
  Generated 4 hypotheses from scout brief:
  1. N+1 query regression (prior: 0.7 based on deploy diff)
  2. Missing index on new query pattern (prior: 0.5)
  3. Connection pool exhaustion under new load (prior: 0.3)
  4. GC pause accumulation (prior: 0.15, from Theorist)
  Testing top 3 by information gain. Designs approved by Methodologist.

[30 minutes later]
Swarm: Finding — N+1 query confirmed. New endpoint makes 47 queries per request
  vs 3 before. Effect size: 340% latency increase (CI: [290%, 390%]).
  Connection pooling hypothesis refuted (no significant effect).
  Index hypothesis still testing.

  I'm pivoting to build mode: dispatching a builder to fix the N+1 with eager
  loading, and a second investigator to verify no other regressions.

[No further user interaction needed until completion]

--- User can inject at any time: ---
You: I think it might be the new middleware, not the ORM
Swarm: Adding hypothesis: "Middleware overhead" (prior: 0.5 based on your input).
  Queuing investigation after current round completes.
```

### Scenario: Experimental Science

```
You: /swarm Run the BevCo RGM experiment — full framework validation
  with all 4 experiments, ablation study, and paper generation

Swarm: This is a formal experimental project. I'll use full scientific rigor.

  Phase 0 — Scout: Read PROMPT.md, understand ground truth structure, identify
  the 5 planted interaction effects and evaluation criteria.

  Phase 1 — Foundation (parallel, 2 agents):
    Core types + data generation (with embedded ground truth)
    Policy + expert belief generation

  Phase 2 — Encoding layer (1 agent, needs core types):
    Statistical profiles, constraint vectors, temporal beliefs, cross-encoder

  Phase 3 — Diagnostic agents (5 agents in parallel):
    Elasticity, Interaction, Constraint, Temporal, Portfolio
    Each agent's experimental design reviewed before execution
    Raw diagnostic data preserved for ablation comparison

  Phase 4 — Synthesis + Quality Gate (sequential):
    Causal assembler combines evidence packets
    Multi-dimensional quality gate filters candidates

  Phase 5 — Experiments (4 experiments, mix of parallel and sequential):
    Exp 1: Encoding validation (needs encoding layer)
    Exp 2: Ablation study (needs full pipeline)
    Exp 3: Progressive reduction measurement (needs pipeline)
    Exp 4: Cross-domain generalization (needs pipeline)
    Statistician reviews all quantitative results
    Critic validates each experiment's methodology

  Phase 6 — Paper + Webapp (parallel, need experiment results):
    LaTeX paper with figures, tables from real data
    Interactive webapp dashboard

  14 agents across 6 waves. Estimated completion: 2-3 hours.
  All experiments will be pre-registered and results independently validated.
  Ready?
```

### The /standup Command (Enhanced)

For engineering projects, standup looks identical to current output. For scientific projects:

```
You: /standup

=== INVESTIGATION STATUS ===

Belief Map:
  H1: N+1 query regression — CONFIRMED (p<0.0001, d=3.4, replicated)
  H2: Connection pool exhaustion — REFUTED (p=0.73, d=0.02)
  H3: Missing index — IN PROGRESS (Agent 3, 12 commits, 5min ago)
  H4: GC pause accumulation — QUEUED (prior: 0.15, from theorist)

Findings (3 validated, 1 pending review):
  #12 "N+1 regression: 47 queries/request" — quality: 0.94
  #14 "Pool exhaustion: no effect" — quality: 0.88
  #15 "Deploy diff: ORM change isolated to /api/users" — quality: 0.91
  #16 "Index scan on users_orders table" — AWAITING STATISTICIAN

Working Theory:
  "Latency spike caused by ORM query builder change introducing N+1 pattern
   on /api/users endpoint. The eager-loading removal in commit abc123 causes
   47 individual queries where 3 previously existed."

  Predictions: Fix N+1 -> latency returns to baseline (testing in progress)

Agent Activity:
  agent-n1-fix      12 commits  3 min ago  Building eager-loading fix
  agent-index       8 commits   5 min ago  Testing index hypothesis
  agent-validate    (queued)               Will verify fix reduces latency

Convergence: 65% (2/4 hypotheses resolved, fix in progress, 1 prediction pending)
```

### The /progress Command (Enhanced)

```
You: /progress

Tasks:     8 total | 3 closed | 2 in-progress | 2 queued | 1 review
Findings:  3 validated | 1 pending | 0 contradicted
Hypotheses: 2/4 resolved (1 confirmed, 1 refuted)
Theory:    current — N+1 regression model (1 prediction pending)
Rigor:     Scientific | Pre-reg: 3/3 compliant | Replications: 1/1 confirmed
Converge:  65%
```

### User Interaction Model

The orchestrator minimizes interruptions while keeping the user informed and in control.

**Mandatory user touchpoints** (system pauses for confirmation):
1. Initial plan presentation — before any agents spawn
2. Paradigm stress — when 3+ findings contradict the working model
3. Cycle limit reached — when max_investigation_cycles is hit without convergence

**Informational updates** (system continues without waiting):
- Major finding validated (direction-changing)
- Mode transition (investigate -> build)
- Convergence regression with reason
- Replication mismatch detected

**User can always**:
- Inject a hypothesis: "I think it might be X" — orchestrator adds it to the belief map with user-assigned or default prior (0.5)
- Override classification: `/swarm --mode build` or `/swarm --rigor standard`
- Force-close: `/swarm stop` — saves state, all agents stop, work can be resumed
- Request specific action: `/swarm replicate <finding-id>` or `/swarm investigate <hypothesis>`

**The orchestrator never**:
- Asks for confirmation on routine OODA decisions
- Asks whether to continue after each finding
- Blocks on Theorist/Synthesizer output (these run asynchronously)

---

## 14. Workflow: End to End

### Step 0 — Clone and initialize
```bash
git clone https://github.com/yourorg/agent-swarm-template my-app
cd my-app
./scripts/swarm-init.sh
```

### Step 1 — Plan and dispatch
```
claude
> /swarm Build a full-stack task management app with auth, REST API, React frontend, and PostgreSQL backend
```

### Step 2 — Monitor
```bash
tmux attach -t my-app-swarm    # Watch agents work in real time
> /progress                     # Quick check
```

### Step 3 — Standup
```
> /standup
```

### Step 4 — Merge and re-dispatch
```
> /merge
> /swarm continue
```

`/swarm continue` is not a 7th command — it's the same `/swarm` command with the keyword `continue`. It triggers the orchestrator to:
1. Read Beads state (open tasks, closed tasks, findings)
2. Read `.swarm/journal.md` for narrative context (if investigation)
3. Read the belief map (if investigation)
4. Resume the OODA loop from where it left off

This is the **Session Recovery Protocol** — how the stateless orchestrator reconstructs state after a session break:

```
Session Recovery:
  1. Read .swarm-config.json (project settings, rigor config)
  2. bd prime (loads Beads context)
  3. bd list --json (all tasks: status, type, notes)
  4. Parse findings from Beads (TYPE:finding entries)
  5. Parse belief map from Beads (BELIEF_MAP entries)
  6. Read .swarm/journal.md (narrative, last cycle number)
  7. Check tmux session (are agents still running?)
  8. Check git worktrees (which branches exist?)
  9. Reconstruct OODA state: what cycle are we on? What's pending?
  10. Present summary to user and resume
```

For Build mode, steps 4-6 are skipped (no evidence layers).

### Step 5 — Repeat until epic is done

### Step 6 — Cleanup
```
> /teardown
```

---

## 15. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Science-first architecture** | Science needs everything engineering needs, plus more. Engineering is a simplified path through the same system. Zero overhead for build-only projects. |
| **Auto-classified rigor levels** | Users should not configure rigor. The system infers it from the prompt and escalates if needed. |
| **OODA loop over linear pipeline** | Investigations are inherently iterative. A linear plan-dispatch-merge flow cannot handle hypothesis revision, replication requests, or paradigm shifts. |
| **Evidence as first-class entities** | Findings with raw data, statistical quality scores, and review chains are fundamentally different from task completion status. They need their own system. |
| **9 roles auto-selected by task** | Roles activate based on mode + rigor. No configuration. Standard build = 2 roles. Full investigation = 9 roles. |
| **Beads over markdown plans** | Structured dependency graph with hash-based IDs; `bd ready` answers in milliseconds |
| **Git worktrees over clones** | Shared `.git` directory; faster, less disk space; natural `git diff` across branches |
| **tmux over background processes** | Visual observability; scroll output; intervene in real time |
| **Agent CLI `-p` flag** | Non-interactive execution; agent receives instructions, does work, exits |
| **Max 4 agents** | Balances merge complexity, database contention, and human review overhead |
| **Information-gain hypothesis selection** | Replaces simple priority ordering. Always test the hypothesis that would teach us the most, not just the one marked P1. |
| **Mandatory pre-registration** | Prevents p-hacking and post-hoc rationalization. Analysis plans are locked before experiments run. |
| **Serendipity budget (15%)** | Strict scope prevents serendipitous discoveries. Reserving capacity for unexpected leads captures high-value outliers. |
| **Platform-agnostic design** | The architecture works with both Claude Code (`.claude/commands/`) and GitHub Copilot (`.github/agents/`). Prompts, skills, and agent definitions are stored in `.github/` (Copilot-native). Claude Code uses `.claude/commands/` that reference the same logic. The orchestrator's behavior is defined once in the agent/prompt files; the platform is just the execution environment. Users pick one platform — the design doesn't require both simultaneously. |

---

## 16. Autopilot Mode

The `scripts/autopilot.sh` daemon eliminates human-in-the-loop orchestration by implementing a continuous poll-merge-dispatch cycle.

### How It Works

```
User runs: ./scripts/autopilot.sh [--dashboard /tmp/swarm.txt]

AUTOPILOT LOOP:
  1. Dispatch all bd-ready tasks (up to max_agents)
  2. Sleep poll_interval (30s)
  3. For each active agent:
     - Beads task closed? -> quality gate -> merge
     - tmux window gone?  -> check results -> merge/retry
     - Timeout exceeded?  -> kill -> retry (up to 3x)
  4. Check bd ready for newly unblocked tasks
  5. Dispatch next wave
  6. Repeat until no open work remains
```

### Quality Gates

`scripts/quality-gate.sh` runs before every merge:
1. Branch must have commits
2. Beads task must be closed
3. No merge conflicts with main
4. Tests must pass (auto-detects Python pytest / Node npm test)
5. Custom gate hook (`.swarm-quality-gate.sh`) if present

Failed gates trigger a retry with error context (up to `--max-retries`).

### Usage

```bash
# ZERO-TOUCH: From prompt file to finished project
./scripts/autopilot.sh --prompt PROMPT.md --dashboard /tmp/swarm.txt

# Research domain (plain directories, no git branching):
./scripts/autopilot.sh --prompt research-brief.md --domain research

# Pre-planned tasks (Beads already populated):
./scripts/autopilot.sh

# With live TUI dashboard (separate terminal):
python3 scripts/dashboard.py --refresh 3
```

### Domain Support

| Domain | Isolation | Merge Strategy | Quality Gate |
|--------|-----------|---------------|--------------|
| `code` (default) | Git worktrees | `git merge` | Tests + conflict check |
| `research` | Plain directories | File assembly | Summary check |
| `generic` | Plain directories | File assembly | Custom hook |

---

## 17. File-by-File Change Specification

This section details every file that must be modified or created to implement the full design.

### Files to MODIFY

#### `CLAUDE.md` — Agent Constitution

**Add** Evidence Standards, Rigor Gates, Investigation Protocol, and Scientific Integrity sections.

#### `AGENTS.md` — Compatibility Alias

**Add** Finding Protocol subsection under "Issue Tracking with bd" documenting the structured finding creation workflow.

#### `.github/agents/swarm-orchestrator.agent.md` — Orchestrator Agent

**Replace** Core Responsibilities with 8-item list covering: Classify, Plan, Cast, Dispatch, Monitor (OODA), Synthesize, Merge, Converge. **Add** Rigor Classification table, Information-Gain Prioritization formula, Paradigm Check logic, and Bias Monitor. **Replace** linear Workflow with OODA-based workflow.

#### `.github/agents/worker-agent.agent.md` — Worker Agent

**Add** Evidence Standards section and Unexpected Findings section. **Replace** Completion Checklist with separate checklists for Build Tasks and Investigation Tasks.

#### `.github/prompts/swarm.prompt.md` — /swarm Command

**Add** Phase 0: Classify and Phase 0.5: Scout. **Rewrite** Phase 1: Plan with mode-specific decomposition (Build/Investigate/Explore/Hybrid). **Replace** Phase 2: Dispatch with Cast and Dispatch (role selection table by mode x rigor). **Replace** Phase 3: Monitor with OODA Loop.

#### `.github/prompts/standup.prompt.md` — /standup Command

**Add** Scientific+ rigor sections: Belief Map, Findings summary, Working Theory, Rigor Compliance, Convergence percentage.

#### `.github/prompts/progress.prompt.md` — /progress Command

**Add** findings, investigation journal tail, rigor-aware compact display.

#### `.github/prompts/merge.prompt.md` — /merge Command

**Add** finding gate verification and knowledge store acceptance steps.

#### `.github/prompts/spawn.prompt.md` — /spawn Command

**Add** Methodologist review gate check for investigation tasks at Scientific+ rigor.

#### `.swarm-config.json` (template in `swarm-init.sh`)

**Add** `rigor` configuration block with all threshold and gate settings.

#### `templates/agent-prompt.md` — Worker Agent Template

**Add** investigation-specific fields and evidence reporting instructions.

#### `templates/standup-report.md` — Standup Report Template

**Add** scientific project sections: Belief Map, Findings, Working Theory, Convergence.

#### `templates/epic-template.md` — Epic Template

**Add** investigation mode sections: hypothesis list, expected information gain, rigor level.

#### `scripts/swarm-init.sh` — Initialization

**Add** `.swarm/` directory creation and `journal.md` initialization.

### Files to CREATE

| File | Purpose |
|------|---------|
| `.github/agents/theorist.agent.md` | Causal model builder agent |
| `.github/agents/methodologist.agent.md` | Experimental design review agent |
| `.github/agents/statistician.agent.md` | Quantitative rigor gatekeeper agent |
| `.github/skills/investigation-protocol/SKILL.md` | Hypothesis to experiment to finding workflow |
| `.github/skills/evidence-system/SKILL.md` | Findings, belief maps, journal, raw data management |
| `templates/investigator-prompt.md` | Template for investigator agent prompts |
| `.swarm/journal.md` | Investigation journal (created at swarm init) |

### Files UNCHANGED

- `.github/prompts/teardown.prompt.md` — Cleanup is infrastructure-level, rigor-agnostic
- `.github/workflows/daily-standup.yml` — GitHub Actions workflow
- `.github/workflows/agent-ci.yml` — CI pipeline
- `.github/skills/beads-tracking/SKILL.md` — Beads commands unchanged
- `.github/skills/git-worktree-management/SKILL.md` — Worktree management unchanged
- `.github/skills/branch-merging/SKILL.md` — Merge process unchanged
- `scripts/teardown.sh` — Cleanup unchanged
- `scripts/dashboard.py` — Dashboard unchanged
- `scripts/quality-gate.sh` — Gate logic unchanged
- `scripts/merge-agent.sh` — Merge mechanics unchanged
- `scripts/merge-agent-generic.sh` — Generic merge unchanged
- `scripts/spawn-agent-generic.sh` — Generic spawn unchanged
- `scripts/cron-standup.sh` — Cron wrapper unchanged
- `scripts/autopilot.sh` — Autopilot unchanged (OODA logic lives in orchestrator, not script)

---

## 18. Summary

| Dimension | Design |
|-----------|--------|
| Roles | 9 (builder, investigator, scout, critic, synthesizer, explorer, theorist, methodologist, statistician) |
| Workflow modes | 4 (build, investigate, explore, hybrid) |
| Rigor levels | 4 (standard, analytical, scientific, experimental) — auto-classified |
| Task types | 6 (build, investigation, exploration, review, replication, theory) |
| Evidence | Findings with raw data, belief maps, investigation journal |
| Decision logic | OODA loop with information-gain prioritization |
| Hypothesis mgmt | Belief maps, priors, information-gain ranking |
| Statistical rigor | Statistician role, mandatory CI/effect-size/p-value, multiple comparison correction |
| Experimental design | Methodologist review, pre-registration, confound tracking |
| Theory building | Theorist role, causal models, novel predictions |
| Replication | Replication tasks, policy-driven trigger, independent verification |
| Bias prevention | Adversarial audits, confirmation ratio tracking, pre-registration |
| Serendipity | Budget (15%), escalation flags, snapshot/restore |
| Convergence | Rigor-appropriate: tasks to findings to theory to prediction |
| User experience | One prompt — rigor and mode auto-detected |
| Commands | Same 6 — richer output at higher rigor levels |
| Config required | None — everything auto-classified |
