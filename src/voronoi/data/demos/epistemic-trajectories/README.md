# Demo: Phase Transitions in Multi-Source Reasoning

**Do LLMs exhibit sharp phase transitions when reasoning over heterogeneous knowledge sources as structural complexity increases? Does knowledge compilation shift the critical threshold?**

A benchmark with deterministic ground truth: synthetic decision scenarios with known causal DAGs, planted cross-source constraints, and forward-simulable outcomes. Scenarios are parameterized along a **knowledge complexity axis** $K$ (3–15 coupled levers, 1-hop to 3-hop constraint chains) and tested across **4–5 models** spanning sub-frontier to frontier capability.

## What It Does

Maps the interaction surface of (model capability) × (knowledge complexity) × (encoding format) with deterministic evaluation. No LLM-as-judge variance.

### Core Thesis

Knowledge compilation is not a capability crutch — it is a **complexity management mechanism** with a model-dependent activation threshold $K_c(M)$. Below $K_c$, compilation saves tokens (2–5× compression). Above $K_c$, it saves reasoning quality. L4 encoding is Pareto-optimal across the entire range.

### Design: 2 × 6 × M Factorial

**Encoding:** L1 (raw text) vs L4 (compiled epistemic-type-preserving encoding)

**Knowledge Complexity ($K$):** 6 levels from $K_1$ (3 levers, 1-hop constraints) to $K_6$ (15 levers, 3-hop cascading constraints with temporal coupling)

**Models:** 4–5 models spanning sub-frontier to frontier capability

Always all-sources (data + policy + expert + playbook). The question is not "does adding sources help?" but "does *compiling* sources help, and when?"

### Evaluation

Two co-primary metrics, fully deterministic:
- **Decision Regret**: forward-simulate through known causal DAG
- **Constraint Violation Rate**: recommendation vs ground-truth constraint rules

Plus **token efficiency** metrics: input/output tokens, compression ratios, cost per correct decision.

### Key Figures

1. **Phase diagram**: Encoding benefit vs $K$, one curve per model — crossing zero at model-specific $K_c$
2. **Pareto frontier**: Accuracy vs tokens — L4 always up-and-left of L1
3. **Cascade detection heatmap**: Models × constraint depth — diagonal failure boundary
4. **Cost per correct decision**: L4 cheaper everywhere

## How to Run

```bash
voronoi demo run epistemic-trajectories
```

## Phases

```
Phase −1: Encoding pre-flight (6 scenarios, 0 LLM calls)
Phase 0:  Complexity calibration (6 scenarios × 2 encodings × 1 model, k=3)
Phase 1:  Multi-model pilot (6 scenarios × 2 encodings × M models, k=3)
Phase 2:  Full (36 scenarios × 2 encodings × M models, k=3)
Phase 3:  Paper + webapp (gated on Phase 2)
```

## Output

```
demos/epistemic-trajectories/
  output/
    results.json              # Per-scenario per-encoding per-model per-run: regret, CVR, tokens
    token_efficiency.json     # Compression ratios, cost per correct decision, Pareto data
    deterministic_metrics.json
    reliability_metrics.json
    pipeline_scores.json      # Trajectory pruning + random baseline
    cascade_detection.json
    phase_transitions.json    # Per-model K_c estimates + CIs
    encoding_hashes.json
    paper/
      paper.tex + paper.pdf + figures/
    index.html
    data/
  src/
  run_experiments.py
```

## Success Criteria

1. Encoding × Complexity interaction on Decision Regret (p < 0.017)
2. L4 CVR < L1 CVR at $K \geq K_4$ (p < 0.05)
3. Per-model phase transition $K_c$ estimable via logistic breakpoint
4. L4 Pareto-dominates on cost-accuracy in ≥80% of cells
5. Pipeline compression scales with $K$ (correlation > 0.7)
6. Paper compiles with figures from actual data

## Call Budget

~3,200 LLM calls for M=4 models (k=3 throughout, includes Phase 1 multi-model pilot).

## Prerequisites

- Python 3.11+, numpy, scipy, matplotlib
- `copilot` CLI in PATH
- beads, tmux, gh
