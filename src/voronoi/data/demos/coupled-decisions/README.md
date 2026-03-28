# Demo: Coupled Decision Spaces

**Does structured encoding of heterogeneous knowledge make LLM reasoning more reliable — and does encoding unlock cross-source reasoning?**

A multi-agent system that encodes heterogeneous knowledge sources (quantitative data, codified policies, expert judgment, decision playbooks) into reasoning-ready representations — then validates whether structured encoding outperforms "just paste everything into the prompt" on a coupled decision space with planted ground truth.

## What It Does

Generates synthetic RGM (Revenue Growth Management) scenarios with planted effects that are **genuinely misleading in raw form** but correctly interpretable with structured encoding. A 2×2 factorial tests encoding and source diversity jointly; a separate pipeline observation tests compression.

### 2×2 Factorial Design

|  | **Data-only** | **All-sources** |
|--|---------------|-----------------|
| **L1 (raw text)** | L1-D | L1-A |
| **L4 (structured)** | L4-D | L4-A |

Three hypothesis tests from one dataset:

| Claim | Test |
|-------|------|
| Encoding reduces Decision Regret | Main effect of encoding (L4 vs L1) |
| Cross-source reasoning works at L4 | L4-A vs L4-D |
| **Encoding enables cross-source reasoning** | **Interaction: source benefit is larger at L4 than L1** |

The interaction is the headline finding. No partial-source conditions (DP, DE) — in production you always have all sources. Source ablations are engineering diagnostics done in Phase −1, not experimental conditions.

### E3: Pipeline Compression (Observational)

Full pipeline (diagnostic agents → causal synthesis → quality gate) on all scenarios at L4-all. Measures effective compression from naive combinatorial space. Compression scales with scenario dimensionality: 15–30× for 5-lever scenarios, 100–270× for 10+ lever scenarios.

### Signal Chain

`encoding → single LLM discovery call → evaluation`. No pipeline between encoding and evaluation.

### Planted Effect Types

| Category | Why Raw Rows Mislead | What Encoding Fixes |
|----------|---------------------|---------------------|
| Simpson's paradox | Aggregate masks subgroup reversal | Segment-level stats pre-computed |
| Constraint boundary | Constraint buried in prose | Typed vector with threshold |

### Evaluation

Two co-primary metrics, both fully deterministic (no LLM judge):
- **Decision Regret**: forward-simulate the model's recommendation through the known causal DAG. Measures practical value.
- **Constraint Violation Rate**: does the recommendation violate known policy constraints? Measures safety.

Secondary: Variable Recall, Direction Accuracy, Causal Edge Recovery F1, cross-run reliability (σ), failure rate. MBRS retained as descriptive metric for comparability.

## How to Run

```bash
voronoi demo run coupled-decisions
```

## Phases

```
Phase 1: Pilot — 6 scenarios (2 per difficulty tier), all 4 cells, k=3, calibration gates
Phase 2: Full — 36 scenarios × 4 cells × k=3 runs, ANOVA on Decision Regret
Phase 3: Paper + webapp (gated on Phase 2)
```

## Output

```
demos/coupled-decisions/
  output/
    results.json            # Per-scenario per-cell per-run Decision Regret + Constraint Violation Rate + ANOVA
    deterministic_metrics.json  # Variable Recall, Direction Accuracy, Rule Match, Scope Precision, Edge Recovery F1
    reliability_metrics.json    # Cross-run σ, failure rate per cell
    pipeline_scores.json    # Quality gate 5-dimension scores + random baseline
    encoding_hashes.json    # SHA-256 + char counts
    paper/
      paper.tex + paper.pdf + figures/
    index.html              # Interactive webapp
    data/                   # Synthetic data + ground_truth.json (includes DAG + SEM coefficients)
  src/                      # All source code
  run_experiments.py        # Single entry point
```

## Success Criteria

1. At least one of: encoding main effect or interaction on Decision Regret, p < 0.017
2. L4-A Constraint Violation Rate < L1-A (p < 0.05)
3. Interaction on Decision Regret: source benefit larger at L4 than at L1
4. L4 cross-run σ < L1 cross-run σ (encoding improves reliability)
5. Pipeline effective compression ≥ 100× on high-dimensional scenarios (10+ levers)
6. Three invariants formally defined in paper
7. Paper compiles with figures from actual data
8. All claims backed by effect sizes and CIs
9. Pipeline architecture matches abstract (≥2 agents, synthesis tuples, 5-dim gate)

## Call Budget

~765 LLM calls (best case) to ~1,629 (k=3 throughout). See PROMPT.md for breakdown.

## Prerequisites

- Python 3.11+, numpy, scipy, matplotlib
- `copilot` CLI in PATH
- beads, tmux, gh
