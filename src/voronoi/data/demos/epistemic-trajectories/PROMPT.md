# Epistemic Interoperability in Coupled Decision Spaces: Knowledge Compilation Enables Cross-Source Constraint Detection and Feasible Trajectory Pruning

Produce a complete academic paper — with synthetic and real-data evidence — that introduces a knowledge compilation framework for reasoning over coupled decision levers under heterogeneous knowledge. The paper must be rigorous enough for a top-tier venue (AAAI, NeurIPS, ICML workshop, or Management Science).

---

## Abstract

> A broad class of applied decision problems — including revenue growth management, precision medicine, materials discovery, supply chain design, and financial risk management — share three structural invariants. **Lever coupling:** adjusting one decision variable alters the optimal configuration of others, rendering independent optimization invalid. **Knowledge heterogeneity:** the information needed to navigate the decision space is fragmented across sources with incompatible epistemic types — quantitative measurements, codified policy rules, and expert judgment each carry different truth conditions, confidence semantics, and temporal dynamics. **Cognitive assembly bottleneck:** no single source or single-lever analysis can identify the feasible region, forcing reliance on ad‑hoc human cognitive synthesis.
>
> This paper makes three contributions. First, we formally characterize this problem class through the three invariants and show that approaches addressing any single invariant in isolation necessarily produce incomplete solutions. This characterization defines the structural conditions under which a unified framework can generalize across domains.
>
> Second, we introduce an **epistemic-type-preserving encoding layer** — a knowledge compilation step, orthogonal to and composable with retrieval — that transforms each knowledge source into a reasoning-ready representation while preserving its native semantics: quantitative data as statistical profiles, policy knowledge as tiered constraint vectors, and expert judgment as temporal belief objects with confidence and decay functions. Crucially, conflicts between sources — such as data recommending an action that policy prohibits — become first-class diagnostic signals rather than noise. This is knowledge compilation, not retrieval: RAG solves *which* knowledge is relevant; encoding solves *how* already-available knowledge is represented for joint reasoning.
>
> Third, we present a **feasible trajectory pruning pipeline** that systematically narrows the combinatorial decision space. Parallel diagnostic agents eliminate infeasible and dominated trajectories along complementary analytical dimensions; a causal synthesis layer assembles surviving evidence into structured interventions specifying lever, direction, scope, and mechanism; and a multidimensional quality gate filters candidates on evidence density, constraint alignment, actionability, testability, and novelty. The output is a small set of causally grounded feasible trajectories through the coupled lever space — not point recommendations, but paths that respect coupling, constraints, and evidence quality.
>
> We instantiate the framework in Revenue Growth Management, where commercial levers — pricing, promotion, assortment, distribution, pack-price architecture — are deeply coupled and where knowledge is distributed across data, policy documents, and expert judgment. **The primary finding is that epistemic-type-preserving encoding enables cross-source constraint detection that raw-text concatenation structurally cannot perform.** Constraint-boundary effects — where data recommends an action that policy prohibits — are detectable only through joint reasoning across source types. The encoding × source-diversity interaction effect on Decision Regret is the headline result: the benefit of combining multiple knowledge sources is significantly larger under structured encoding than under raw text, where adding sources degrades or has no effect (information overload). The encoding main effect (structured > raw text) is secondary and expected — pre-computed statistics outperforming raw rows is not novel; what is novel is that encoding *unlocks* reasoning that raw text *destroys*. The feasible trajectory pruning pipeline compresses the combinatorial lever-pair space by 15–270× depending on scenario dimensionality, with pipeline-selected trajectories significantly outperforming random baselines. We validate that the three invariants manifest in real-world public datasets, eliminating reliance on synthetic-only evidence. We conclude by identifying the structural conditions under which the framework generalizes to other domains characterized by coupled decision levers.

This abstract is the contract. Every claim made above must be substantiated in the paper.

---

## Experimental Design: 2×2 Factorial + Real-Data Validation + Feasible Trajectory Pruning

A **2×2 within-subject factorial** tests whether epistemic-type-preserving encoding enables cross-source reasoning. A **real-data validation** confirms the invariants exist outside synthetic construction. A **pipeline observation** tests feasible trajectory pruning. The three-invariants characterization is a logical argument — no experiment needed.

### The 2×2 Factorial

|  | **Data-only** | **All-sources** |
|--|---|---|
| **L1 (raw text)** | L1-D | L1-A |
| **L4 (structured)** | L4-D | L4-A |

**Rationale:** In production, practitioners always have all available knowledge. The question is whether compiling that knowledge with epistemic type preservation improves joint reasoning versus pasting it as raw text.

Three planned tests from one dataset — **interaction is primary:**

| Abstract claim | Statistical test | Status |
|---|---|---|
| **Encoding enables cross-source reasoning** | **Interaction: (L4-A − L4-D) > (L1-A − L1-D) on Decision Regret** | **Primary** |
| Encoding reduces constraint violations | L4-A CVR < L1-A (p<0.05) | **Co-primary** |
| Encoding reduces Decision Regret | Main effect of encoding (L4 vs L1, pooled) | Secondary/expected |

Bonferroni correction: α = 0.05/3 ≈ 0.017 for primary test; 0.05 for co-primary.

**Why interaction is primary:** The encoding main effect (L4 > L1) is guaranteed — you've moved analytical work from the LLM to deterministic code. The novel claim is that encoding *enables* a qualitatively new capability (cross-source constraint detection) that raw text *cannot* support regardless of prompt quality. This is the "epistemic interoperability" thesis.

Two predicted sub-patterns:
- L1-A ≤ L1-D: adding sources as raw text hurts or is neutral (information overload). Establishes the *problem*.
- L4-A > L4-D: encoding unlocks cross-source reasoning. Establishes the *solution*.

### Difficulty Stratification

All N=36 scenarios are stratified into three difficulty tiers:

| Tier | N | SNR multiplier | Expected L1-D Regret | Purpose |
|---|---|---|---|---|
| **Easy** | 12 | 2.0 | Low (0.15–0.30) | Shows system works when signal is clear |
| **Medium** | 12 | 1.0 | Moderate (0.30–0.50) | Tests encoding under moderate challenge |
| **Hard** | 12 | 0.5 | High (0.50–0.80) | Tests encoding under severe challenge |

Dose-response prediction: encoding effect increases with difficulty. Easy scenarios show small or zero effect (both L1 and L4 detect strong signals). Hard scenarios show large effect (L1 collapses, L4 maintains partial detection).

Report: interaction d per difficulty tier + linear trend test on interaction effect magnitude × difficulty.

Signal chain: `encoding → single LLM discovery call → evaluation`. The pipeline (E3) is tested separately.

---

## Factorial Design Details

### Encoding Levels

| Level | Data | Knowledge | Playbook |
|-------|------|-----------|----------|
| **L1: Raw text** | CSV with headers + raw rows. NO statistics/aggregations/correlations | Policy as flat prose | Playbook as flat prose |
| **L4: Full structured** | Statistical profiles (raw rows REMOVED) | Tiered constraint vectors + temporal belief objects (prose REMOVED) | Process graph + rule catalog (prose REMOVED) |

**Key principle:** L4 pre-computes statistics via deterministic code; the LLM reasons over computed summaries instead of raw numbers. L4 encoding REPLACES raw content, never appends.

**Character ratio:** Report the natural L4/L1 character ratio per scenario as a diagnostic metric. Do NOT enforce a hard constraint — L4's natural compression is a feature of the encoding, not a confound. If L4 achieves lower regret with 0.3× the characters, that *strengthens* the knowledge compilation thesis. If L4 is naturally shorter, pad only with real analytical content (subgroup-level statistics, cross-lever interaction profiles, segment-conditional summaries) — NEVER with placeholder lines.

### L4 Constraint Encoding Specification (CRITICAL)

Prior run failure: L4-A constraint section rendered **empty headers with no rules**, then padded with 2000+ lines of `"(statistical profile complete — no additional signal)"` to meet character ratio. This made L4-A = L4-D + noise, destroying the interaction effect.

**Requirements for L4 constraint encoding:**
- Each compound constraint MUST render as: `RULE_ID: IF cond_1 AND cond_2 [OR cond_3 AND cond_4] → PROHIBIT action ON lever`
- Each condition: field name, operator, threshold value
- Nested disjunctions explicitly marked with OR groups
- Cross-reference with data: `"Data recommends increasing discount_pct (r=+0.35 with revenue). Conflicts with RULE_003."`
- `PolicyDocument.rules` list MUST be populated by the scenario generator — if empty, the encoder produces empty headers
- Conflict surface: for each constraint, explicitly annotate whether the data-optimal action conflicts, aligns, or is neutral

### L4 Belief Object Specification

Expert beliefs MUST encode as temporal belief objects with:
- `claim`: specific directional claim about a lever's effect
- `confidence`: numeric [0, 1]
- `decay_rate`: how quickly the belief loses validity
- `evidence_basis`: what supports the belief
- `segment_validity`: which segments the belief applies to
- `conflicts_with`: explicit cross-reference to data or policy sources that disagree

### Source Conditions

| Condition | Code | Included |
|-----------|------|----------|
| **Data-only** | D | Quantitative data only |
| **All-sources** | A | Data + policies + expert beliefs + playbook |

Playbook is always bundled with all-sources (never isolated) because it is procedural scaffolding, not an independent knowledge source.

**No partial-source conditions (DP, DE).** Source ablation is an engineering diagnostic done in Phase −1, not an experimental condition.

### Data Generation: Structural Equation Model (SEM)

Each scenario defines a directed acyclic graph over lever columns, with mechanistic edges:

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
- **Interaction effects** emerge from moderated mediation: A → M → Y where the A→M edge is moderated by B
- **Constraint boundaries** are structurally planted in policy rules — cross-lever (e.g., pricing constraint that activates only when promotion exceeds a threshold)
- Lever columns have **natural collinearity** from shared upstream causes (mean |r| ≥ 0.15)
- Difficulty controlled by noise injection at DAG edges

**Calibrate to real distributions:**
- Price variables: $1.99–$12.99, modal at $3.99 (US CPG pricing norms)
- Promo depth: 10%–40% with mass at 15%–25% (trade promo benchmarks)
- SKU count: integer 5–200 per category (realistic planogram sizes)
- Distribution coverage: 0.3–0.95 (realistic retail coverage range)

### Planted Effects (priority order)

Each scenario has **3 ground-truth effects** (all mandatory). Listed in priority order — constraint-boundary is the headline:

#### 1. Constraint Boundary (PRIMARY — the thesis test)

Data recommends an action; a compound constraint prohibits it. This is the **only** effect type that structurally requires cross-source reasoning — data alone sees the opportunity, policy alone states the rule, but neither in isolation reveals the conflict.

- ≥3 conditions with nested disjunction, distributed across ≥2 non-adjacent policy paragraphs
- **Cross-lever constraints** (e.g., pricing constraint activated when promotion exceeds threshold) — single-lever analysis cannot detect them
- `PolicyDocument.rules` must contain fully-specified `PolicyRule` objects
- ≥50% of scenarios must have active constraint conflicts where the data-optimal action hits a boundary
- Phase −1 must verify CVR > 0

#### 2. Interaction Effect (supporting)

≥2 levers produce non-additive outcome invisible when analyzed independently.
- At least half of scenarios must have **3-way or 4-way interactions** where pairwise analysis shows nothing
- Validate: (a) individual main effects p>0.10, (b) joint term p<0.05, (c) ≤20% L1-data pilot detection rate

#### 3. Simpson's Paradox (supporting)

Aggregate correlation reverses at segment level.
- ≥4 overlapping subgroups, paradox NOT visible from scanning raw rows
- Use **multi-mediator** variants (A→M1→M2→B) where single-variable stratification fails
- Validate: (a) aggregate vs within-group slope signs differ, (b) naive 100-row sample misses it

**Source conflict requirement:** ≥60% of scenarios must have conflicting sources — data suggests action X, policy prohibits X, expert hedges or disagrees. Source content must contain information not derivable from the CSV alone.

**Distractor patterns:** ≥2 real-but-non-planted patterns per scenario.

### Scenario Requirements

- **N = 36 scenarios**, stratified 12 easy / 12 medium / 12 hard
- **≥1500 rows** per scenario. **≥12 scenarios at ≥3000 rows.** All rows delivered to LLM — never truncate.
- Realistic RGM column names. ≥5 lever columns per scenario (≥3 of 5 RGM domains). ≥10 lever columns in ≥8 scenarios. ≥2 categorical grouping variables.
- Each scenario includes **≥2 complexity types** from the list below.

### Scenario Complexity Types

Each scenario must include ≥2:

1. **Higher-order interactions (3-way, 4-way)** — highest priority
2. **Regime-switching data** — DGP changes at unknown breakpoint. ≥4 scenarios.
3. **Temporal coupling** — Lever A at $t$ affects B's optimum at $t+\Delta t$
4. **Contradictory experts with segment-conditional validity** — Expert A correct for segment X, wrong for Y
5. **Cascading constraint activation** — hitting one constraint boundary activates a dormant constraint on a different lever pair

### Discovery Prompt

LLM reports **exactly 5 findings in structured JSON** (columns, direction, magnitude, scope, mechanism, confidence).

The discovery prompt is **genuinely category-blind** — no analytical procedures that map 1:1 to planted effect types:

```
You are a senior analyst examining a business dataset with additional context.

TASK: Identify exactly 5 findings that would change a decision-maker's actions.
Focus on findings where the obvious conclusion is wrong or incomplete.

For each finding, you MUST:
1. State what a naive analysis of this data would conclude
2. Explain why that conclusion is wrong, incomplete, or dangerous
3. Specify the EXACT conditions under which your corrected finding holds
4. Identify any source of information that contradicts another source

Return ONLY a JSON array of findings:
[{"columns": [...], "direction": "...", "magnitude": "...",
  "scope": "...", "mechanism": "...", "confidence": 0.0}]

DATA AND CONTEXT:
{encoding}
```

**Design principles:**
- **Category-blind.** No instructions to "check subgroups," "check constraints," or "test interactions." The prompt asks for findings where "the obvious conclusion is wrong" — this naturally invites all three effect types without hinting at any specific one.
- **Naive-then-corrected structure.** Forces the LLM to articulate what's misleading about first-pass analysis.
- **Exactly 5 findings.** Standardizes comparison across cells.
- **Same prompt for all 4 cells.** Only the encoded content changes.

### Evaluation

**Two-stage rubric matching:**
1. **Code pre-filter** — score Variables (graduated) and Direction from JSON; eliminate non-matches without LLM call
2. **Batched LLM judge** — 8 dimensions per (finding, GT) pair:
   - **Graduated** (0.0–1.0): Variables = `|found ∩ gt_vars| / |gt_vars|`
   - Binary (0/1): Direction, Scope, Mechanism, Quantification
   - Continuous (0–2): Precision, Completeness, Specificity
   - Match score = Variables + (binary sum) + (continuous sum / 6). Range 0–6. Threshold ≥3.5.

**Vote calibration:** Phase 1 runs 3 votes → Krippendorff's α. If α≥0.85, Phase 2 drops to 1 vote.

### Metrics

#### Co-Primary: Decision Regret + Constraint Violation Rate (deterministic, no LLM judge)

| Metric | Computation | What it measures |
|---|---|---|
| **Decision Regret** | Extract (lever, direction, magnitude) from each finding. Forward-simulate through the scenario's causal DAG. `regret = E[outcome | optimal_action] − E[outcome | model_recommended_action]`. Infeasible actions (constraint violations) incur penalty = 2× max feasible regret. | Practical value of the model's recommendation |
| **Constraint Violation Rate** | For each recommended action, check against all ground-truth constraint rules. Binary per recommendation. Rate = violated / total. | **Primary evidence for epistemic interoperability thesis.** Does encoding make cross-source conflicts actionable? |

Analyzed via 2×2 repeated-measures ANOVA + Cohen's d + 95% CI. Report per difficulty tier. **Interaction effect is the primary test.**

#### Secondary: Deterministic Discovery Metrics (LLM-free)

| Metric | Computation |
|---|---|
| **Variable Recall** | `\|found ∩ gt_vars\| / \|gt_vars\|` per finding, best-match per GT effect |
| **Direction Accuracy** | Exact match after normalization |
| **Constraint Rule Match** | Exact match on RULE_ID or ≥50% condition overlap |
| **Scope Precision** | Jaccard similarity on segment conditions |
| **Causal Edge Recovery F1** | Parse mechanisms into (cause, effect, direction) triples vs planted DAG |

#### Secondary: Reliability Metrics

| Metric | Computation |
|---|---|
| **Cross-run σ** | Standard deviation of Decision Regret across k runs per scenario × cell. Reported descriptively — L4 may have higher σ (diverse reasoning paths) while lower mean regret. |
| **Failure Rate** | Proportion of runs where best-match score = 0 for any planted effect |

#### Tertiary: MBRS (retained for comparability)

MBRS retained as descriptive metric. NOT used for hypothesis testing.

### Phases

**Phase −1 — Encoding Pre-Flight (1 scenario, 0 LLM calls):**

Before any experimentation, verify encoding quality:
1. Generate all 4 encodings for 1 scenario. Print character counts + natural ratio.
2. L4-A constraint section MUST contain populated rules — not just headers. If empty → fix `PolicyDocument` construction and `_build_constraint_vectors()` before proceeding.
3. L4-A belief objects MUST have populated claims, confidence, decay, evidence, segment_validity.
4. Diff L4-D vs L4-A: delta MUST contain actual constraint rules and belief content.
5. Diff L1-D vs L1-A: delta MUST contain policy prose and expert text.
6. No `"(no additional signal)"` placeholder lines.
7. **Source ablation diagnostic (engineering only):** Generate L4-DP and L4-DE for this 1 scenario. Verify L4-DP contains policy rules, L4-DE contains expert beliefs. These conditions are NOT used in the experiment.
8. **Constraint activation verification:** Forward-simulate the data-optimal action through constraint rules. At least one constraint must be violated (CVR > 0).
9. **Source conflict verification:** The pre-flight scenario must have at least one case where data recommends X and policy/expert opposes X.
10. **If any check fails: STOP and fix.**

**Phase 0 — Difficulty Calibration (3 scenarios per tier = 9, L1-D + L1-A, k=3):**
- **Anti-ceiling (easy):** mean Decision Regret > 0.15.
- **Anti-ceiling (medium):** mean Decision Regret > 0.30.
- **Floor check (hard):** mean Decision Regret < 0.95.
- **Tier separation:** hard_regret − easy_regret ≥ 0.15.
- **Source differentiation gate:** If L1-A = L1-D (|Δ regret| < 0.02) in >40% of pilot scenarios → regenerate source content with stronger conflicts.
- **Constraint activation gate:** CVR > 0 for L1-D in ≥50% of pilot scenarios.
- Reusable in Phase 2 if passed.

**Phase 0.5 — Real-Data Validation (2-3 public datasets, qualitative):**

Take 2-3 publicly available datasets (Kaggle retail/CPG data, published RGM case study, or equivalent):
1. **Invariant existence proof:** Show that lever coupling, knowledge heterogeneity, and the cognitive assembly bottleneck exist in the real data — not just synthetic construction.
2. **L1 failure demonstration:** Run L1 encoding on real data. Document specific cases where raw-text reasoning produces incorrect or incomplete conclusions.
3. **L4 improvement demonstration:** Run L4 encoding on the same data. Document cases where structured encoding surfaces insights that L1 missed.
4. **Qualitative analysis only.** No ground truth is available → cannot compute Decision Regret. Instead, document findings that domain practitioners would confirm as correct or valuable.

This is an **existence proof**, not a full factorial. Goal: demonstrate the invariants are real in non-synthetic contexts, eliminating the circularity objection ("you designed both the data and the encoding").

Report: `output/real_data_validation.json` with per-dataset L1 findings, L4 findings, and qualitative comparison.

**Phase 1 — Pilot (6 scenarios = 2 per difficulty tier, all 4 cells, k=3, 2 models):**
- Run on **primary model** AND **secondary model** (e.g., Claude + GPT-4)
- Improvement gate: L4-A Decision Regret < L1-D Decision Regret by ≥0.10
- Anti-ceiling: no cell SD = 0.00
- **Per-effect diagnostic:** Print Decision Regret by effect type × cell. Constraint-boundary should show the largest encoding × source interaction.
- **Difficulty diagnostic:** Print interaction contrast by difficulty tier.
- **Source differentiation diagnostic:** If L1-A = L1-D in >40% → regenerate.
- **Constraint Violation Rate diagnostic:** L4-A must have lower CVR than L1-A. CVR > 0 in ≥50% of scenarios.
- **Cross-model consistency:** Primary and secondary model must both show interaction effect in same direction — magnitude may differ. If effect direction reverses → framework is model-specific, not general.
- **Zero-information gate:** Replace scenarios with identical regret across all 4 cells.
- **Max 2 revision attempts.** On 3rd failure → `DESIGN_INVALID`, do NOT paper.

**Phase 2 — Full (N = 36, all 4 cells, k=3, primary model only):**
- **HARD GATE:** Interaction on Decision Regret p<0.017 OR L4-A CVR < L1-A p<0.05.
- If both fail: `DESIGN_INVALID`, do NOT paper.
- Report all three planned tests regardless of significance.
- Report interaction d per difficulty tier + dose-response trend.
- Report all deterministic discovery metrics per cell.
- Report reliability metrics per cell.
- Report natural L4/L1 character ratio per scenario as diagnostic.
- Report MBRS per cell as descriptive comparability metric.
- Replace zero-information scenarios (within ε=0.001).

**Phase 3 — Paper + Webapp (only after Phase 2 passes)**

---

## E3: Feasible Trajectory Pruning

Run full pipeline on all scenarios at L4-A. Separate from factorial.

The pipeline systematically reduces the combinatorial lever-pair space to a small set of **feasible trajectories** — causally grounded decision paths that respect lever coupling, constraint boundaries, and evidence quality.

Compute `naive_space = C(n_levers, 2) × n_segments × n_knowledge_sources`. Report effective compression (naive_space → Stage 3 output):
- Low-dim (5 levers, 2–3 segments): 15–30×
- High-dim (10+ levers, 4+ segments): 100–270×

Report median, IQR, per-scenario. Quality gate scores 5 dimensions (evidence density, constraint alignment, actionability, testability, novelty) → `output/pipeline_scores.json`.

### Random Baseline Comparison (MANDATORY)

For each scenario, generate a **random 15-item shortlist** (15 randomly sampled lever-pair × segment combinations). Evaluate both pipeline shortlist and random shortlist against ground truth.

Report:
- Pipeline shortlist recall vs random shortlist recall
- Quality score comparison on all 5 dimensions
- Paired t-test: pipeline recall > random recall

This converts "we select 15 from N" (trivially achievable) to "our 15 are *better* than random 15" (substantive).

---

## Hard Rules

1. **Same model for all cells within a phase.** (Phase 1 uses two models for cross-model validation.)
2. **Never truncate rows.** All rows delivered to LLM. Reduce columns if context is tight.
3. **Category-blind discovery prompts.** No analytical procedure that maps to a specific planted effect type.
4. **Encoding replaces, never appends.** Report natural character ratio as diagnostic, not as a constraint.
5. **Single entry point:** `run_experiments.py`.
6. **LLM calls via** `copilot -p "<prompt>" -s --no-color --allow-all`. Cache by prompt hash.
7. **Ground truth used only for evaluation**, never loaded by reasoning system.
8. **≥1500 rows per scenario.** ≥12 scenarios at ≥3000 rows.
9. **k ≥ 3 runs per cell in ALL phases.** k=1 is never permitted.
10. **NO SIMULATION.** No mock/fake/sim files. Reduce N if budget is tight — never simulate.
11. **Cache validation.** `.llm_cache/` must contain ≥ N×4×k entries.
12. **Batched judge calls** + code pre-filtering mandatory.
13. **Validate Simpson's construction.** Automated checks: (a) aggregate vs within-group slope signs differ, (b) naive 100-row sample misses it, (c) subgroup x-ranges overlap, (d) noise sufficient, (e) subgroup labels derived from binning/clustering.
14. **Realistic RGM column names.**
15. **Validate interaction construction.** Main effects p>0.10 individually, joint term p<0.05.
16. **Parallelize LLM calls.** ≥4 concurrent calls during Phase 2.
17. **Deterministic metrics are primary evidence.** Decision Regret and CVR are co-primary. MBRS is descriptive only.
18. **Code pre-filter is mandatory gate.** No finding scores >0 on rubric unless it passes code pre-filter.
19. **Zero-information scenario gate.** Replace scenarios with identical regret across all 4 cells.
20. **No LLM call may generate results.json.** All statistics computed by deterministic Python code.
21. **Decision Regret computation is deterministic.** Forward-simulation uses only numpy arithmetic. DAG and SEM coefficients stored in `ground_truth.json`.

---

## Calibration History

Prior runs found these patterns. Documented as methodological calibration:

1. **Ceiling from easy Simpson's.** Textbook Simpson's scores 0.85–0.98 across all cells. Fix: use multi-mediator variants.
2. **k=1 collapses variance.** Single-run cells → zero within-cell variance → degenerate ANOVA. Fix: k≥3 everywhere.
3. **≤500 rows too easy.** Frontier LLMs scan 500×15 in one pass. Fix: ≥1500 rows minimum.
4. **Simple constraints trivially parsed.** 2-condition AND in one paragraph is extracted trivially. Fix: ≥3 conditions with nested disjunction across multiple paragraphs.
5. **Empty L4 structured encoding.** Prior run: `_build_constraint_vectors()` rendered headers but no rules because `PolicyDocument.rules` was empty. The encoder padded with filler. Result: L4-A ≈ L4-D + noise → interaction destroyed. Fix: scenario generator populates `PolicyDocument.rules`, verify in Phase −1.
6. **Source content too weak / redundant with data.** 30-hour run: 14/36 scenarios showed L1-A = L1-D. Policy rules and expert beliefs were derivable from data patterns alone. Fix: require conflicting sources (≥60%) and Phase 0 source differentiation gate.
7. **Constraint floor effect.** 30-hour run: only 7/36 scenarios triggered any constraint violations. Fix: ≥50% scenarios with active constraint conflicts, Phase −1 CVR > 0 verification.
8. **Zero-information scenarios.** 30-hour run: 4/36 scenarios produced identical regret across all 4 cells. Fix: Phase 1 gate replaces them.
9. **L4 instability misread as defect.** L4-A had 35× higher cross-run σ than L1-A. This is expected — structured encoding creates diverse reasoning paths while raw text leads to formulaic responses. Fix: report σ descriptively, test mean regret + failure rate.
10. **Discovery prompt category-hinting.** Original prompt had three "reasoning requirements" that mapped 1:1 to three planted effect types. This is category-naming without category-naming. Fix: genuinely category-blind prompt with no analytical procedures targeting specific effects.

---

## Success Criteria

| ID | Criterion | How measured |
|----|-----------|-------------|
| **SC1** | Encoding enables cross-source reasoning | Interaction on Decision Regret p<0.017 |
| **SC2** | Encoding reduces constraint violations | L4-A CVR < L1-A p<0.05 |
| **SC3** | Pipeline feasible trajectories beat random | Pipeline recall > random recall p<0.05 |
| **SC4** | Dose-response on difficulty | Interaction d increases from easy → hard |
| **SC5** | Paper compiles from actual data | Compilation + all figures from real results |

**Prerequisites (verified in Phase −1, not success criteria):**
- Encoding construction valid (non-empty constraint vectors, belief objects)
- Simpson's construction valid (automated checks)
- Interaction construction valid (automated checks)
- Difficulty tiers calibrated (anti-ceiling, floor check, tier separation)
- Cross-model consistency confirmed (Phase 1)

**Deliverable checklist (not success criteria):**
- `results.json` complete with per-scenario per-cell per-run data
- `deterministic_metrics.json` complete
- `reliability_metrics.json` complete
- `pipeline_scores.json` with random baseline comparison
- `real_data_validation.json` with qualitative analysis
- `encoding_hashes.json` with natural character ratios
- Claims backed by effect sizes and CIs
- Three invariants formally defined
- Pipeline architecture matches abstract

---

## Call Budget

With N=36, 4 cells, k=3:

| Phase | Scenarios | Cells | k | Discovery | Judge (batched) | Total |
|---|---|---|---|---|---|---|
| Phase −1 | 1 | 4 | 0 | 0 | 0 | **0** |
| Phase 0 | 9 | 2 (L1-D, L1-A) | 3 | 54 | ~108 | **~162** |
| Phase 0.5 | 2-3 real | 2 (L1, L4) | 1 | ~6 | 0 (qualitative) | **~6** |
| Phase 1 (model 1) | 6 | 4 | 3 | 72 | ~144 | **~216** |
| Phase 1 (model 2) | 6 | 4 | 3 | 72 | ~144 | **~216** |
| Phase 2 (k=3) | 36 | 4 | 3 | 432 | ~864 | **~1296** |
| Pipeline | 36 | 1 | 1 | 0 (reuses L4-A) | ~36 | **~36** |

Total: ~1,932 calls. To reduce: decrease N from 36 to 18 while keeping k=3 — never reduce k.

---

## Deliverables

```
demos/epistemic-trajectories/
  output/
    results.json             # Per-scenario per-cell per-run Decision Regret + CVR + ANOVA
    deterministic_metrics.json
    reliability_metrics.json
    pipeline_scores.json     # Feasible trajectory pruning + random baseline
    encoding_hashes.json     # SHA-256 + natural character ratios
    real_data_validation.json  # Phase 0.5 qualitative analysis
    index.html               # Interactive webapp
    data/                    # Synthetic data + ground_truth per scenario (DAG + SEM)
    paper/
      paper.tex + paper.pdf + figures/ + references.bib
  src/                       # All source code
  run_experiments.py         # Single entry point
  .llm_cache/                # Prompt-hash cache
```

Python 3.11+, numpy, scipy, matplotlib. Copilot CLI for all LLM calls.

When complete: delete agent branches, remove worktrees, kill tmux sessions.

---

## Completion Protocol

**Do NOT write `.swarm/deliverable.md` until ALL of the following are true:**
1. Phase 2 HARD GATE passed (interaction p<0.017 or CVR p<0.05)
2. E3 feasible trajectory pruning + random baseline results in `output/pipeline_scores.json`
3. Paper compiles with all figures from actual experimental data
4. `output/results.json` complete
5. `output/deterministic_metrics.json` complete
6. `output/reliability_metrics.json` complete
7. `output/real_data_validation.json` complete (Phase 0.5)
8. All 5 Success Criteria verified

Writing `deliverable.md` prematurely will cause the server to mark this investigation as complete and kill all agents. The deliverable is the LAST file written, after everything else is done.
