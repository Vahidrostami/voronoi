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

## Experimental Design: 2×4 Factorial + Difficulty Stratification + Pipeline Observation

A **2×4 within-subject factorial** tests encoding and source composition simultaneously. A separate **pipeline observation** tests the compression claim. The three-invariants characterization is a logical argument — no experiment needed.

### The 2×4 Factorial (Source Decomposition)

|  | **Data-only** | **Data+Policy** | **Data+Experts** | **All-sources** |
|--|---|---|---|---|
| **L1 (raw text)** | L1-D | L1-DP | L1-DE | L1-A |
| **L4 (structured)** | L4-D | L4-DP | L4-DE | L4-A |

**Why 2×4 instead of 2×2:** The prior 2×2 design lumped all non-data sources together and could not determine *which* source type drives the interaction. Source decomposition answers: is it the policy constraints? The expert beliefs? Both? This is critical because if only policy drives the effect, the expert encoding is decorative.

Six planned tests from one dataset:

| Abstract claim | Statistical test |
|---|---|
| Encoding enables discovery | Main effect of encoding (L4 vs L1, pooled across source conditions) |
| Cross-source reasoning works (policy) | L4-DP vs L4-D (policy adds value at L4?) |
| Cross-source reasoning works (experts) | L4-DE vs L4-D (experts add value at L4?) |
| Cross-source reasoning works (combined) | L4-A vs L4-D |
| **Encoding enables policy integration** | **Interaction: (L4-DP − L4-D) > (L1-DP − L1-D)** |
| **Encoding enables cross-source reasoning** | **Interaction: (L4-A − L4-D) > (L1-A − L1-D)** |

Bonferroni correction: α = 0.05/6 ≈ 0.0083 per test.

The policy interaction is predicted to be the strongest (constraint-boundary effects structurally require policy), with the expert interaction weaker but present for contradictory-expert scenarios.

### Difficulty Stratification

All N=36 scenarios are stratified into three difficulty tiers:

| Tier | N | Signal-to-noise | Expected L1-D MBRS | Purpose |
|---|---|---|---|---|
| **Easy** | 12 | SNR multiplier 2.0 | 0.55–0.70 | Shows system works when signal is clear |
| **Medium** | 12 | SNR multiplier 1.0 | 0.35–0.50 | Tests encoding under moderate challenge |
| **Hard** | 12 | SNR multiplier 0.5 | 0.05–0.25 | Tests encoding under severe challenge |

This enables a **dose-response analysis**: does the encoding × sources interaction *increase* with difficulty? Prediction: yes — encoding is irrelevant for easy scenarios (both L1 and L4 detect strong signals) but critical for hard ones (L1 collapses, L4 maintains partial detection).

Report: interaction d per difficulty tier + linear trend test on interaction magnitude × difficulty.

Signal chain: `encoding → single LLM discovery call → evaluation`. The pipeline (E3) is tested separately.

---

## Factorial Design Details

### Encoding Levels

| Level | Data | Knowledge | Playbook |
|-------|------|-----------|----------|
| **L1: Raw text** | CSV with headers + raw rows. NO statistics/aggregations/correlations | Policy as flat prose | Playbook as flat prose |
| **L4: Full structured** | Statistical profiles (raw rows REMOVED) | Tiered constraint vectors + temporal belief objects (prose REMOVED) | Process graph + rule catalog (prose REMOVED) |

**Key principle:** L4 pre-computes statistics via deterministic code; the LLM reasons over computed summaries instead of raw numbers. L4 character count must be within [0.7×, 1.5×] of L1. Encoding REPLACES raw content, never appends.

### L4 Constraint Encoding Specification (CRITICAL)

Prior run failure: L4-A constraint section rendered **empty headers with no rules**, then padded with 2000+ lines of `"(statistical profile complete — no additional signal)"` to meet character ratio. This made L4-A = L4-D + noise, destroying the encoding × sources interaction.

**Requirements for L4 constraint encoding:**
- Each compound constraint MUST render as: `RULE_ID: IF cond_1 AND cond_2 [OR cond_3 AND cond_4] → PROHIBIT action ON lever`
- Each condition: field name, operator, threshold value
- Nested disjunctions explicitly marked with OR groups
- Cross-reference with data: `"Data recommends increasing discount_pct (r=+0.35 with revenue). Conflicts with RULE_003."`
- `PolicyDocument.rules` list MUST be populated by the scenario generator — if empty, the encoder produces empty headers
- **NEVER pad with placeholder lines** to meet the [0.7×, 1.5×] ratio. If L4 is too short, add subgroup-level statistics, segment-conditional summaries, or cross-lever interaction profiles — real analytical content only.

### Source Conditions

| Condition | Code | Included |
|-----------|------|----------|
| **Data-only** | D | Quantitative data only |
| **Data+Policy** | DP | Data + policy documents (constraint rules) |
| **Data+Experts** | DE | Data + expert beliefs (temporal, segment-conditional) |
| **All-sources** | A | Data + policies + expert beliefs + playbook |

Playbook is always bundled with all-sources (never isolated) because it is procedural scaffolding, not an independent knowledge source.

### Data Generation: Structural Equation Model (SEM)

**Prior run weakness:** Effects were generated as additive overlays on independent random columns. A reviewer who reads the generator code will see that effects don't emerge from a realistic DGP — they're injected post-hoc. Independent columns are also unrealistically easy to analyze (no natural collinearity).

**New approach: Causal DAG per scenario.** Each scenario defines a directed acyclic graph over lever columns, with mechanistic edges:

```python
# Example DAG for an RGM scenario
base_price → net_price_per_unit    (mechanistic: net = base × (1 - discount))
base_price → gross_margin_pct      (mechanistic: margin increases with price)
promo_depth_pct → volume_uplift    (causal: deeper promos lift volume)
volume_uplift × margin → revenue_uplift  (definitional)
channel → price_elasticity         (moderator: elasticity differs by channel)
region → constraint_activation     (moderator: policies are region-conditional)
```

**Requirements:**
- Each scenario's DGP is defined by a DAG with ≥5 causal edges + ≥2 moderator edges
- **Simpson's paradox** emerges from a confounded DAG path where a latent confounder Z → X and Z → Y but the direct effect X → Y has opposite sign
- **Interaction effects** emerge from moderated mediation: A → M → Y where the A→M edge is moderated by B (the 3-way interaction A×B→M→Y becomes invisible when analyzing A or B alone)
- **Constraint boundaries** remain structurally planted in policy rules — no change needed
- Lever columns have **natural collinearity** arising from shared upstream causes (e.g., price and margin are mechanically related)
- **Difficulty is controlled by noise injection at DAG edges**: Easy = low noise (relationships are recoverable from aggregate stats), Hard = high noise (relationships are buried)

**Validation:** For each scenario, compute the correlation matrix of all lever columns. The mean absolute off-diagonal correlation should be ≥0.15 (realistic collinearity). If columns are near-independent (mean |r| < 0.10), the DAG is too sparse — add edges.

**Calibrate to real distributions:** Use empirically grounded marginals instead of generic distributions:
- Price variables: range $1.99–$12.99, modal at $3.99 (US CPG pricing norms)
- Promo depth: 10%–40% with mass at 15%–25% (trade promo benchmarks)
- SKU count: integer 5–200 per category (realistic planogram sizes)
- Distribution coverage: 0.3–0.95 (realistic retail coverage range)

### Planted Effects

Each scenario has **3 ground-truth effects** (all mandatory):

- **Simpson's paradox** — Aggregate correlation reverses at segment level. ≥4 overlapping subgroups, paradox NOT visible from scanning raw rows (overlapping x-values, noise masking within-group slopes). Subgroup labels derived from binning/clustering, not column headers. Use **multi-mediator** variants (A→M1→M2→B) where single-variable stratification fails. Validate: (a) aggregate vs within-group slope signs differ, (b) naive 100-row sample misses it, (c) subgroups not trivially column-derived.
- **Constraint-boundary** — Data recommends an action; a compound constraint prohibits it. ≥3 conditions with nested disjunction, distributed across ≥2 non-adjacent policy paragraphs. **This is the strongest test of the thesis** — structurally requires cross-source reasoning. The `PolicyDocument.rules` list must contain fully-specified `PolicyRule` objects that the L4 encoder can render as structured constraint vectors.
- **Interaction effect** — ≥2 levers produce non-additive outcome invisible when analyzed independently. Not a textbook-standard pattern. At least half of scenarios must have **3-way or 4-way interactions** where pairwise analysis shows nothing. Validate: (a) individual main effects p>0.10, (b) joint term p<0.05, (c) ≤20% L1-data pilot detection rate.

**Distractor patterns:** ≥2 real-but-non-planted patterns per scenario.

### Scenario Requirements

- **N = 36 scenarios**, structurally varied, stratified 12 easy / 12 medium / 12 hard. Power analysis: d≈0.39 (weakest per-type interaction in prior run) needs N≥34 paired at 80% power; N=36 provides margin.
- **≥1500 rows** per scenario. **≥12 scenarios at ≥3000 rows.** All rows delivered to LLM — never truncate.
- Realistic RGM column names. ≥5 lever columns per scenario (≥3 of 5 RGM domains). ≥10 lever columns in ≥8 scenarios. ≥2 categorical grouping variables.
- Each scenario includes **≥2 complexity types** (see Scenario Complexity Types below).
- Difficulty tier assigned at generation time. Each tier has balanced complexity-type coverage.

### Scenario Complexity Types

Each scenario must include ≥2 from this list, on top of the 3 mandatory planted effects. These ensure raw-text representations are *structurally incapable* of making patterns legible:

1. **Higher-order interactions (3-way, 4-way)** — e.g., price×promotion×channel where elasticity reverses by channel. L4 encodes cross-lever interaction profiles for lever triples; raw CSV does not. **Highest priority.**
2. **Regime-switching data** — DGP changes at unknown breakpoint. Pre-break correlations mislead post-break. Temporal belief objects with decay model this; raw CSV treats all rows equally. ≥4 scenarios.
3. **Temporal coupling** — Lever A at $t$ affects B's optimum at $t+\Delta t$. Statistical profiles with cross-period correlation detect it; raw rows do not.
4. **Contradictory experts with segment-conditional validity** — Expert A correct for segment X, wrong for Y; Expert B the reverse. Structured belief objects with evidence fields enable cross-referencing; raw text forces pick-one-or-average.
5. **Cascading constraint activation** — C1 always active; hitting C1's boundary activates dormant C2 on a different lever pair. Tiered constraint vectors with conditional triggers encode the dependency.

### Discovery Prompt (Chain-of-Thought)

LLM reports **exactly 5 findings in structured JSON** (columns, direction, magnitude, scope, mechanism, confidence). Category-blind.

The discovery prompt uses **structured reasoning scaffolding** to elicit deeper analysis without naming effect categories:

```
You are a senior analyst examining a business dataset with additional context.

TASK: Identify exactly 5 findings that would change a decision-maker's actions.

For each finding, you MUST:
1. First state what a naive analysis would conclude
2. Then explain why that conclusion is wrong or incomplete
3. Specify the EXACT conditions under which your finding holds

REASONING REQUIREMENTS:
- Before reporting any correlation, check whether it holds within each
  subgroup separately. If the sign flips, that IS the finding.
- Before recommending any action on a lever, check ALL provided
  constraints/policies for conflicts. If a recommended action violates
  a constraint, that IS the finding.
- Before concluding a variable has no effect, check whether it interacts
  with other variables jointly. Test combinations, not just individual variables.
- Cross-reference different information sources. If data suggests X but an
  expert or policy says not-X, explain the contradiction.

Return ONLY a JSON array of findings:
[{"columns": [...], "direction": "...", "magnitude": "...",
  "scope": "...", "mechanism": "...", "confidence": 0.0}]

DATA AND CONTEXT:
{encoding}
```

**Key design principles:**
- **Category-blind:** Never names Simpson's paradox, constraint-boundary, or interaction effects.
- **Reasoning checklist:** Explicit instructions to perform subgroup analysis, constraint checking, and multi-variable interaction testing. These are *analytical procedures*, not effect-type hints.
- **Naive-then-corrected structure:** Forces the LLM to articulate why the obvious conclusion is wrong — this naturally elicits the planted effects.
- **Exactly 5 findings:** Prevents the LLM from producing 3 shallow observations and stopping.
- **Same prompt for all 8 cells.** Only the encoded content changes.

### Evaluation

**Two-stage rubric matching:**
1. **Code pre-filter** — score Variables (graduated, see below) and Direction from JSON; eliminate non-matches without LLM call
2. **Batched LLM judge** — 8 dimensions per (finding, GT) pair:
   - **Graduated** (0.0–1.0): Variables = `|found ∩ gt_vars| / |gt_vars|` (proportion, NOT binary)
   - Binary (0/1): Direction, Scope, Mechanism, Quantification
   - Continuous (0–2): Precision, Completeness, Specificity
   - Match score = Variables + (binary sum) + (continuous sum / 6). Range 0–6. Threshold ≥3.5.

**Vote calibration:** Phase 1 runs 3 votes → Krippendorff's α. If α≥0.85, Phase 2 drops to 1 vote.

### Metrics

#### Primary: MBRS (Mean Best Rubric Score)
- Best match per GT effect, averaged per scenario. Normalized to [0,1].
- Analyzed via 2×4 repeated-measures ANOVA + Cohen's d + 95% CI.
- MBRS by effect type: Separate for Simpson's, constraint-boundary, interaction.
- Thesis-weighted MBRS: Interaction×2, constraint-boundary×1, Simpson's×1.
- Report both equal-weighted and thesis-weighted.

#### Deterministic Sub-Metrics (LLM-free, independently verifiable)

These metrics use NO LLM judge — computed purely from the structured JSON findings against ground truth. They eliminate the "LLM-judging-LLM" circularity critique.

| Metric | Computation | What it measures |
|---|---|---|
| **Variable Recall** | `\|found ∩ gt_vars\| / \|gt_vars\|` per finding, best-match per GT effect | Did the model identify the right levers? |
| **Direction Accuracy** | Exact match after normalization (positive/negative/reversal/non-additive) | Did it get the sign right? |
| **Constraint Rule Match** | Exact match on RULE_ID or ≥50% condition overlap with ground-truth rule | Did it find the specific policy conflict? |
| **Scope Precision** | Jaccard similarity on segment conditions (e.g., region, channel values) | Did it identify the correct subpopulation? |

Report deterministic metrics in a parallel table alongside MBRS. If deterministic metrics show the same interaction pattern as MBRS, the finding is robust to evaluator choice.

#### Constraint Detection Rate (CDR) — for constraint-boundary effects only

For each scenario × cell, score the best constraint-boundary finding on 4 sub-dimensions:
1. **Mentioned conflict** (binary): Did the finding acknowledge data-policy tension?
2. **Identified rule** (binary): Did it reference the correct constraint or rule ID?
3. **Identified conditions** (proportion): What fraction of the compound conditions were stated?
4. **Identified threshold** (binary): Did it give the numeric boundary?

CDR = mean of (1)–(4). Report CDR per cell. Prediction: L4-A ≫ L1-A ≫ L1-D on CDR, with L4 specifically excelling on conditions and threshold (impossible to extract from prose at L1).

#### Secondary
- **F1 by cell** at ≥3.5/6.0 and ≥4.5/6.0 thresholds. Report per-cell, not just aggregate. Prediction: L4-A has highest precision (fewest false discoveries).
- **Precision by cell**: `(correct findings) / (total findings)` — catches the "shotgun strategy" where models dump many low-quality findings.

### Phases

**Phase −1 — Encoding Pre-Flight (1 scenario, 0 LLM calls):**

Before any experimentation, verify encoding quality:
1. Generate all 8 encodings for 1 scenario. Print character counts.
2. L4-A constraint section MUST contain populated rules — not just headers. If empty → fix `PolicyDocument` construction and `_build_constraint_vectors()` before proceeding.
3. L4-A belief objects MUST have populated claims, confidence, decay, evidence, segment_validity.
4. Diff L4-D vs L4-A: delta MUST contain actual constraint rules and belief content.
5. Diff L4-D vs L4-DP: delta MUST contain constraint rules only (no expert content).
6. Diff L4-D vs L4-DE: delta MUST contain expert beliefs only (no constraint content).
7. Diff L1-D vs L1-A: delta MUST contain policy prose and expert text.
8. Character ratio [0.7×, 1.5×] achieved via content, NOT padding. Zero `"(no additional signal)"` lines allowed.
9. **If any check fails: STOP and fix the encoding layer.**

**Phase 0 — Difficulty Calibration (3 scenarios per tier = 9, L1-D only, k=3):**
- Run 3 easy, 3 medium, 3 hard scenarios at L1-D.
- **Anti-ceiling (easy):** mean MBRS < 0.75. These should be findable but not trivial.
- **Anti-ceiling (medium):** mean MBRS < 0.55.
- **Floor check (hard):** mean MBRS > 0.05. Hard scenarios must be non-trivial (not total noise).
- **Tier separation:** easy_mean − hard_mean ≥ 0.20. If tiers don't separate → adjust SNR multipliers.
- **Per-effect:** Each effect type MBRS < 0.67 in ≥1 medium/hard scenario.
- Reusable in Phase 2 if passed.

**Phase 1 — Pilot (6 scenarios = 2 per difficulty tier, all 8 cells, k=3):**
- Improvement gate: `MBRS_L4-A − MBRS_L1-D ≥ 0.10`
- Anti-ceiling: no cell SD = 0.00
- Encoding verification: hashes differ, L4 chars within [0.7×, 1.5×] of L1
- **Source decomposition diagnostic:** Compare L4-DP vs L4-D and L4-DE vs L4-D separately. If L4-DE < L4-D (experts hurt), investigate expert encoding quality. If L4-DP < L4-D, constraint encoding is broken.
- **Per-effect diagnostic:** Print MBRS by effect type × cell to identify which effects benefit from encoding. If constraint-boundary MBRS drops at L4-DP → the constraint encoding is broken.
- **Difficulty diagnostic:** Print interaction contrast by difficulty tier. If easy scenarios show zero interaction → good (confirms dose-response). If hard scenarios show zero interaction → encoding isn't strong enough.
- **Deterministic metrics diagnostic:** Compute Variable Recall and Direction Accuracy per cell. Verify they show the same pattern as MBRS.
- **Max 2 revision attempts.** On 3rd failure → `DESIGN_INVALID`, do NOT paper.
- If gates pass: proceed. If fail: STOP, diagnose, revise.

**Phase 2 — Full (N = 36, all 8 cells, k=3 or k=1 if α≥0.85):**
- HARD GATE: p<0.0083 (Bonferroni-corrected) on at least one of: (a) encoding×sources interaction (L4-A vs L4-D vs L1-A vs L1-D), (b) encoding main, (c) policy integration interaction (L4-DP vs L4-D vs L1-DP vs L1-D).
- If all fail: `DESIGN_INVALID`, do NOT paper.
- Report all six planned tests regardless of significance.
- Report per-difficulty-tier interaction contrasts.
- Report all deterministic sub-metrics (Variable Recall, Direction Accuracy, Constraint Rule Match, Scope Precision) per cell.
- Report CDR (Constraint Detection Rate) per cell.
- Report F1 and Precision per cell.
- Report dose-response trend: linear regression of interaction d on difficulty tier.

**Phase 3 — Paper + Webapp (only after Phase 2 passes)**

---

## E3: Pipeline Compresses Space

Run full pipeline on all scenarios at L4-A. Separate from factorial.

Compute `naive_space = C(n_levers, 2) × n_segments × n_knowledge_sources`. Report effective compression (naive_space → Stage 3 output):
- Low-dim (5 levers, 2–3 segments): 15–30×
- High-dim (10+ levers, 4+ segments): 100–270×

Report median, IQR, per-scenario. Quality gate scores 5 dimensions (evidence density, constraint alignment, actionability, testability, novelty) → `output/pipeline_scores.json`.

### Random Baseline Comparison (MANDATORY)

For each scenario, also generate a **random 15-item shortlist** (15 randomly sampled lever-pair × segment combinations). Evaluate both the pipeline shortlist and the random shortlist against ground truth using the same MBRS rubric.

Report:
- Pipeline shortlist recall: how many of the 3 planted effects appear in the 15 items?
- Random shortlist recall: same metric for the random baseline
- Quality score comparison: pipeline vs. random on all 5 quality dimensions

This converts the compression claim from "we select 15 from N" (trivially achievable) to "our 15 are *better* than random 15" (substantive).

---

## Hard Rules

1. **Same model for all cells.**
2. **Never truncate rows.** All rows delivered to LLM. Reduce columns if context is tight — never truncate rows.
3. **Category-blind discovery prompts.** Never name effect categories.
4. **Encoding replaces, never appends.** L4 chars within [0.7×, 1.5×] of L1.
5. **Single entry point:** `run_experiments.py`.
6. **LLM calls via** `copilot -p "<prompt>" -s --no-color --allow-all`. Cache by prompt hash.
7. **Ground truth used only for evaluation**, never loaded by reasoning system.
8. **≥1500 rows per scenario.** ≥8 scenarios at ≥3000 rows.
9. **k ≥ 3 runs per cell in Phase 1.** Phase 2 may use k=1 if α≥0.85 in Phase 1 vote calibration. Zero-variance cells make ANOVA meaningless.
10. **NO SIMULATION.** No mock/fake/sim files. Reduce N if budget is tight — never simulate.
11. **Cache validation.** `.llm_cache/` must contain ≥ N×8×k entries (8 cells per scenario).
12. **Batched judge calls** + code pre-filtering mandatory.
13. **Validate Simpson's construction.** After generating each scenario, automated checks: (a) aggregate slope sign ≠ majority within-group slope sign, (b) naive 100-row sample does NOT detect the reversal, (c) subgroup x-ranges overlap with `x_spread ≤ x_std`, (d) noise satisfies `noise_std ≥ 0.8 × |within_slope × x_std|`, (e) subgroup labels derived from binning/clustering, not raw column values. If validation fails, regenerate.
14. **Realistic RGM column names.** No generic `col_1`.
15. **Validate interaction construction.** Main effects p>0.10 individually, joint term p<0.05, not textbook-standard.
16. **Parallelize LLM calls.** For each scenario, dispatch all 8 cells simultaneously in separate subprocesses or tmux panes. Never serialize cells within one scenario. During Phase 2, maintain ≥8 concurrent LLM calls at all times.
17. **No encoding padding.** L4 character ratio must be achieved through real analytical content. If `_build_constraint_vectors()` or `_build_belief_objects()` returns empty/header-only content, the scenario generator is broken — fix it before running.
18. **Deterministic metrics are primary evidence.** The paper MUST report Variable Recall, Direction Accuracy, Rule Match, and Scope Precision alongside MBRS. If deterministic metrics contradict MBRS (e.g., MBRS shows interaction but Variable Recall does not), the MBRS result is suspect — investigate the judge.
19. **Code pre-filter is mandatory gate.** No finding may score >0 on the rubric unless it passes the code pre-filter (correct variables AND correct direction). This prevents the LLM judge from awarding credit to plausible-sounding but factually wrong findings.
20. **k=1 audit requirement.** If Phase 2 uses k=1 (after α≥0.85 in Phase 1), randomly select 6 scenarios (2 per difficulty tier) and re-run at k=3 as a post-hoc audit. If the k=3 scores differ from k=1 scores by >0.10 MBRS in >2 scenarios, fall back to k=3 for all cells.
21. **No LLM call may generate results.json.** The ANOVA, Cohen's d, CIs, and all statistical tests must be computed by deterministic Python code (scipy/numpy) from the cached rubric scores. The LLM is used only for (a) discovery calls and (b) judge calls — never for statistical computation.

---

## Call Budget

With N=36, 8 cells, and k dependent on Phase 1 vote calibration:

| Phase | Scenarios | Cells | k | Discovery | Judge (batched) | Total |
|---|---|---|---|---|---|---|
| Phase −1 | 1 | 8 | 0 | 0 | 0 | **0** |
| Phase 0 | 9 | 1 (L1-D) | 3 | 27 | ~54 | **~81** |
| Phase 1 | 6 | 8 | 3 | 144 | ~288 | **~432** |
| Phase 2 (k=1) | 36 | 8 | 1 | 288 | ~576 | **~864** |
| Phase 2 (k=3) | 36 | 8 | 3 | 864 | ~1728 | **~2592** |
| Pipeline | 36 | 1 | 1 | 0 (reuses L4-A) | ~36 | **~36** |

Best case (k=1 after α≥0.85): ~1,413 total calls.
Worst case (k=3 throughout): ~3,141 total calls.

---

## Known Failure Modes

Prior runs found these anti-patterns. Not hard rules, but documented traps:

1. **Ceiling from easy Simpson's.** Textbook Simpson's scores 0.85–0.98 across all cells. Use multi-mediator variants.
2. **Coarse rubric ceiling.** 5-binary-dim rubric clusters at top. The continuous dimensions (Precision, Completeness, Specificity) break this.
3. **k=1 collapses variance.** Single-run cells → zero within-cell variance → degenerate ANOVA.
4. **≤500 rows too easy.** Frontier LLMs scan 500×15 in one pass. Encoding advantage starts at ≥1500 rows.
5. **Simple constraints trivially parsed.** 2-condition AND in one paragraph is extracted trivially. Need ≥3 conditions with nested disjunction across multiple paragraphs.
6. **Empty L4 structured encoding.** Prior run: `_build_constraint_vectors()` rendered headers but no rules because `PolicyDocument.rules` was empty. The encoder then padded with 2000+ filler lines to meet character ratio. Result: L4-A ≈ L4-D + noise → sources degraded L4 performance. **This single bug killed the interaction effect.** Ensure scenario generator populates `PolicyDocument.rules` with actual `PolicyRule` objects and verify in Phase −1.
7. **Sources hurt at L4.** Prior run Phase 1 showed L4-A (0.234) < L4-D (0.265). If persists after fixing #6: one knowledge source type is adding noise. The 2×4 design's source decomposition (DP vs DE vs A) now diagnoses this directly.

---

## Success Criteria

| ID | Criterion | How measured |
|----|-----------|-------------|
| **SC1** | Encoding improves discovery | Encoding main p<0.0083, OR interaction p<0.0083, OR policy-integration interaction p<0.0083 |
| **SC2** | Cross-source benefits from encoding | Interaction on cross-source MBRS significant. Source decomposition identifies *which* source drives it. |
| **SC3** | Pipeline compression scales AND beats random | High-dim ≥100×. Pipeline recall > random recall (p<0.05 paired t-test). |
| **SC4** | Three invariants + insufficiency argument | Logical argument in paper |
| **SC5** | Paper compiles from actual data | Compilation + review |
| **SC6** | Claims backed by effect sizes and CIs | Statistical reporting |
| **SC7** | Pipeline architecture matches abstract | `pipeline_scores.json` with 5-dim gate |
| **SC8** | Simpson's construction validated | Automated checks (Hard Rule 13) |
| **SC9** | Design avoids ceiling AND floor | No cell SD=0; L1-D easy tier < 0.75; hard tier > 0.05 |
| **SC10** | Interaction construction validated | Automated checks (Hard Rule 15) |
| **SC11** | Deterministic metrics confirm MBRS pattern | Variable Recall and Direction Accuracy show same interaction direction as MBRS |
| **SC12** | Dose-response on difficulty | Interaction d increases monotonically from easy → medium → hard tiers |
| **SC13** | CDR decomposition for constraint-boundary | L4-A CDR conditions+threshold > L1-A CDR (p<0.05) |
| **SC14** | All per-type interactions significant | Constraint-boundary, Simpson's, AND interaction effects each show significant encoding×sources interaction at corrected α |

---

## Deliverables

```
demos/coupled-decisions/
  output/
    results.json            # Per-scenario per-cell per-run MBRS + ANOVA + per-type + per-tier
    deterministic_metrics.json  # Variable Recall, Direction Accuracy, Rule Match, Scope Precision per cell
    cdr_scores.json         # Constraint Detection Rate decomposition per cell
    pipeline_scores.json    # Pipeline + random baseline comparison
    encoding_hashes.json    # SHA-256 + char counts per encoding
    index.html              # Interactive webapp
    data/                   # Synthetic data + ground_truth per scenario
    paper/
      paper.tex + paper.pdf + figures/ + references.bib
  src/                      # All source code
  run_experiments.py        # Single entry point
  .llm_cache/               # Prompt-hash cache
```

Python 3.11+, numpy, scipy, matplotlib. Copilot CLI for all LLM calls.

When complete: delete agent branches, remove worktrees, kill tmux sessions.

---

## Completion Protocol

**Do NOT write `.swarm/deliverable.md` until ALL of the following are true:**
1. Phase 2 HARD GATE passed (at least one p<0.0083 among the six planned tests)
2. E3 pipeline compression + random baseline results logged to `output/pipeline_scores.json`
3. Paper compiles with all figures from actual experimental data
4. `output/results.json` contains complete per-scenario per-cell per-run metrics + ANOVA results
5. `output/deterministic_metrics.json` contains Variable Recall, Direction Accuracy, Rule Match, Scope Precision per cell
6. `output/cdr_scores.json` contains Constraint Detection Rate decomposition per cell
7. All 14 Success Criteria verified

Writing `deliverable.md` prematurely will cause the server to mark this investigation as complete and kill all agents. The deliverable is the LAST file written, after everything else is done.
