# Demo: Coupled Decision Spaces

**Does structured encoding of heterogeneous knowledge beat raw text for cross-lever effect discovery?**

A multi-agent system that encodes heterogeneous knowledge sources (quantitative data, codified policies, expert judgment, decision playbooks) into reasoning-ready representations — then validates whether structured encoding outperforms "just paste everything into the prompt" on a coupled decision space with planted ground truth.

## What It Does

Generates synthetic RGM (Revenue Growth Management) scenarios with planted effects that are **genuinely misleading in raw form** but correctly interpretable with structured encoding. Three clean experiments — one per abstract claim.

### Three Experiments

| # | Abstract claim | What varies | What's measured |
|---|---------------|-------------|-----------------|
| **E1** | Encoding enables effect discovery | L1 (raw text) vs L4 (structured) | Mean Best Rubric Score (MBRS) |
| **E2** | Cross-source reasoning works | All-sources vs data-only at L4 | Cross-source MBRS difference |
| **E3** | Pipeline compresses space | — (observational) | Compression ratio |

### E1: Direct Discovery (Core Experiment)

Signal chain: `encoding → single LLM discovery call → rubric matching`. No pipeline between encoding and evaluation.

| Level | Data | Knowledge | Playbook |
|-------|------|-----------|----------|
| **L1: Raw text** | CSV with headers + raw rows, no stats | Flat prose | Flat prose |
| **L4: Full structured** | Statistical profiles (rows removed) | Typed constraints + belief objects (prose removed) | Process graph + rule catalog (prose removed) |

L4 replaces raw content — never appends. Character count within [0.7×, 1.5×] of L1. Same model for both levels.

### Planted Effect Types

| Category | Why Raw Rows Mislead | What Encoding Fixes |
|----------|---------------------|---------------------|
| Simpson's paradox | Aggregate masks subgroup reversal | Segment-level stats pre-computed |
| Constraint boundary | Constraint buried in prose | Typed vector with threshold |

Agents may add more effect types if they pass a detection pilot (≥30% at L1, ≥60% at L4).

### Rubric Matching

5-dimension scoring (variables, direction, scope, mechanism, quantification), 0/1 each. Match if ≥3/5. Three-vote majority per judgment. Krippendorff's alpha for reliability.

## How to Run

### Option A: CLI (recommended)

```bash
voronoi demo run coupled-decisions
```

### Option B: Interactive

```bash
voronoi init
copilot
> /swarm Build from demos/coupled-decisions/PROMPT.md
```

## Phases

```
Phase 1: Pilot — 2 scenarios, L1 vs L4, calibration gates
Phase 2: Full experiment — ≥12 scenarios × k=5 runs, hypothesis test
Phase 3: Paper + webapp (gated on Phase 2 passing)
```

## Output

```
demos/coupled-decisions/
  output/
    results.json            # Per-scenario per-level per-run metrics
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

1. L4 > L1 on MBRS, p < 0.05 (k=5 runs × ≥12 scenarios, same model)
2. All-sources > data-only on cross-source MBRS at L4
3. Pipeline compression ≥ 10×
4. Three invariants formally defined in paper
5. Paper compiles with figures from actual data
6. All claims backed by effect sizes and CIs
7. Pipeline architecture matches abstract (≥2 agents, synthesis tuples, 5-dim gate)

## Prerequisites

- Python 3.11+, numpy, scipy, matplotlib
- `copilot` CLI in PATH
- beads, tmux, gh
