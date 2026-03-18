# Navigating Coupled Decision Spaces with Fragmented and Heterogeneous Knowledge: A System of Agents for Reasoning

Produce a complete academic paper — with synthetic experimental evidence — that introduces a multi-agent framework for reasoning over coupled decision levers under heterogeneous knowledge. The paper must be rigorous enough for a top-tier venue (AAAI, NeurIPS, ICML workshop, or Management Science).

---

## Abstract

> A broad class of applied decision problems — including revenue growth management, precision medicine, materials discovery, supply chain design, and financial risk management — share a common underlying structure. In these settings, the decision space is combinatorial over interdependent levers, the feasible region is constrained by hard operational limits, and the knowledge required to navigate the space is fragmented across sources with incompatible semantics, noise characteristics, and epistemic status. Adjusting one decision variable alters the optimal configuration of others, rendering independent optimization invalid. At the same time, the heterogeneity of available knowledge — ranging from quantitative measurements and codified rules to expert judgment — creates a representational bottleneck that prevents joint reasoning and forces reliance on ad‑hoc human cognitive synthesis.
>
> This paper makes three contributions. First, we formally characterize this problem class through three structural invariants: lever coupling, knowledge heterogeneity, and the cognitive assembly bottleneck. We show that approaches addressing any single invariant in isolation necessarily produce incomplete solutions. This characterization defines the structural conditions under which a unified framework can generalize across domains. Second, we introduce a multimodal encoding layer that transforms each knowledge type into a reasoning‑ready representation while preserving its native semantics: quantitative data are encoded as statistical profiles, policy knowledge as tiered constraint vectors, and expert judgment as temporal belief objects equipped with confidence and decay functions. By preserving epistemic differences rather than collapsing them, the framework enables agents to reason jointly across all knowledge types. Conflicts between sources — such as quantitative signals contradicting established heuristics — become diagnostic signals of potential structural change rather than unresolvable noise. Third, we present a progressive space‑reduction pipeline operating over coupled levers in three stages. Parallel diagnostic agents prune the combinatorial space along complementary analytical dimensions; a causal synthesis layer assembles the surviving evidence into structured interventions specifying lever, direction, scope, and mechanism; and a multidimensional quality gate filters candidates based on evidence density, constraint alignment, actionability, testability, and novelty.
>
> We instantiate the framework in the domain of Revenue Growth Management, where commercial levers — including pricing, promotion, assortment, distribution, and pack‑price architecture — are deeply coupled and where knowledge is distributed across numerical data, policy documents, and subject‑matter expertise. We show that the encoding layer improves the reliability of cross‑lever effect detection — reducing variance and eliminating failure modes in complex scenarios where raw‑text reasoning is inconsistent — and that combining structured encoding with multiple knowledge sources yields an interaction effect: the benefit of source diversity is realized only when the encoding preserves epistemic distinctions. The progressive reduction pipeline compresses the combinatorial lever‑pair space by 15–270× depending on scenario dimensionality, producing a focused set of causally grounded, testable hypotheses. We conclude by identifying the structural conditions under which the framework generalizes to other domains characterized by coupled decision levers.

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

**Structured encoding of heterogeneous knowledge makes LLM-based cross-lever effect discovery consistently reliable — reducing variance and eliminating failure modes present in raw-text reasoning. This reliability advantage is amplified when multiple knowledge sources are combined: encoding and source diversity interact, because source diversity only helps when the encoding preserves epistemic distinctions.**

### Why E2 (Cross-Source) Is the Flagship

The interaction test (encoding × sources) is the paper's headline finding, but the **cross-source main effect at L4** is the most defensible individual claim. Constraint-boundary effects structurally require policy documents — no amount of data scanning discovers "promos > 40% prohibited when margin < 15%" from CSV alone. Unlike the encoding main effect (which is vulnerable to ceiling effects at moderate row counts), the all-sources vs data-only comparison genuinely removes information, making it robust to LLM capability improvements.

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

Each scenario has **3 ground-truth effects** (all three are mandatory):

- **Simpson's paradox** — Aggregate correlation reverses at segment level. Must use ≥4 overlapping subgroups where the paradox is NOT visible from scanning raw rows (groups must overlap in x-values with `x_spread ≤ x_std`, noise must partially mask within-group slopes with `noise_std ≥ 0.8 × |within_slope × x_std|`). Construction must be verified: after generation, run a validation check confirming that (a) the aggregate slope has opposite sign to the majority of within-group slopes, (b) a naive correlation on sampled rows (N=100) does NOT detect the reversal, and (c) the subgroup labels are NOT column headers but must be derived from binning or clustering (to prevent trivial group-by detection). This is a data-only effect — detectable without knowledge sources.
- **Constraint-boundary** — Data recommends an action; a compound multi-condition constraint prohibits it. The constraint must require **≥3 conditions with at least one nested disjunction** (e.g., `(margin < 15% AND region ∈ {North, West}) OR (promo_depth > 40% AND pack_size < 500ml AND channel = convenience)`). Conditions must be distributed across ≥2 non-adjacent paragraphs in the policy document — never stated as a single rule block. This is a cross-source effect — undetectable without policy knowledge. **This effect type is the strongest test of the paper's thesis** — it structurally requires cross-source information.
- **Interaction effect (mandatory)** — Two or more levers jointly produce a non-additive outcome that is invisible when levers are analyzed independently. For example: promotion depth has no main effect on margin, but promotion × pack-size interaction drives a significant margin shift in a specific segment. The interaction must involve ≥2 levers and ≥1 moderating variable, and must NOT be a textbook-standard pattern (e.g., avoid simple two-way interactions that are common in statistics curricula). Must pass L1-data detection check: if ≥80% of L1-data pilot runs detect it, the interaction is too easy — redesign with more confounders or weaker signal. **Run 2 upgrade:** at least half of scenarios must include a **3-way or 4-way interaction** (e.g., price × promotion × channel) where pairwise analysis shows nothing — only the full joint term is significant.

**Distractor patterns:** Each scenario must include ≥2 real-but-non-planted statistical patterns (correlations, trends, clusters) that are NOT ground-truth effects.

### Scenario Requirements

- **N ≥ 24 scenarios**, structurally varied (different column sets, subgroup counts, constraint types, lever combinations). This floor is derived from a power analysis (see below): at the observed d ≈ 0.48 for the encoding main effect, N ≥ 28 is needed for 80% power at α = 0.05; with mixed-effects modeling (k runs per scenario), N ≥ 24 suffices.
- **≥ 1500 rows** per scenario (the floor where raw-data scanning starts to degrade for frontier LLMs — below ~500 rows, LLMs scan raw data reliably and ceiling effects kill the encoding advantage). **At least 8 scenarios must have ≥ 3000 rows** to stress-test attention degradation at scale.
- **All rows must be delivered to the LLM.** The `--max-rows` flag (or any row truncation) is **prohibited**. If context length is a concern, reduce column count — never truncate rows. At 1500 rows × 15 columns, L1 is ~240K characters (~75K tokens). For 3000-row scenarios, verify the model's context window accommodates the full payload; if not, reduce columns to stay within limits.
- **Use realistic RGM column names** (e.g., `discount_pct`, `promo_depth`, `shelf_space_share`, `pack_size_ml`, `distribution_coverage`) — not generic `col_1`, `col_2` names. Realistic names increase ecological validity and make the task harder for raw-text scanning.
- **≥ 5 lever columns** per scenario, covering ≥3 of the 5 RGM domains (pricing, promotion, assortment, distribution, pack-price architecture); at least 8 scenarios cover all 5.
- **≥ 10 lever columns** in at least 6 scenarios (high-dimensional scenarios are critical for E3 compression claims).
- **≥ 2 categorical grouping variables** per scenario (creating multiplicative segment space).

### Power Analysis

Prior experiments measured d ≈ 0.48 for the encoding main effect with N = 12 (underpowered — observed p > 0.05). Required sample sizes at 80% power, α = 0.05:

| Effect | Observed d | Required N (paired t) | With mixed-effects (k=3) | Notes |
|--------|-----------|----------------------|--------------------------|-------|
| Encoding main | 0.48 | 28 | 24 | Prior run got d=0.00 at 500 rows; harder scenarios at 1500+ rows needed |
| Interaction | ~0.35 (est.) | 52 | 40 | Prior run got d=0.00; mandatory interaction effect + finer rubric should surface signal |
| Cross-source at L4 | ~1.0 (est. from E2 design) | 10 | 8 | Most robust — removing sources genuinely removes information |

The cross-source comparison (E2) is expected to have a large effect because removing entire knowledge sources genuinely removes information — unlike encoding level, where L1 still contains all the data. This is why E2 is the flagship experiment.

If the interaction remains underpowered at N = 24, the paper reports the encoding main effect and cross-source main effect as separate findings, with the interaction as exploratory. Pre-register this fallback.

### Discovery and Evaluation

The LLM reports **3–5 findings in structured JSON** (columns, direction, magnitude, scope, mechanism, confidence). Category-blind — no effect type names in the prompt.

**Evaluation uses two-stage rubric matching:**
1. **Code pre-filter** — score Variables and Direction from structured JSON fields; eliminate obvious non-matches (both dimensions = 0) without an LLM call
2. **Batched LLM judge** — one call per discovery run scores all surviving (finding, GT) pairs on **8 dimensions**:
   - **Binary (0/1):** Variables, Direction, Scope, Mechanism, Quantification (same as before)
   - **Continuous (0–2):** Precision (how precisely the effect is characterized — 0 = vague, 1 = approximate, 2 = exact), Completeness (how much of the GT effect is captured — 0 = fragment, 1 = partial, 2 = full), Specificity (how narrowly scoped vs. generic — 0 = generic, 1 = partially scoped, 2 = fully conditioned on correct subpopulation)
   - **Match score** = (sum of binary dims) + (sum of continuous dims / 6). Range: 0.0–6.0. Match threshold: ≥ 3.5.
   - The continuous dimensions break ceiling effects: two findings that both pass 5/5 binary dims can still differ on precision and specificity.

**Vote calibration:** Phase 1 (pilot) runs 3 votes per batch to compute Krippendorff's α. If α ≥ 0.85, Phase 2 drops to 1 vote. If α < 0.40, revise the judge prompt.

### Metrics

- **Primary: Mean Best Rubric Score (MBRS)** — For each GT effect, take the highest rubric score from the top-3 ranked findings. Average across GT effects per scenario. MBRS now ranges 0.0–6.0 (not 0–1) due to the continuous dimensions. Normalize to [0, 1] for reporting: `MBRS_norm = MBRS / 6.0`. Analyze via 2×2 repeated-measures ANOVA (encoding × sources), report interaction F-test + main effects + Cohen's d + 95% CI.
- **MBRS by effect type** — Separate MBRS for data-only GT effects (Simpson's), cross-source GT effects (constraint-boundary), and interaction effects. The interaction hypothesis predicts that cross-source MBRS shows a larger encoding × sources interaction than data-only MBRS. The interaction-effect MBRS tests whether structured encoding helps detect non-additive patterns that require multi-lever reasoning.
- **Secondary**: F1 at ≥3.5/6.0 and ≥4.5/6.0 thresholds, effect-type coverage.

### Phases

**Phase 0 — Difficulty Calibration (3 scenarios, L1-data only, k=3 runs):**

Before investing in the full factorial, verify that the task is actually hard enough for raw-text reasoning to struggle. Run 3 structurally varied scenarios through L1-data only.
- **Anti-ceiling gate:** `mean MBRS_L1-data < 0.80` (normalized). If L1-data already scores ≥ 0.80, the scenarios are too easy — the encoding condition has no room to improve. Remediation options (agent decides which): increase row count, add more confounders/distractor patterns, increase noise in Simpson's construction, add more constraint conditions, make interaction effects weaker-signal.
- **Variance gate:** `SD(MBRS) across 3 scenarios > 0.05`. If SD ≈ 0, all scenarios are at the same difficulty — add structural variation.
- **Per-effect check:** For each planted effect type, at least 1 of 3 scenarios must have MBRS < 0.67 at L1-data. If every effect type is at ceiling, the effects are too prototypical.
- Phase 0 scenarios can be reused in Phase 2 if they pass all gates.

**Phase 1 — Pilot (3 scenarios, all 4 cells, k=3 runs):**
- Validates planted effect difficulty: `MBRS_L4-all − MBRS_L1-data ≥ 0.15` (relaxed from 0.20 given harder scenarios)
- **Anti-ceiling gate:** No cell may have `SD(MBRS) = 0.00` across all scenarios. If any cell has zero variance, the rubric cannot discriminate — harden scenarios or refine rubric continuous dimensions before proceeding.
- Calibrates judge reliability (α threshold for vote count)
- Validates encoding hashes differ, L4 chars within [0.7×, 1.5×] of L1
- If any gate fails: STOP, diagnose, revise. Do NOT proceed.

**Phase 2 — Full (N ≥ 24 scenarios, k=3 runs per cell):**
- HARD GATE: At least one of the following must hold at p < 0.05: (a) interaction effect, (b) encoding main effect, (c) cross-source main effect at L4.
- If all three fail: flag `DESIGN_INVALID`, do NOT proceed to paper.
- Report all three tests regardless of significance. The cross-source main effect is expected to be the largest and most robust.

**Phase 3 — Paper + Webapp (only after Phase 2 passes)**

### Optional: Sequential Stopping

Run scenarios in batches of 6. After each batch:
- If interaction p < 0.01 AND cross-source main effect p < 0.01: stop early, sufficient evidence
- If all three tests p > 0.50 with ≥ 18 scenarios: stop for futility

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

**Metric**: Effective compression varies by scenario dimensionality. Report the full distribution:
- **Low-dimensional scenarios** (5 levers, 2–3 segments): expect 15–30× effective compression
- **High-dimensional scenarios** (10+ levers, 4+ segments): expect 100–270× effective compression
- Report median, IQR, and per-scenario values. The paper's claim is that compression scales with scenario complexity — NOT a fixed 100× floor.

Example: With 10 levers, 12 segments, 3 sources: naive_space = C(10,2) × 12 × 3 = 1620. Pipeline output of 6 candidates → 270× compression.

Quality gate scores all 5 abstract dimensions (evidence density, constraint alignment, actionability, testability, novelty). Log to `output/pipeline_scores.json`.

---

## Hard Rules

1. **Same model for all cells.** Never switch models between conditions.
2. **Never truncate rows.** All rows must be delivered to the LLM. No `--max-rows` flag, no sampling, no row limits. If context is tight, reduce column count or scenario count — never truncate rows. This is the most critical rule: row truncation below 500 caused ceiling effects in prior experiments (L1 MBRS 0.954 at 150 rows, killing the encoding advantage).
3. **Never name effect categories in discovery prompts.** Category-blind only.
4. **Encoding replaces, never appends.** L4 chars within [0.7×, 1.5×] of L1.
5. **Single entry point:** `run_experiments.py`.
6. **All LLM calls via** `copilot -p "<prompt>" -s --no-color --allow-all`. Cache by prompt hash. Record model in `results.json`.
7. **Ground truth never loaded by the reasoning system.** Used only for evaluation.
8. **Minimum 1500 rows per scenario.** At least 8 scenarios must have ≥ 3000 rows.
9. **k ≥ 3 runs per cell.** Never reduce to k = 1. Within-cell variance is essential for detecting effects; k = 1 produces degenerate zero-variance cells that make ANOVA meaningless.
10. **NO SIMULATION MODE.** Do NOT substitute real LLM calls with sampling, hardcoded probabilities, or mock scripts. Do NOT create `*sim*`, `*mock*`, or `*fake*` files. The ONLY entry point is `run_experiments.py`. Reduce N if call budget is tight — never simulate, never reduce k below 3.
11. **LLM cache validation.** `.llm_cache/` must contain ≥ `N × 4 × k` entries (scenarios × cells × runs). If nearly empty, the experiment was not run.
12. **Judge call efficiency.** Batched prompts + code pre-filtering are mandatory, not optional.
13. **Validate Simpson's paradox construction.** After generating each scenario, run automated checks: (a) aggregate slope sign ≠ majority within-group slope sign, (b) naive 100-row sample correlation does NOT detect the reversal, (c) subgroup x-ranges overlap with `x_spread ≤ x_std`, (d) noise satisfies `noise_std ≥ 0.8 × |within_slope × x_std|`, (e) subgroup labels are derived from binning/clustering, not raw column values. If validation fails, regenerate the scenario.
14. **Use realistic RGM column names.** No generic `col_1`/`scenario_*` naming. Columns must reflect actual RGM lever names (e.g., `discount_pct`, `promo_depth`, `shelf_space_share`).
15. **Validate interaction effect construction.** After generating each scenario, verify: (a) main effects of the interacting levers are non-significant (p > 0.10) when tested independently, (b) the interaction term is significant (p < 0.05) in a two-way ANOVA, (c) the effect is not a standard textbook pattern (agent must document why).

---

## Known Failure Modes — Read Before Building

Prior runs produced a decisive null result (encoding F = 0.000, d = 0.000). Root-cause analysis identified the following design traps. These are NOT hard rules — they are documented anti-patterns to help agents avoid repeating the same failures.

1. **Ceiling from easy patterns.** Simpson's paradox is extensively represented in LLM training data. If you plant only textbook-standard patterns, the LLM recognizes them from raw numbers regardless of encoding. Mitigation: use the mandatory interaction effect (which is domain-specific and not textbook), increase noise, require subgroup derivation rather than column lookup. **Run 1 confirmed this:** Simpson's MBRS was 0.85–0.98 across all cells. Run 2 must use multi-mediator Simpson's variants (see Run 2 Directions).
2. **Ceiling from coarse rubric.** A 5-binary-dimension rubric (max score 5) clusters scores at the top when the model is competent. Two findings that differ meaningfully in precision/specificity both score 5/5. The continuous rubric dimensions (Precision, Completeness, Specificity) exist specifically to break this ceiling.
3. **k = 1 collapses variance.** With one run per cell, ANOVA gets N observations with zero within-cell variance. The "exact null" (F = 0.000) likely reflects a single cached reasoning path, not genuine equivalence.
4. **500 rows is within easy-scan range.** Frontier LLMs with 128K+ context process 500 × 15 tabular data in a single attention pass. The encoding advantage emerges where raw scanning degrades — empirically around 1500+ rows.
5. **Simple constraints are trivially parsed.** A 2-condition AND constraint in one paragraph is extracted in one reading. Distributing ≥3 conditions with nested logic across multiple paragraphs requires structured extraction.
6. **Fewer than 3 planted effects per scenario reduces statistical power at the effect-type level.** All three are mandatory — Simpson's, constraint-boundary, and interaction.

---

## Run 2 Directions — Amplify Encoding Effect

Run 1 (18 hrs, 26 scenarios) established: **sources dominate encoding in aggregate** (η²=0.120 vs 0.013), but encoding was highly significant for interaction-effect detection (η²=0.241, p<0.001). Simpson's paradox hit ceiling (MBRS 0.85–0.98 across all cells). The aggregate encoding null likely reflects that 2 of 3 effect types don't stress the encoding layer.

**Goal for Run 2:** Push encoding from subgroup-significant to aggregate-significant by designing scenarios where raw-text representations are *structurally incapable* of making relevant patterns legible.

### New Scenario Complexity Types

Add these to the scenario generator. Each scenario should include **at least 2** of the following on top of the 3 mandatory planted effects:

**1. Higher-order interactions (3-way, 4-way).** Current scenarios test pairwise coupling. Add lever triples where price × promotion × channel interact: the price–promotion elasticity reverses sign depending on channel. L4's cross-lever interaction profiles (lever triples) directly encode this; raw CSV does not. **Priority: highest — lowest implementation cost, directly stresses encoding.**

**2. Regime-switching data.** The data-generating process changes at an unknown breakpoint (e.g., market disruption mid-dataset). Pre-break correlations mislead post-break. Temporal belief objects with decay coefficients model this; raw CSV treats all rows equally. Include at least 4 scenarios with a regime break.

**3. Temporal coupling (time-lagged interactions).** Lever A's change at $t$ affects lever B's optimum at $t+\Delta t$. No single time-slice shows the coupling. Statistical profiles with cross-period correlation detect it; raw rows do not. Real-world analogue: promotion depth today affects brand equity (price elasticity) next quarter.

**4. Contradictory experts with segment-conditional validity.** Expert A says effect is positive (correct for segment X, wrong for Y). Expert B says negative (correct for Y, wrong for X). Raw text: LLM picks one or averages. Structured encoding: temporal belief objects with evidence fields let the LLM cross-reference each belief against segment-level profiles.

**5. Cascading constraint activation.** Constraint C1 is always active. Hitting C1's boundary activates dormant C2, which constrains a *different* lever pair. Raw text mentions both constraints but not the activation dependency. Tiered constraint vectors with conditional triggers encode this.

**6. Multi-mediator Simpson's paradox.** Current Simpson's: one confounder → stratify → reversal visible (too easy — ceiling). Harder: A → M1 → M2 → B where M1/M2 are partially observed. Stratifying by M1 alone doesn't resolve the paradox. This breaks the current ceiling.

### Updated Anti-Ceiling Gate

Phase 0 must verify: `mean MBRS_L1-data < 0.65` (tightened from 0.80) for scenarios using the new complexity types. If L1-data still scores above 0.65 on these, the scenario is not hard enough.

### Framing for the Paper

Do not frame the encoding finding as "encoding helps for hard problems" (sounds obvious). Frame as: **"Encoding depth exhibits a phase transition — irrelevant below a complexity threshold and critical above it."** The Run 1 interaction-effect subgroup (η²=0.241) is evidence of this transition; Run 2 scenarios are designed to cross the threshold more often.

---

## What Agents Decide

Agents own ALL implementation decisions not listed in Hard Rules:

- Exact scenario count (≥24), rows per scenario (≥1500, with ≥8 at ≥3000), column designs
- Simpson's paradox construction parameters (group overlap, noise levels, number of subgroups ≥4) — the only constraint is that the paradox must not be trivially visible from raw CSV at 1500+ rows and subgroup labels must be derived, not direct columns
- Constraint-boundary construction (number of conditions ≥3, how they're distributed across paragraphs) — must include at least one nested disjunction
- Interaction effect construction (which levers, what moderating variable, signal strength) — must not be a textbook-standard pattern and must pass the L1-data detection check
- Encoding representations (statistical profiles, constraint vectors, belief objects, process graphs)
- Discovery prompt wording (must be category-blind, must request structured JSON, must constrain to 3–5 findings)
- Rubric judge prompt wording (must include vocabulary normalization)
- Code pre-filter implementation (synonym maps, direction matching logic)
- Number/specialization of diagnostic agents for E3 (≥2, complementary; use confidence threshold, not fixed count)
- Causal synthesis schema (must include lever, direction, scope, mechanism)
- Quality gate weights and threshold (no hard cap on output count)
- Whether to include L2/L3 for a gradient plot (optional)
- Whether to add a 4th+ effect type beyond the 3 mandatory ones (must pass detection pilot first)
- Paper structure, related work, figure design, webapp layout

---

## Success Criteria

| ID | Criterion | How measured |
|----|-----------|-------------|
| **SC1** | Encoding improves discovery reliability | Main effect of encoding p < 0.05, OR interaction p < 0.05, OR cross-source main effect at L4 p < 0.05. At least one must hold. |
| **SC2** | Cross-source reasoning benefits from encoding | Interaction (encoding × sources) on cross-source MBRS. If underpowered, report cross-source main effect at L4 as primary, interaction as exploratory. |
| **SC9** | Design avoids ceiling effects | No cell has SD(MBRS) = 0.00 across scenarios; mean MBRS_L1-data < 0.80 (normalized). Verified in Phase 0 + Phase 1. |
| **SC3** | Pipeline compression scales with dimensionality | Report full distribution. High-dimensional scenarios (10+ levers) must achieve ≥100× effective compression. |
| **SC4** | Three invariants formally defined + single-invariant insufficiency | Logical argument in paper |
| **SC5** | Paper compiles, figures from actual data | Compilation + review |
| **SC6** | All claims backed by effect sizes and CIs | Statistical reporting |
| **SC7** | Pipeline architecture matches abstract | `pipeline_scores.json` with 5-dim gate |
| **SC8** | Simpson's paradox construction validated | Automated checks pass for all scenarios (see Hard Rule 13) |
| **SC10** | Interaction effect construction validated | Automated checks pass for all scenarios (see Hard Rule 15) |

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

With N=24 scenarios, 4 cells, k=3 runs, batched judging, code pre-filtering, and pilot-validated single vote:

| Component | Formula | Calls |
|-----------|---------|-------|
| Factorial discovery | 24 × 4 cells × 3 runs | 288 |
| Factorial judging (batched, 1 vote) | 288 batched calls | 288 |
| E3 pipeline | 24 × ~4 agents | ~96 |
| **Total** | | **~672** |

If pilot α < 0.85 (3-vote mode): judging × 3 → ~1152 total.

With optional sequential stopping (pre-registered, batches of 6): expected ~400–500 calls.

---

## Cleanup

When complete: delete all agent branches (local + remote), remove worktrees, prune, kill tmux sessions. `.llm_cache/` may be preserved.
