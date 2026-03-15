# Demo: Coupled Decision Spaces

**Does structured encoding of heterogeneous knowledge beat raw text for cross-lever effect discovery — and does encoding unlock cross-source reasoning?**

A multi-agent system that encodes heterogeneous knowledge sources (quantitative data, codified policies, expert judgment, decision playbooks) into reasoning-ready representations — then validates whether structured encoding outperforms "just paste everything into the prompt" on a coupled decision space with planted ground truth.

## What It Does

Generates synthetic RGM (Revenue Growth Management) scenarios with planted effects that are **genuinely misleading in raw form** but correctly interpretable with structured encoding. A single 2×2 factorial tests encoding and source diversity jointly; a separate pipeline observation tests compression.

### 2×2 Factorial Design

|  | **Data-only** | **All-sources** |
|--|---------------|-----------------|
| **L1 (raw text)** | L1-data | L1-all |
| **L4 (structured)** | L4-data | L4-all |

Three hypothesis tests from one dataset:

| Claim | Test |
|-------|------|
| Encoding enables discovery | Main effect of encoding (L4 vs L1) |
| Cross-source reasoning works | Main effect of sources at L4 |
| **Encoding enables cross-source reasoning** | **Interaction: source benefit is larger at L4 than L1** |

The interaction is the headline finding.

### E3: Pipeline Compression (Observational)

Full pipeline (diagnostic agents → causal synthesis → quality gate) on all scenarios at L4-all. Measures effective compression from naive combinatorial space.

### Signal Chain

`encoding → single LLM discovery call → evaluation`. No pipeline between encoding and evaluation.

### Planted Effect Types

| Category | Why Raw Rows Mislead | What Encoding Fixes |
|----------|---------------------|---------------------|
| Simpson's paradox | Aggregate masks subgroup reversal | Segment-level stats pre-computed |
| Constraint boundary | Constraint buried in prose | Typed vector with threshold |

### Evaluation

Two-stage rubric matching: code-based pre-filter (Variables + Direction from structured JSON), then batched LLM judge for all 5 dimensions. Pilot validates whether 1 vote suffices (α ≥ 0.85) or 3-vote majority needed.

## How to Run

```bash
voronoi demo run coupled-decisions
```

## Phases

```
Phase 1: Pilot — 2 scenarios, all 4 cells, k=3 runs, calibration gates
Phase 2: Full — ≥12 scenarios × 4 cells × k=3 runs, ANOVA
Phase 3: Paper + webapp (gated on Phase 2)
```

## Output

```
demos/coupled-decisions/
  output/
    results.json            # Per-scenario per-cell per-run metrics + ANOVA
    pipeline_scores.json    # Quality gate 5-dimension scores
    encoding_hashes.json    # SHA-256 + char counts
    paper/
      paper.tex + paper.pdf + figures/
    index.html              # Interactive webapp
    data/                   # Synthetic data + ground_truth.json
  src/                      # All source code
  run_experiments.py        # Single entry point
```

## Success Criteria

1. Encoding main effect OR interaction p < 0.05
2. Interaction on cross-source MBRS (encoding × sources)
3. Pipeline effective compression ≥ 100×
4. Three invariants formally defined in paper
5. Paper compiles with figures from actual data
6. All claims backed by effect sizes and CIs
7. Pipeline architecture matches abstract (≥2 agents, synthesis tuples, 5-dim gate)

## Call Budget

~336 LLM calls (best case) to ~528 (3-vote fallback). See PROMPT.md for breakdown.

## Prerequisites

- Python 3.11+, numpy, scipy, matplotlib
- `copilot` CLI in PATH
- beads, tmux, gh
