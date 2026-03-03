# Demo: Coupled Decision Spaces

**Can LLM-powered agents reason over coupled commercial levers better than siloed analysis?**

A multi-agent system that synthesizes heterogeneous knowledge sources (quantitative data, codified policies, expert judgment) to navigate a combinatorial decision space with ~10^18 combinations — validated against planted ground truth.

## What It Does

Generates a synthetic beverage company dataset ("BevCo") with 5 planted cross-lever effects that **only** appear when analyzing multiple decision levers jointly. An agent system must discover these effects, validate them experimentally, and write an academic paper with the results.

### The 5 Planted Effects

| # | Effect | Why Siloed Analysis Misses It |
|---|--------|------|
| 1 | Price-Promotion Trap | Promo ROI looks positive independently; joint analysis reveals base-price cut is better |
| 2 | Assortment-Distribution Synergy | Neither lever alone works; combined they yield +9% revenue |
| 3 | Pack-Price Cannibalization Mask | 12-pack appears to grow volume but cannibalizes 6-pack margin |
| 4 | Cross-Source Signal | Quant + policy + expert must all be synthesized for correct answer |
| 5 | Constraint-Coupling Conflict | Expert is directionally right but scoped wrong without policy constraints |

### Knowledge Sources

- **Quantitative**: ~1M transaction rows, price elasticities, market share data
- **Policy**: 15 codified business rules (hard/soft constraints)
- **Expert**: 15-20 qualitative beliefs with confidence scores (mix of correct, outdated, conditional)

## How to Run

### Option A: CLI (recommended)

```bash
voronoi demo run coupled-decisions
```

Watch agents:
```bash
tmux attach -t $(basename $(pwd))-swarm
```

### Option B: Interactive

```bash
voronoi init
copilot
> /swarm Build from demos/coupled-decisions/PROMPT.md
```

## Wave Structure

```
Wave 1: Data generator (synthetic BevCo scenario with planted effects)
Wave 2: Knowledge encoding + multi-agent reasoning system (parallel)
Wave 3: Experiments (encoding validation, ablation, progressive reduction, cross-domain)
Wave 4: Validation gate (statistical audit, methodology critique, reproducibility, adversarial)
Wave 5: Paper + webapp (parallel — gated on validation passing)
```

## Output

```
demos/coupled-decisions/
  output/
    results.json            # All experiment results
    validation_report.json  # Validation gate verdicts (must all PASS)
    paper/
      paper.tex             # LaTeX source
      paper.pdf             # Compiled PDF
      figures/              # Generated figures
    index.html              # Interactive webapp
    data/                   # Generated synthetic data files
  src/                      # All source code
```

## Success Criteria

1. Full system discovers ≥4/5 planted effects; best ablation discovers ≤3/5
2. Knowledge encoding yields ≥80% cross-type query accuracy (vs ≤50% without)
3. Decision space reduced from 10^18 → ≤15 recommendations with zero hard-constraint violations
4. All 4 validation stages produce PASS verdicts
5. Paper compiles with figures/tables from validated data
6. Webapp opens in browser with interactive results

## Prerequisites

- Python 3.11+, numpy, scipy, matplotlib
- `copilot` CLI in PATH (falls back to heuristic reasoning if unavailable)
- beads, tmux, gh

## Why This Demo

- **Validation rigor**: 4-stage validation gate before paper can be written
- **Ground truth**: planted effects allow objective measurement of system quality
- **Cross-source reasoning**: tests whether agents can synthesize fundamentally different knowledge types
- **Real-world pattern**: coupled decision spaces appear in pricing, medicine, supply chain, and more
