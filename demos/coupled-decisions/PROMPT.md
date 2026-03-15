# Navigating Coupled Decision Spaces with Fragmented and Heterogeneous Knowledge: A System of Agents for Reasoning

Produce a complete academic paper — with synthetic experimental evidence — that introduces a multi-agent framework for reasoning over coupled decision levers under heterogeneous knowledge. The paper must be rigorous enough for a top-tier venue (AAAI, NeurIPS, ICML workshop, or Management Science).

---

## Abstract

> A broad class of applied decision problems — including revenue growth management, precision medicine, materials discovery, supply chain design, and financial risk management — share a common underlying structure. In these settings, the decision space is combinatorial over interdependent levers, the feasible region is constrained by hard operational limits, and the knowledge required to navigate the space is fragmented across sources with incompatible semantics, noise characteristics, and epistemic status. Adjusting one decision variable alters the optimal configuration of others, rendering independent optimization invalid. At the same time, the heterogeneity of available knowledge — ranging from quantitative measurements and codified rules to expert judgment — creates a representational bottleneck that prevents joint reasoning and forces reliance on ad‑hoc human cognitive synthesis.
>
> This paper makes three contributions. First, we formally characterize this problem class through three structural invariants: lever coupling, knowledge heterogeneity, and the cognitive assembly bottleneck. We show that approaches addressing any single invariant in isolation necessarily produce incomplete solutions. This characterization defines the structural conditions under which a unified framework can generalize across domains. Second, we introduce a multimodal encoding layer that transforms each knowledge type into a reasoning‑ready representation while preserving its native semantics: quantitative data are encoded as statistical profiles, policy knowledge as tiered constraint vectors, and expert judgment as temporal belief objects equipped with confidence and decay functions. By preserving epistemic differences rather than collapsing them, the framework enables agents to reason jointly across all knowledge types. Conflicts between sources — such as quantitative signals contradicting established heuristics — become diagnostic signals of potential structural change rather than unresolvable noise. Third, we present a progressive space‑reduction pipeline operating over coupled levers in three stages. Parallel diagnostic agents prune the combinatorial space along complementary analytical dimensions; a causal synthesis layer assembles the surviving evidence into structured interventions specifying lever, direction, scope, and mechanism; and a multidimensional quality gate filters candidates based on evidence density, constraint alignment, actionability, testability, and novelty.
>
> We instantiate the framework in the domain of Revenue Growth Management, where commercial levers — including pricing, promotion, assortment, distribution, and pack‑price architecture — are deeply coupled and where knowledge is distributed across numerical data, policy documents, and subject‑matter expertise. We show that the encoding layer enables cross‑type reasoning that reveals interaction effects invisible to siloed analyses, and that the progressive reduction pipeline efficiently compresses a large candidate space into a focused set of causally grounded, testable hypotheses. We conclude by identifying the structural conditions under which the framework generalizes to other domains characterized by coupled decision levers.

This abstract is the contract. Every claim made above must be substantiated in the paper.

---

## Experimental Design: 2×2 Factorial + Pipeline Observation

The abstract makes three claims. A single **2×2 within-subject factorial** tests claims 1 and 2 simultaneously, and a separate **pipeline observation** tests claim 3. The problem characterization (three structural invariants) is a logical argument in the paper — no experiment needed.

### The 2×2 Factorial

Two factors, each with two levels. Every scenario runs through all four cells.

|  | **Data-only** | **All-sources** |
|--|---------------|-----------------|
| **L1 (raw text)** | L1-data | L1-all |
| **L4 (structured)** | L4-data | L4-all |

This yields three tests from one dataset:

| Abstract claim | Statistical test | Interpretation |
|---|---|---|
| Encoding enables discovery | Main effect of encoding (L4 vs L1, pooled across sources) | Same as former E1 |
| Cross-source reasoning works | Main effect of sources at L4 (L4-all vs L4-data) | Same as former E2 |
| **Encoding enables cross-source reasoning** | **Interaction: (L4-all − L4-data) > (L1-all − L1-data)** | The headline finding — adding sources only helps when the encoding is structured |

The interaction is the paper's strongest evidence: it directly supports the thesis that structured encoding *unlocks* cross-type reasoning, not just improves single-source reasoning.

### Signal Chain

```
encoding → single LLM discovery call → evaluation
```

**No pipeline between encoding and evaluation.** The pipeline (E3) is tested separately.

---

## Core Hypothesis

**Structured encoding of heterogeneous knowledge enables an LLM to discover cross-lever effects that it misses when the same information is presented as plain text. This advantage is amplified when multiple knowledge sources are combined — i.e., encoding and source diversity interact.**

---

## Factorial Design Details

### Encoding Levels

| Level | Data | Knowledge | Playbook |
|-------|------|-----------|----------|
| **L1: Raw text** | CSV with column headers + raw rows. NO summary statistics, NO aggregations, NO correlations | Policy sentences as flat prose | Playbook as flat prose |
| **L4: Full structured** | Statistical profiles (raw rows REMOVED) | Tiered constraint vectors + temporal belief objects (prose REMOVED) | Process graph + rule catalog (prose REMOVED) |

**Key principle:** The encoding layer pre-computes statistics using deterministic code and delivers structured results to the LLM. The LLM still does all reasoning — pattern recognition, conflict detection, causal inference — but over computed summaries instead of raw numbers. This is the paper's thesis. L4 character count must be within [0.7×, 1.5×] of L1. Encoding REPLACES raw content, never appends.

### Source Conditions

| Condition | Included |
|-----------|----------|
| **Data-only** | Quantitative data only |
| **All-sources** | Data + policies + expert beliefs + playbook |

### Planted Effects

Each scenario has **3 ground-truth effects**:

- **Simpson's paradox** — Aggregate correlation reverses at segment level. Must use ≥3 overlapping subgroups where the paradox is NOT visible from scanning raw rows (groups must overlap in x-values, noise must partially mask within-group slopes). This is a data-only effect — detectable without knowledge sources.
- **Constraint-boundary** — Data recommends an action; a compound multi-condition constraint prohibits it. The constraint must require ≥2 AND-joined conditions to identify. This is a cross-source effect — undetectable without policy knowledge.
- Agents may add a third effect type if it passes a detection pilot (≥30% at L1, ≥60% at L4).

**Distractor patterns:** Each scenario must include ≥2 real-but-non-planted statistical patterns (correlations, trends, clusters) that are NOT ground-truth effects.

### Scenario Requirements

- **N ≥ 12 scenarios**, structurally varied (different column sets, subgroup counts, constraint types, lever combinations)
- **≥ 500 rows** per scenario (the floor where encoding matters — below ~150 rows, LLMs can scan raw data reliably)
- **≥ 5 lever columns** per scenario, covering ≥3 of the 5 RGM domains (pricing, promotion, assortment, distribution, pack-price architecture); at least 4 scenarios cover all 5
- **≥ 2 categorical grouping variables** per scenario (creating multiplicative segment space)

### Discovery and Evaluation

The LLM reports **3–5 findings in structured JSON** (columns, direction, magnitude, scope, mechanism, confidence). Category-blind — no effect type names in the prompt.

**Evaluation uses two-stage rubric matching:**
1. **Code pre-filter** — score Variables and Direction from structured JSON fields; eliminate obvious non-matches (both dimensions = 0) without an LLM call
2. **Batched LLM judge** — one call per discovery run scores all surviving (finding, GT) pairs on 5 dimensions (Variables, Direction, Scope, Mechanism, Quantification), each 0/1. Match threshold: ≥3/5.

**Vote calibration:** Phase 1 (pilot) runs 3 votes per batch to compute Krippendorff's α. If α ≥ 0.85, Phase 2 drops to 1 vote. If α < 0.40, revise the judge prompt.

### Metrics

- **Primary: Mean Best Rubric Score (MBRS)** — For each GT effect, take the highest rubric score from the top-3 ranked findings. Average across GT effects per scenario. Analyze via 2×2 repeated-measures ANOVA (encoding × sources), report interaction F-test + main effects + Cohen's d + 95% CI.
- **MBRS by effect type** — Separate MBRS for data-only GT effects (Simpson's) and cross-source GT effects (constraint-boundary). The interaction hypothesis predicts that cross-source MBRS shows a larger encoding × sources interaction than data-only MBRS.
- **Secondary**: F1 at ≥3/5 and ≥4/5 thresholds, effect-type coverage.

### Phases

**Phase 1 — Pilot (2 scenarios, all 4 cells, k=3 runs):**
- Validates planted effect difficulty: `MBRS_L4-all − MBRS_L1-data ≥ 0.20`
- Calibrates judge reliability (α threshold for vote count)
- Validates encoding hashes differ, L4 chars within [0.7×, 1.5×] of L1
- If any gate fails: STOP, diagnose, revise. Do NOT proceed.

**Phase 2 — Full (N ≥ 12 scenarios, k=3 runs per cell):**
- HARD GATE: Interaction effect p < 0.05 OR encoding main effect p < 0.05. At least one must hold.
- If both fail: flag `DESIGN_INVALID`, do NOT proceed to paper.

**Phase 3 — Paper + Webapp (only after Phase 2 passes)**

### Optional: Sequential Stopping

Run scenarios in batches of 4. After each batch:
- If interaction p < 0.01: stop early, sufficient evidence
- If interaction p > 0.50 with ≥ 8 scenarios: stop for futility

If used, pre-register the stopping rule and report adjusted p-values.

---

## E3: Pipeline Compresses Space

Run the **full pipeline** (diagnostic agents → causal synthesis → quality gate) on all scenarios at L4-all. This is **separate from the factorial** — the pipeline is not in the discovery evaluation path.

### Design

Each scenario at L4-all goes through 3 stages. No fixed candidate quotas — agents report all signals above a confidence threshold. The quality gate filters by score threshold only, no hard cap on output count.

### Compression Metrics

Compute naive combinatorial space per scenario:

```
naive_space = C(n_levers, 2) × n_segments × n_knowledge_sources
```

Report two ratios:
1. **Pipeline compression**: Stage 1 output → Stage 3 output
2. **Effective compression**: naive_space → Stage 3 output (this matters for the paper's claim)

**Metric**: Median effective compression ≥ 100×. Quality gate scores all 5 abstract dimensions (evidence density, constraint alignment, actionability, testability, novelty). Log to `output/pipeline_scores.json`.

---

## Hard Rules

1. **Same model for all cells.** Never switch models between conditions.
2. **Never truncate context.** Reduce scenario count instead.
3. **Never name effect categories in discovery prompts.** Category-blind only.
4. **Encoding replaces, never appends.** L4 chars within [0.7×, 1.5×] of L1.
5. **Single entry point:** `run_experiments.py`.
6. **All LLM calls via** `copilot -p "<prompt>" -s --no-color --allow-all`. Cache by prompt hash. Record model in `results.json`.
7. **Ground truth never loaded by the reasoning system.** Used only for evaluation.
8. **Minimum 500 rows per scenario.**
9. **NO SIMULATION MODE.** Do NOT substitute real LLM calls with sampling, hardcoded probabilities, or mock scripts. Do NOT create `*sim*`, `*mock*`, or `*fake*` files. The ONLY entry point is `run_experiments.py`. Reduce k or N if call budget is tight — never simulate.
10. **LLM cache validation.** `.llm_cache/` must contain ≥ `N × 4 × k` entries (scenarios × cells × runs). If nearly empty, the experiment was not run.
11. **Judge call efficiency.** Batched prompts + code pre-filtering are mandatory, not optional.

---

## What Agents Decide

Agents own ALL implementation decisions not listed in Hard Rules:

- Exact scenario count (≥12), rows per scenario, column designs
- Simpson's paradox construction parameters (group overlap, noise levels, number of subgroups) — the only constraint is that the paradox must not be trivially visible from raw CSV at 500+ rows
- Constraint-boundary construction (number of conditions, how they're buried in prose) — must be compound (≥2 AND-joined)
- Encoding representations (statistical profiles, constraint vectors, belief objects, process graphs)
- Discovery prompt wording (must be category-blind, must request structured JSON, must constrain to 3–5 findings)
- Rubric judge prompt wording (must include vocabulary normalization)
- Code pre-filter implementation (synonym maps, direction matching logic)
- Number/specialization of diagnostic agents for E3 (≥2, complementary; use confidence threshold, not fixed count)
- Causal synthesis schema (must include lever, direction, scope, mechanism)
- Quality gate weights and threshold (no hard cap on output count)
- Whether to include L2/L3 for a gradient plot (optional)
- Whether to add effect types (must pass detection pilot first)
- Paper structure, related work, figure design, webapp layout

---

## Success Criteria

| ID | Criterion | How measured |
|----|-----------|-------------|
| **SC1** | Encoding improves discovery | Main effect of encoding, p < 0.05, or interaction p < 0.05 |
| **SC2** | Cross-source reasoning benefits from encoding | Interaction (encoding × sources) on cross-source MBRS |
| **SC3** | Pipeline compression ≥ 100× effective | Median naive_space / Stage 3 output |
| **SC4** | Three invariants formally defined + single-invariant insufficiency | Logical argument in paper |
| **SC5** | Paper compiles, figures from actual data | Compilation + review |
| **SC6** | All claims backed by effect sizes and CIs | Statistical reporting |
| **SC7** | Pipeline architecture matches abstract | `pipeline_scores.json` with 5-dim gate |

---

## Deliverables

```
demos/coupled-decisions/
  output/
    results.json            # Per-scenario per-cell per-run metrics + ANOVA results + model key
    pipeline_scores.json    # Quality gate 5-dimension scores per candidate
    encoding_hashes.json    # SHA-256 + char counts per level
    index.html              # Interactive webapp
    data/                   # Synthetic data + ground_truth.json
    paper/
      paper.tex + paper.pdf + figures/ + references.bib
  src/                      # All source code
  run_experiments.py        # Single entry point
  .llm_cache/               # Prompt-hash cache
```

---

## Technical Stack

- Python 3.11+, numpy, scipy, matplotlib
- Copilot CLI for all LLM calls
- Target: <60 min first run, <5 min from cache

### Expected LLM Call Budget

With N=12 scenarios, 4 cells, k=3 runs, batched judging, code pre-filtering, and pilot-validated single vote:

| Component | Formula | Calls |
|-----------|---------|-------|
| Factorial discovery | 12 × 4 cells × 3 runs | 144 |
| Factorial judging (batched, 1 vote) | 144 batched calls | 144 |
| E3 pipeline | 12 × ~4 agents | ~48 |
| **Total** | | **~336** |

If pilot α < 0.85 (3-vote mode): judging × 3 → ~528 total.

With optional sequential stopping (pre-registered): expected ~200 calls.

---

## Cleanup

When complete: delete all agent branches (local + remote), remove worktrees, prune, kill tmux sessions. `.llm_cache/` may be preserved.
