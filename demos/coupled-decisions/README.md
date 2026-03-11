# Demo: Coupled Decision Spaces

**Does structured encoding of heterogeneous knowledge beat naive RAG for coupled decision reasoning?**

A multi-agent system that encodes heterogeneous knowledge sources (quantitative data, codified policies, expert judgment, decision playbooks) into reasoning-ready representations — then validates whether structured encoding outperforms "just paste everything into the prompt" on a combinatorial decision space with planted ground truth.

## What It Does

Generates a synthetic beverage company dataset ("BevCo") with planted effects that are **genuinely misleading in raw form** but correctly interpretable with structured encoding. An agent system must discover these effects, validate them experimentally, and write an academic paper with the results.

### Encoding Ablation Ladder (the core experiment)

| Level | Data | Knowledge | Playbook | What it tests |
|-------|------|-----------|----------|--------------|
| **1. Naive RAG** | N rows as markdown table | Policies as bullets, beliefs as prose | Prose description | The "just paste it" baseline |
| **2. + Statistical pre-computation** | Statistical profiles (distributions, correlations, segments, trends) | Still unstructured text | Still prose | Value of Python-computed analytics |
| **3. + Type-aware encoding** | Statistical profiles | Tiered constraint vectors, temporal belief objects with decay | Still prose | Value of epistemic typing |
| **4. Full structured** | Statistical profiles | Typed constraints, temporal beliefs | Process graphs, typed rule catalog, technique registry | Value of playbook structuring |

All levels receive the **same data sample** (same N rows) and **all four knowledge sources** — only encoding quality varies.

### Planted Effect Categories (designed to break naive RAG)

| Category | Why Raw Rows Mislead | What Encoding Fixes It |
|----------|---------------------|----------------------|
| Simpson's paradox (≥2) | Aggregate correlation tells the wrong story | Segment-aware statistical profiles resolve it |
| Confounded coupling (≥1) | Shared temporal confound creates spurious correlation | Temporal detrending removes it |
| Constraint-boundary effect (≥2) | Data says "go" but a hard constraint says "stop" | Typed constraint vectors with scope flag it |
| Decayed belief trap (≥1) | Expert belief was true historically, data has shifted | Temporal belief metadata + trend break detection |
| Nonlinear segment interaction (≥1) | Linear correlation across all rows shows nothing | Segment-aware sub-population splits surface it |

### Playbook Complexity (30–50 queries across 6+ question types)

| Trap | What It Tests |
|------|---------------|
| Wrong-process trap | Question looks like one type but is actually another — wrong process, wrong answer |
| Missing shared-rule trap | Rule from another question type's context is required but not loaded |
| Technique-reuse trap | Shared technique needs scoping adaptation, not blind reuse |
| Cross-chain trap | Answer depends on output from a prior question of a different type |
| Context-dependent strictness trap | Same rule is hard vs. soft depending on question type |

### Knowledge Sources

- **Quantitative**: ~1M transaction rows, price elasticities, market share data
- **Policy**: 15+ codified business rules (hard/soft constraints with scope and strictness per question type)
- **Expert**: 15–20 qualitative beliefs with confidence scores, temporal validity, and decay (mix of correct, outdated, conditional)
- **Playbook**: 6+ question types with processes, 20+ overlapping rules, 10+ shared techniques, cross-question dependencies

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
Wave 1: Data generator (synthetic BevCo with encoding-sensitive planted effects)
Wave 2: Knowledge encoding + multi-agent reasoning system (parallel)
Wave 3: Experiments (encoding ablation ladder, cross-source, pipeline compression, playbook reasoning)
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
4. Process selection accuracy ≥80% on 30–50 diverse queries; flat baseline ≤60%
5. All 4 validation stages produce PASS verdicts
6. Paper compiles with figures/tables from validated data
7. Webapp opens in browser with interactive results

## Prerequisites

- Python 3.11+, numpy, scipy, matplotlib
- `copilot` CLI in PATH (falls back to heuristic reasoning if unavailable)
- beads, tmux, gh

## Why This Demo

- **Validation rigor**: 4-stage validation gate before paper can be written
- **Ground truth**: planted effects allow objective measurement of system quality
- **Cross-source reasoning**: tests whether agents can synthesize fundamentally different knowledge types
- **Real-world pattern**: coupled decision spaces appear in pricing, medicine, supply chain, and more
