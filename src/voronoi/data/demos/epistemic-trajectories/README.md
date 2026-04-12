# Demo: Epistemic Trajectories

**When knowledge sources have incompatible epistemic types, does preserving their native semantics during encoding enable cross-source reasoning — specifically constraint-boundary detection — that raw-text concatenation structurally cannot perform?**

A multi-agent system that compiles heterogeneous knowledge sources into epistemic-type-preserving representations, then validates whether this compilation enables cross-source constraint detection and systematically prunes the feasible trajectory space of coupled decision levers.

## What It Does

Generates synthetic RGM (Revenue Growth Management) scenarios with planted effects — including cross-source constraint boundaries that are **structurally undetectable** from any single source in isolation. A 2×2 factorial tests encoding and source diversity; a pipeline observation tests feasible trajectory pruning. A real-data validation phase confirms the invariants exist outside synthetic construction.

### Core Thesis

Knowledge compilation (not retrieval) is the bottleneck. RAG answers "which knowledge is relevant?" — this framework answers "how should knowledge be represented for joint reasoning?" The two are orthogonal and composable. The primary evidence is **constraint-boundary detection**: data alone recommends an action, policy alone states a rule, but neither source in isolation reveals the conflict. Cross-source reasoning is structurally mandatory.

### 2×2 Factorial Design

|  | **Data-only** | **All-sources** |
|--|---------------|-----------------|
| **L1 (raw text)** | L1-D | L1-A |
| **L4 (structured)** | L4-D | L4-A |

Three hypothesis tests (primary first):

| Claim | Test | Status |
|-------|------|--------|
| **Encoding enables cross-source reasoning** | **Interaction: source benefit larger at L4 than L1** | **Primary** |
| Encoding reduces Constraint Violation Rate | L4-A CVR < L1-A | Co-primary |
| Encoding reduces Decision Regret | Main effect of encoding (L4 vs L1) | Secondary/expected |

The interaction is the headline finding. The main effect (structured > raw) is expected — pre-computed statistics outperforming raw rows is not novel. The novel claim is that encoding *enables* cross-source reasoning that raw text *destroys*.

### E3: Feasible Trajectory Pruning

Full pipeline on all scenarios at L4-all. The pipeline systematically narrows the combinatorial decision space through three pruning stages:

1. **Parallel diagnostic agents** — eliminate infeasible/dominated trajectories along complementary dimensions
2. **Causal synthesis** — assemble surviving evidence into structured interventions (lever, direction, scope, mechanism)
3. **Quality gate** — filter for evidence density, constraint alignment, actionability, testability, novelty

Output: a small set of **feasible trajectories** — causally grounded paths through the coupled lever space, not point recommendations. Compression scales with dimensionality: 15–30× for 5-lever, 100–270× for 10+.

### Signal Chain

`encoding → single LLM discovery call → evaluation`. No pipeline between encoding and evaluation.

### Planted Effect Types (priority order)

| Category | Why It's Primary | What Encoding Fixes |
|----------|-----------------|---------------------|
| **Constraint boundary** | Structurally requires cross-source reasoning — no single source detects it | Typed constraint vectors with threshold + cross-reference with data |
| Interaction effect | Non-additive coupling invisible to single-lever analysis | Cross-lever interaction profiles |
| Simpson's paradox | Aggregate masks subgroup reversal | Segment-level stats pre-computed |

### Evaluation

Two co-primary metrics, both fully deterministic (no LLM judge):
- **Decision Regret**: forward-simulate through known causal DAG. Measures practical value.
- **Constraint Violation Rate**: does the recommendation violate known policy constraints? Measures safety. **Primary evidence for the thesis.**

Secondary: Variable Recall, Direction Accuracy, Causal Edge Recovery F1, cross-run reliability, failure rate.

## How to Run

```bash
voronoi demo run epistemic-trajectories
```

## Phases

```
Phase −1: Encoding pre-flight (1 scenario, 0 LLM calls)
Phase 0:  Difficulty calibration (9 scenarios, L1-D + L1-A, k=3)
Phase 0.5: Real-data validation (2-3 public datasets, qualitative)
Phase 1:  Pilot (6 scenarios, all 4 cells, k=3, 2 models)
Phase 2:  Full (36 scenarios × 4 cells × k=3 runs)
Phase 3:  Paper + webapp (gated on Phase 2)
```

## Output

```
demos/epistemic-trajectories/
  output/
    results.json             # Per-scenario per-cell per-run Decision Regret + CVR + ANOVA
    deterministic_metrics.json
    reliability_metrics.json
    pipeline_scores.json     # Feasible trajectory pruning + random baseline
    encoding_hashes.json
    real_data_validation.json  # Phase 0.5 qualitative results
    paper/
      paper.tex + paper.pdf + figures/
    index.html
    data/
  src/
  run_experiments.py
```

## Success Criteria

1. Interaction effect on Decision Regret: encoding enables cross-source reasoning (p < 0.017)
2. L4-A Constraint Violation Rate < L1-A (p < 0.05)
3. Pipeline feasible-trajectory recall > random recall (p < 0.05)
4. Dose-response: encoding effect increases with difficulty tier
5. Paper compiles with figures from actual data

## Call Budget

~1,850 LLM calls (k=3 throughout, includes second-model pilot).

## Prerequisites

- Python 3.11+, numpy, scipy, matplotlib
- `copilot` CLI in PATH
- beads, tmux, gh
