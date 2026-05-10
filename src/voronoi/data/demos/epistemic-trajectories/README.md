# Demo: Capability Thresholds in Multi-Source Reasoning

**Does knowledge compilation provide lasting value as LLM capabilities improve, or do frontier models outgrow it? At what difficulty does compilation start to matter, and which dimension of complexity does it specifically neutralize?**

A benchmark with deterministic ground truth: synthetic decision scenarios with known causal DAGs, planted cross-source constraints, and forward-simulable outcomes. Scenarios span a difficulty axis $K$ (3–15 coupled levers, 1-hop to 3-hop constraint chains) plus an **orthogonal slice at $K_4$** that separates depth, width, and source-conflict dimensions. Tested across **4–5 models** ranked by an a-priori capability proxy (GPQA / MMLU-Pro).

## What It Does

Maps the interaction surface of (model capability) × (knowledge complexity) × (encoding format) with deterministic evaluation. No LLM-as-judge variance on the primary metric.

### Core Thesis

Knowledge compilation is not a capability crutch — it is a **complexity management mechanism** with a model-dependent activation threshold $K_c(M)$. The orthogonal $K_4$ slice plus a **null-encoder control ($L_4'$)** attempts to attribute the benefit specifically to epistemic-type preservation (not mere noise removal) and specifically to constraint depth (not lever count or source count).

### Design: 3 × (6 + 3) × M Factorial

**Encoding:** L1 (raw text) vs L4 (compiled epistemic-type-preserving encoding) vs **L4′ (null-encoder control: same template, scrambled cross-references, decoy conflicts)**

**Difficulty ($K$):** 6 cumulative levels from $K_1$ (3 levers, 1-hop constraints) to $K_6$ (15 levers, 3-hop cascading constraints)

**Orthogonal slice at $K_4$:** three cells isolating depth, width, and source-conflict dimensions

**Models:** 4–5 models ranked by a-priori capability proxy (frozen before Phase 1)

Always all-sources (data + policy + expert + playbook). The question is not "does adding sources help?" but "does *compiling* sources help, and when, and which complexity dimension does it address?"

### Evaluation

Two co-primary metrics, fully deterministic:
- **Decision Regret**: forward-simulate through known causal DAG
- **Constraint Violation Rate**: recommendation vs ground-truth constraint rules

Plus **token efficiency** metrics: input/output tokens, compression ratios, **accuracy at matched input-token budget** (the honest version of Pareto).

Primary statistics use mixed-effects beta/logit regression (regret ∈ [0, 1], heteroscedastic) with pre-registered planned contrasts for the null-encoder and decomposition tests. Changepoint vs smooth-sigmoid fits are compared via AIC/BIC — sharpness is tested, not assumed.

### Key Figures

1. **Capability-threshold diagram**: Encoding benefit vs $K$, one curve per model — crossing zero at model-specific $K_c$; inset regresses $K_c$ against the capability proxy
2. **Accuracy at matched token budget**: L4 at or above L1 at any input-token count
3. **Cascade detection heatmap**: L1 vs L4 vs L4′ — the L4 vs L4′ contrast is the sharpest visual claim
4. **Decomposition**: L1/L4/L4′ at $K_4^{\text{depth}}$ vs $K_4^{\text{width}}$ vs $K_4^{\text{sources}}$
5. **Cost per correct decision** at $K_4$

## How to Run

```bash
voronoi demo run epistemic-trajectories
```

## Phases

```
Phase −1: Encoding pre-flight (9 scenarios, 0 discovery calls) — includes L4 hallucination audit + L4′ scramble check
Phase 0:  Difficulty calibration (6 scenarios × L1+L4 × 1 model, k=3) — freezes generator SHA-256 on exit
Phase 1:  Multi-model pilot on held-out seeds (6 scenarios × L1+L4 × M models, k=3)
Phase 2:  Main sweep (36 × L1+L4 + L4′ at K4–K6) · Orthogonal slice (18 × L1+L4+L4′) × M × 3
Phase 3:  Paper + webapp (gated on Phase 2 hard gates)
```

## Output

```
demos/epistemic-trajectories/
  output/
    runner/
      experiment_metrics.json # Per-scenario per-encoding per-model per-run: regret, CVR, tokens
    token_efficiency.json     # Compression ratios, cost per correct decision, matched-budget accuracy
    deterministic_metrics.json
    reliability_metrics.json
    pipeline_scores.json      # Trajectory pruning + random baseline
    cascade_detection.json
    phase_transitions.json    # Per-model K_c estimates + CIs + changepoint-vs-sigmoid AIC/BIC
    null_encoder_contrast.json # L4 vs L4′ at K >= K_4
    orthogonal_slice.json     # K_4 depth/width/sources decomposition
    generator_lock.json       # SHA-256 of generator + encoder prompts + seed ranges
    models.json               # A-priori capability proxy scores (frozen)
    failures.json             # Parse fails, refusals, timeouts
    encoding_hashes.json
    paper/
      paper.tex + paper.pdf + figures/ + appendix_encoder_prompt.md
    index.html
    data/
  src/
  run_experiments.py
```

## Success Criteria

1. Encoding × $K$ interaction on Decision Regret (mixed-effects beta/logit, $p < 0.017$)
2. L4 CVR < L1 CVR at $K \geq K_4$ ($p < 0.05$)
3. Capability threshold $K_c$ estimable, scales linearly with a-priori capability proxy (slope 95% CI excludes 0)
4. L4 ≥ L1 accuracy at matched input-token budget in ≥80% of (Model, $K$) cells
5. Pipeline compression scales with $K$ (correlation > 0.7)
6. Paper compiles with figures from actual data
7. **Null-encoder control passes:** L4 beats L4′ by ≥0.10 regret at $K \geq K_4$ ($p < 0.017$)
8. **Decomposition:** $(L_1-L_4)$ gap largest at $K_4^{\text{depth}}$ ($p < 0.017$) — or explicitly reported as null with reframed claims
9. Generator SHA-256 lock intact across all Phase 1/2 runs

## Call Budget

~5,500 LLM calls for $M=4$ models (k=3 throughout, main sweep + orthogonal slice + L4′ control).

## Prerequisites

- Python 3.11+, numpy, scipy, statsmodels, matplotlib
- `copilot` CLI in PATH
- beads, tmux, gh
