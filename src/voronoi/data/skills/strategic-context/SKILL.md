---
name: strategic-context
description: >
  Skill for maintaining the Strategic Context Document — a living document that
  preserves the original intent, decision rationale, dead ends, and remaining gaps
  across OODA cycles and sessions. Prevents context degradation in long-running tasks.
user-invocable: true
disable-model-invocation: false
---

# Strategic Context Skill

Maintaining strategic continuity across OODA cycles and sessions.

## When to Use

Use this skill whenever the orchestrator starts a new investigation/exploration/hybrid workflow,
at the beginning of each OODA cycle, and during session recovery.

## The Problem This Solves

Long-running tasks span many OODA cycles and potentially multiple sessions. Without strategic
context, agents lose track of:
- WHY certain directions were chosen over others
- Which approaches were already tried and abandoned
- How the current interpretation of the abstract evolved
- What gaps remain in the answer

`bd prime` gives task state but not strategic reasoning. The journal captures cycle summaries
but not decision rationale. This skill fills that gap.

## Strategic Context Document

**Location:** `.swarm/strategic-context.md`

**Created by:** Orchestrator, at workflow start (Phase 1).

**Updated by:** Orchestrator, at the beginning of each OODA Orient phase.

**Read by:** All agents (injected into worker prompts as `STRATEGIC_CONTEXT`), Synthesizer, Evaluator.

### Document Format

```markdown
# Strategic Context

## Original Abstract
[Verbatim user input — NEVER modified after creation]

## Current Interpretation
[How the orchestrator is reading the abstract NOW — may evolve as findings arrive]
Last updated: Cycle N — YYYY-MM-DD

## Decisions and Rationale
| Cycle | Decision | Rationale | Alternatives Considered |
|-------|----------|-----------|------------------------|
| 1 | Prioritized H1 over H2 | H1 has higher information gain (0.72 vs 0.45) | Could have tested H2 first but it depends on H1's outcome |
| 3 | Pivoted from CPU to I/O investigation | Finding F2 ruled out CPU bottleneck | Could have replicated F2 first, but confidence was high (0.91) |
| 5 | Escalated rigor from Analytical to Scientific | Finding F4 contradicted working model | Could have accepted F4 at face value |

## Dead Ends
| Approach | Cycle Abandoned | Why | Key Finding |
|----------|----------------|-----|-------------|
| Redis caching hypothesis | Cycle 3 | Effect vanished under realistic load | F3: d=0.02, CI[-0.1, 0.14] |
| Connection pooling as root cause | Cycle 4 | Profiling showed <2% of latency | F5: 18ms/890ms total |

## Remaining Gaps
| Gap | Severity | Why Unresolved | Potential Path |
|-----|----------|----------------|----------------|
| Impact on cold-start latency | Medium | Not yet tested | Need investigation task with cold-start specific benchmark |
| Long-term cache degradation | Low | Out of scope for current investigation | Could be follow-up investigation |

## Progress Velocity
| Cycle | Eval Score | Delta | Hypotheses Resolved | Notes |
|-------|-----------|-------|--------------------|----|
| 1 | — | — | 0/5 | Initial dispatch |
| 3 | 0.35 | — | 1/5 | First finding validated |
| 5 | 0.52 | +0.17 | 3/5 | Major pivot |
| 7 | 0.61 | +0.09 | 4/5 | Diminishing returns watch |
| 8 | 0.64 | +0.03 | 4/5 | DIMINISHING_RETURNS flagged |
```

## Orchestrator Workflow

### At Workflow Start (Phase 1)

```bash
# Create the strategic context document
cat > .swarm/strategic-context.md << 'EOF'
# Strategic Context

## Original Abstract
[paste verbatim user input]

## Current Interpretation
[initial interpretation]
Last updated: Cycle 0 — [timestamp]

## Decisions and Rationale
| Cycle | Decision | Rationale | Alternatives Considered |
|-------|----------|-----------|------------------------|

## Dead Ends
| Approach | Cycle Abandoned | Why | Key Finding |
|----------|----------------|-----|-------------|

## Remaining Gaps
| Gap | Severity | Why Unresolved | Potential Path |
|-----|----------|----------------|----------------|

## Progress Velocity
| Cycle | Eval Score | Delta | Hypotheses Resolved | Notes |
|-------|-----------|-------|--------------------|----|
EOF

git add .swarm/strategic-context.md
git commit -m "chore: initialize strategic context document"
```

### At Each OODA Orient Phase

The orchestrator MUST update the strategic context document:

1. **Review current interpretation** — has anything changed?
2. **Log any decisions made this cycle** with rationale and alternatives
3. **Update dead ends** if any approach was abandoned
4. **Update remaining gaps** based on new findings
5. **Update progress velocity** with latest eval score

```bash
# Update the document in-place, then commit
git add .swarm/strategic-context.md
git commit -m "chore: update strategic context — cycle N"
```

### At Session Recovery

```bash
# Session recovery reads strategic context FIRST
cat .swarm/strategic-context.md  # Strategic reasoning and decisions
bd prime                         # Task state
bd list --json                   # All tasks
```

The strategic context document answers both "why are we doing what we're doing?" and records the decision history across cycles.

## Injecting Context into Worker Prompts

When the orchestrator dispatches a worker, it reads the strategic context and injects a relevant excerpt:

```bash
# At dispatch time, orchestrator adds to task notes:
bd update <task-id> --notes "STRATEGIC_CONTEXT: This task tests whether [X], which matters because [Y]. A strong result here would [Z]. A weak result means we need to [W]. Dead ends to avoid: [list]. Current interpretation: [summary]."
```

### What to Include

| Worker Type | Context Injection |
|-------------|-------------------|
| **Investigator** | Which hypothesis, why it was prioritized, what a strong/weak result means for the investigation, dead ends to avoid |
| **Builder** | How this component fits the overall architecture, which findings informed the design, what the component must interoperate with |
| **Replicator** | What the original finding showed, why replication was triggered, what agreement/disagreement would mean |
| **Explorer** | What criteria matter most, how this comparison fits the larger decision, what's already been ruled out |

### What NOT to Include

- Full history of all decisions (too much context, dilutes focus)
- Other agents' task details (scope violation)
- Raw data or detailed findings (workers read those directly)

## Diminishing Returns Detection

The progress velocity table in the strategic context enables diminishing returns detection:

```
IF last 2 cycles each improved eval score by < 0.05:
    DIMINISHING_RETURNS = TRUE
    → Orchestrator considers delivering current output with quality disclosure
    → Instead of spawning more investigation cycles
```

This is tracked by the orchestrator and recorded in the strategic context and in Beads:

```bash
bd update <epic-id> --notes "DIMINISHING_RETURNS:TRUE | LAST_DELTAS:[0.03, 0.02] | RECOMMENDATION:deliver-with-disclosure"
```

## Dead End Prevention

Before dispatching any new investigation, the orchestrator checks dead ends:

```bash
# Parse dead ends from strategic context
# If proposed hypothesis overlaps with a dead end:
#   SKIP unless the new approach is materially different
#   Log: "Skipping H7 — overlaps with dead end [approach] abandoned in cycle [N]"
```

This prevents re-exploration of approaches that have already been tried and failed.
