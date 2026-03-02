# Universal Agent Swarm — Science-First Design

## Project Name: `agent-swarm-template`

A production-ready template for orchestrating multiple AI agents in parallel. Designed from first principles around scientific rigor — science needs everything engineering needs (parallel execution, isolation, merging, task tracking) plus hypothesis management, experimental rigor, statistical validation, and bias prevention. Design for science; engineering works by skipping the science-specific gates.

**The user types one prompt.** The system classifies, adapts, and executes.

---

## 1. Design Philosophy

- **Science is a superset of engineering.** Engineering is a scientific workflow with rigor gates turned off.
- **Zero user burden.** `/swarm <prompt>` auto-detects mode and rigor. Same 6 commands. Richer output only when warranted.
- **Evidence over opinion.** Every quantitative claim requires effect size, CI, sample size, and statistical test. Raw data preserved. Negative results valued equally.
- **Convergence over completion.** Engineering is done when tasks close. Science is done when hypotheses are resolved, the causal model accounts for all observations, and a novel prediction is confirmed.

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
│  └─────────┘ └──────────┘ └──────────┘ └─────────────────┘ │
│                                              ↓              │
│  FINAL EVALUATION — Score output vs. original abstract      │
│  Max 2 improvement rounds · Diminishing returns detection   │
├─────────────────────────────────────────────────────────────┤
│  ROLE REGISTRY — 11 roles, auto-selected by task type       │
├─────────────────────────────────────────────────────────────┤
│  EVIDENCE SYSTEM — Findings, raw data, journal, beliefs     │
│  Strategic Context — Decision rationale, dead ends, gaps    │
├─────────────────────────────────────────────────────────────┤
│  INFRASTRUCTURE — Worktrees · Beads · tmux · git            │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. The Classifier

### Workflow Mode

| Mode | Description | Example |
|------|-------------|---------|
| **Build** | Implement software artifacts | "Build a REST API with auth" |
| **Investigate** | Answer questions with evidence | "Why is our API latency 3x higher?" |
| **Explore** | Evaluate options against criteria | "Which database should we migrate to?" |
| **Hybrid** | Multiple phases with mode transitions | "Figure out the bottleneck and fix it" |

### Rigor Level

| Level | Activates | Example Signal |
|-------|-----------|----------------|
| **Standard** | Builder, Critic | "build", "create", "ship" |
| **Analytical** | + Scout, Statistician | "optimize", "improve", "compare" |
| **Scientific** | + Methodologist, Theorist, all gates | "why", "investigate", "root cause" |
| **Experimental** | Full pipeline + replication | "test whether", "experiment" |

The user never sees rigor levels. Build → Standard. Investigate → Scientific. Explore → Analytical. Hybrid → highest of its phases. **When in doubt, classify higher** — gates can be skipped but not added retroactively.

**Scout activation:** Mandatory for Investigate/Explore/Hybrid. Skipped for Build (unless ambiguous).

**Override:** User can override at plan presentation (`/swarm --mode build`) or mid-flight. Escalation is automatic; de-escalation requires user confirmation.

---

## 4. Role Registry

| Role | Trigger | Key Responsibility |
|------|---------|-------------------|
| **Builder** 🔨 | Build tasks | Implements code in isolated worktree |
| **Investigator** 🔬 | Analytical+ investigation | Tests hypotheses, collects data, reports with evidence. Pre-registers outcomes. Runs sensitivity analysis (2+ parameter variations at Scientific+). Commits raw data with SHA-256 hash. |
| **Scout** 🔍 | Phase 0 of Investigate/Explore/Hybrid | Researches existing knowledge before work starts. Produces structured brief with known results, failed approaches, suggested hypotheses. Identifies SOTA methodology at Scientific+. |
| **Critic** ⚖️ | Before any merge or finding acceptance | Stress-tests output. Inline review for Build; full agent at Scientific+. Uses Structured Checklist (§6.8). Partially blinded at Scientific+ (sees data but not hypothesis). Adversarial loop up to 3 rounds. |
| **Synthesizer** 🧩 | 2+ agents complete related tasks | Integrates results, produces final deliverable (`.swarm/deliverable.md`), maintains journal and belief map. Runs pairwise consistency checks at Scientific+. |
| **Evaluator** 🎯 | Before convergence at Analytical+ | Scores deliverable: Completeness (30%), Coherence (25%), Strength (25%), Actionability (20%). Generates improvement tasks on IMPROVE/FAIL. Max 2 improvement rounds. |
| **Explorer** 🧭 | Explore-mode tasks | Generates and evaluates options against criteria with comparison matrices |
| **Theorist** 🧬 | Scientific+, after belief map update | Builds causal models, generates testable predictions (which become new tasks). Must propose competing theories with discriminating predictions. Monitors for paradigm stress. |
| **Methodologist** 📐 | Scientific+, before investigation starts | Reviews experimental designs. Checks controls, sample sizes, stat tests, confounds. Requires power analysis. Compares against SOTA. Batch-reviews multiple designs in one pass. |
| **Statistician** 📊 | Analytical+, on quantitative findings | Reviews CI, effect sizes, test appropriateness. Verifies data integrity (SHA-256). Applies family-wise error correction. Flags p-hacking indicators. |
| **Worker** | Generic tasks | General-purpose agent for tasks that don't fit specialized roles |

---

## 5. Task Types

```
TASK_TYPE:  build | investigation | exploration | review | replication | theory
RIGOR:      standard | analytical | scientific | experimental
STATUS:     open | claimed | in_progress | review | closed | abandoned
RESULT:     success | negative | inconclusive | refuted | N/A
```

**Investigation tasks at Scientific+ rigor** require pre-registration fields: HYPOTHESIS, METHOD, CONTROLS, EXPECTED_RESULT, CONFOUNDS, STAT_TEST, SAMPLE_SIZE, POWER_ANALYSIS, SENSITIVITY_PLAN.

**Gate chain (Scientific+):**
1. Methodologist reviews design (including power analysis + SOTA compliance)
2. Investigator executes, commits raw data with SHA-256 hash
3. Investigator runs sensitivity analysis (2+ parameter variations)
4. Statistician verifies data integrity + reviews quantitative results
5. Critic performs partially-blinded adversarial review
6. If objection: Adversarial Loop (up to 3 rounds)
7. Synthesizer runs consistency check against existing findings
8. Finding enters knowledge store

**Build tasks:** Builder executes → Critic reviews (inline) → Merge. Up to 3 rejection-retry cycles before user escalation.

**Replication policy:** Triggered when a finding would change direction, has wide CI (>30% of effect), contradicts the model, or has quality score <0.7. Max 2 replications per finding. Agreement requires overlapping 95% CIs or TOST equivalence test.

---

## 6. Scientific Rigor Framework

### 6.1 Evidence Layers

| Layer | Location | Purpose |
|-------|----------|---------|
| **Findings** | Beads entries with structured notes | Unit of knowledge: effect size, CI, N, stat test, data hash, robustness |
| **Raw Data** | `<worktree>/data/raw/` | CSV/JSON committed per experiment; referenced by findings |
| **Journal** | `.swarm/journal.md` | Narrative continuity across OODA cycles — state, key findings, next actions |
| **Belief Map** | Beads entry | Hypothesis probabilities updated per cycle; drives information-gain prioritization |
| **Strategic Context** | `.swarm/strategic-context.md` | Decision rationale, dead ends, gaps, progress velocity |
| **Deliverable** | `.swarm/deliverable.md` | Final output artifact scored by Evaluator |

### 6.2 Consistency Gate

After integrating a new finding, Synthesizer performs pairwise comparison against all validated findings. Contradictions flag `CONSISTENCY_CONFLICT` which **blocks convergence** until resolved via re-experiment, moderating variable identification, or causal model update.

### 6.3 Sensitivity Analysis

Every finding must test 2+ parameter variations (±50% default). A finding is **ROBUST** if the conclusion holds across all variations, **FRAGILE** if it breaks (with documented conditions). All findings must be ROBUST or FRAGILE-with-conditions for convergence.

### 6.4 Adversarial Loop

Critic objects → Investigator responds with data → Critic evaluates → up to 3 rounds → unresolved = CONTESTED (cannot contribute to convergence). Arbitration by Methodologist + Statistician if round 3 fails.

### 6.5 Partial Blinding (Scientific+)

Critic receives raw data, methodology, and stat results — but NOT the hypothesis direction. Critic forms independent interpretation before the hypothesis is revealed. Conflicts trigger the adversarial loop.

### 6.6 SOTA Anchoring

Scout identifies best-known methodology for the domain. Methodologist enforces compliance — deviations from SOTA require documented justification.

### 6.7 Power Analysis (Scientific+)

Every experiment requires: minimum detectable effect size, alpha, target power (≥0.80), and computed minimum N. Experiments without power analysis cannot produce findings above CONFIDENCE:medium.

### 6.8 Structured Critic Checklist

Every Critic review addresses all five checks explicitly:

| Check | Question | Verdict |
|-------|----------|---------|
| CONFOUNDS | Uncontrolled variables that could explain the result? | PASS / CONCERN / FAIL |
| ALT_EXPLANATIONS | Alternative theories that could produce the same data? | PASS / CONCERN / FAIL |
| DATA_QUALITY | Outliers, missing data, floor/ceiling effects? | PASS / CONCERN / FAIL |
| STAT_VALIDITY | Statistical test assumptions met and appropriate? | PASS / CONCERN / FAIL |
| GENERALIZABILITY | Conditions under which this finding might NOT hold? | PASS / CONCERN / FAIL |

A single FAIL triggers the adversarial loop.

### 6.9 Competing Theories (Scientific+)

Theorist must propose ≥2 competing causal models with discriminating predictions. At least one discriminating experiment must run. Investigation cannot converge with only one theory considered.

### 6.10 Data Integrity Chain

Investigator computes SHA-256 of raw data files immediately after collection. Statistician independently verifies hash before review. Mismatch → finding quarantined.

---

## 7. Workflow Engine — OODA Loop

### Investigation Bootstrap (before first cycle)

1. **Scout** → knowledge brief (known results, failed approaches, suggested hypotheses)
2. **Orchestrator** generates 3–7 hypotheses with priors, testability, impact
3. **Theorist** (Scientific+ only) refines hypotheses, adjusts priors, adds non-obvious ones
4. **Belief Map** created with all hypotheses and priors
5. **Tasks created** for top-priority hypotheses ranked by `uncertainty × impact × testability`
6. **Methodologist** (Scientific+) batch-reviews all designs
7. **Enter OODA loop**

Build mode skips bootstrap — decomposes prompt into build tasks directly.

### OODA Cycle

**Observe:** Read Beads status, knowledge store (new findings), journal, belief map, git activity.

**Orient:** Classify events (completion, finding, negative result, conflict, stall, paradigm stress). Run bias check (confirmed/refuted ratio >0.8 with sample >5 = warning). Run convergence check.

**Decide (priority order):**
1. Statistical review of pending findings
2. Methodological review of pending designs
3. Critic review of high-impact findings
4. Replication of direction-changing findings
5. Synthesis (when 2+ new findings available)
6. Theory building (when synthesis updated belief map)
7. New investigation dispatch (highest information-gain hypothesis)
8. New build dispatch
9. Serendipity pursuit (15% budget)
10. Scout re-check (surprising findings)

**Act:** Spawn/restart agents, merge work, accept findings, update belief map, append journal, notify user only on plan approval, strategic pivot, convergence, or paradigm stress.

### Multi-Wave Rebase (Build Mode)

Wave N completes → merge to main → spawn Wave N+1 from updated main. Prefer spawning fresh over rebasing existing worktrees.

### Information-Gain Hypothesis Selection

```
priority(H) = uncertainty(H) × impact(H) × testability(H)
```

Where `uncertainty(H) = 1 - |prior - 0.5| × 2` (highest at 0.5, zero at 0/1).

### Paradigm Check (Scientific+)

If 3+ findings contradict the working model → `PARADIGM_STRESS` flag → user notified with options to revise model, run targeted experiments, or re-scout.

### Serendipity Budget

Reserve 15% of agent capacity for unexpected leads. Snapshot worktree, pursue for 2 cycles, absorb or restore.

---

## 8. Dependencies and Gates

### Relationship Types

| Type | Description |
|------|-------------|
| **blocks** | B cannot start until A closes |
| **informs** | A's results change how B should be done; B can start speculatively |
| **validates** | B independently checks A (replication); both run in parallel |
| **competes** | Alternative approaches; orchestrator picks winner |
| **requires_review** | B needs review agent approval of A's output |
| **predicts** | A (theory) predicts B's result; mismatch → theory revision |

### Artifact Contracts (File-Level Dependencies)

Tasks declare file-level contracts in Beads notes:

| Property | Meaning |
|----------|---------|
| `PRODUCES:file1, file2` | Files task MUST create before passing quality gate |
| `REQUIRES:file1, file2` | Files that MUST exist before task dispatches |
| `GATE:path/to/report.json` | Validation file that must exist AND contain PASS verdicts |

**Enforcement:** Pre-flight check (before dispatch) verifies REQUIRES/GATE. Quality gate (before merge) verifies PRODUCES. Agent prompt includes the contract.

---

## 9. Convergence Criteria

| Rigor | Criteria |
|-------|----------|
| **Standard** | All build tasks closed and merged. Tests passing. |
| **Analytical** | All questions answered with quantitative evidence. Statistician reviewed all findings. No contradictions. |
| **Scientific** | All hypotheses resolved. Causal model accounts for all findings. No PARADIGM_STRESS. ≥1 novel prediction tested. No CONSISTENCY_CONFLICTs. ≥1 competing theory ruled out. All findings ROBUST or FRAGILE-documented. |
| **Experimental** | All Scientific criteria + all high-impact findings replicated (formal agreement). Pre-reg compliance verified. Meta-analysis complete. Raw data archived with verified hashes. All adversarial loops resolved. Power analysis documented for every experiment. |

**Convergence can regress** — new contradictions reopen hypotheses, failed replications revert confirmed findings. The orchestrator shows direction, reason, and action taken.

**Replication termination:** Max 2 replications per finding (3 total measurements). 2/3 agree → majority wins. All 3 disagree → CONTESTED + user attention.

### Final Evaluation (Analytical+)

1. Synthesizer produces deliverable (`.swarm/deliverable.md`)
2. Evaluator scores: COMPLETENESS (0.30) + COHERENCE (0.25) + STRENGTH (0.25) + ACTIONABILITY (0.20)
3. ≥0.75 → PASS. 0.50–0.74 → IMPROVE (targeted tasks, 1–2 more cycles). <0.50 → FAIL + user flag.
4. Max 2 improvement rounds. If last 2 rounds each improved <5% → DIMINISHING_RETURNS → deliver with quality disclosure.

---

## 10. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Science-first architecture** | Engineering is a simplified path through the science system. Zero overhead for build-only projects. |
| **Auto-classified rigor** | Users don't configure rigor. System infers and can escalate. |
| **OODA over linear pipeline** | Investigations are iterative — hypothesis revision, replication, paradigm shifts need loops. |
| **Evidence as first-class** | Findings with raw data, quality scores, and review chains differ fundamentally from task status. |
| **11 roles auto-selected** | Standard build = 2 roles. Full investigation = all 11. No configuration. |
| **Beads over markdown plans** | Structured dependency graph; `bd ready` in milliseconds. |
| **Git worktrees over clones** | Shared `.git`, faster, less disk, natural cross-branch diff. |
| **tmux for observability** | Visual monitoring, scroll output, real-time intervention. |
| **Information-gain prioritization** | Always test what teaches us most, not just what's marked P1. |
| **Mandatory pre-registration** | Prevents p-hacking and post-hoc rationalization. |
| **Serendipity budget (15%)** | Captures high-value outliers that strict scope would miss. |
| **Platform-agnostic** | Works with Claude Code (`.claude/commands/`) and Copilot (`.github/agents/`). |

---

## 11. Autopilot Mode

`scripts/autopilot.sh` — continuous poll-merge-dispatch daemon:

1. Dispatch all `bd ready` tasks (up to `max_agents`)
2. Sleep `poll_interval` (30s)
3. Check active agents: closed → quality gate → merge; timeout → retry (3x max)
4. Dispatch newly unblocked tasks
5. Repeat until no open work

**Quality gates** (`quality-gate.sh`): Branch has commits, Beads task closed, no merge conflicts, tests pass, PRODUCES artifacts exist, custom hook passes.

**Domains:** `code` (worktrees, git merge), `research`/`generic` (plain directories, file assembly).

---

## 12. Multi-Project Scalability

### Problem

One swarm per repo creates sequential bottlenecks, cross-contamination risk, and no global visibility across projects.

### Solution: Namespace + Global Hub

- **Project ID** scopes all shared resources (tmux sessions, worktrees, branches)
- **`~/.swarm/hub.json`** — global registry of all active projects with status, agent count, convergence
- **Resource pool** — `~/.swarm/resources.json` enforces global agent limits across projects (proportional, priority, equal, or manual allocation)
- **Epic isolation** — concurrent swarms in the same repo via Beads epic scoping with separate branch namespaces (`swarm/<epic-id>/agent-*`) and per-epic journals

### Hub Operations

`swarm hub list | switch <id> | pause <id> | resume <id> | remove <id> | dashboard`

### Key Properties

- Zero-cost for single-project users (hub is created on first `swarm-init.sh`, all scripts fall back without it)
- Each project stays in its own repo — natural isolation
- Heartbeat-based stale project detection
- Collision protection via disambiguated project IDs

---

## 13. Summary

| Dimension | Design |
|-----------|--------|
| Roles | 11 (builder, investigator, scout, critic, synthesizer, evaluator, explorer, theorist, methodologist, statistician, worker) |
| Workflow modes | 4 (build, investigate, explore, hybrid) |
| Rigor levels | 4 (standard, analytical, scientific, experimental) — auto-classified |
| Task types | 6 (build, investigation, exploration, review, replication, theory) |
| Evidence | Findings + raw data + belief maps + journal + strategic context |
| Decision logic | OODA loop with information-gain prioritization |
| Convergence | Rigor-appropriate: tasks → findings → theory → prediction |
| User experience | One prompt — everything auto-detected |
| Commands | Same 6 — richer output at higher rigor |
| Config required | None |