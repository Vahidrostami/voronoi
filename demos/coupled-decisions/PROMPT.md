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

A single **2×2 within-subject factorial** tests the encoding and source claims simultaneously. A separate **pipeline observation** tests the compression claim. The three-invariants characterization is a logical argument — no experiment needed.

### The 2×2 Factorial

|  | **Data-only** | **All-sources** |
|--|---------------|-----------------|
| **L1 (raw text)** | L1-data | L1-all |
| **L4 (structured)** | L4-data | L4-all |

Three tests from one dataset:

| Abstract claim | Statistical test |
|---|---|
| Encoding enables discovery | Main effect of encoding (L4 vs L1, pooled) |
| Cross-source reasoning works | Main effect of sources at L4 (L4-all vs L4-data) |
| **Encoding enables cross-source reasoning** | **Interaction: (L4-all − L4-data) > (L1-all − L1-data)** |

The cross-source main effect at L4 is the most defensible individual claim — constraint-boundary effects structurally require policy documents that L1-data cannot provide.

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

Prior run failure: L4-all constraint section rendered **empty headers with no rules**, then padded with 2000+ lines of `"(statistical profile complete — no additional signal)"` to meet character ratio. This made L4-all = L4-data + noise, destroying the encoding × sources interaction.

**Requirements for L4 constraint encoding:**
- Each compound constraint MUST render as: `RULE_ID: IF cond_1 AND cond_2 [OR cond_3 AND cond_4] → PROHIBIT action ON lever`
- Each condition: field name, operator, threshold value
- Nested disjunctions explicitly marked with OR groups
- Cross-reference with data: `"Data recommends increasing discount_pct (r=+0.35 with revenue). Conflicts with RULE_003."`
- `PolicyDocument.rules` list MUST be populated by the scenario generator — if empty, the encoder produces empty headers
- **NEVER pad with placeholder lines** to meet the [0.7×, 1.5×] ratio. If L4 is too short, add subgroup-level statistics, segment-conditional summaries, or cross-lever interaction profiles — real analytical content only.

### Source Conditions

| Condition | Included |
|-----------|----------|
| **Data-only** | Quantitative data only |
| **All-sources** | Data + policies + expert beliefs + playbook |

### Planted Effects

Each scenario has **3 ground-truth effects** (all mandatory):

- **Simpson's paradox** — Aggregate correlation reverses at segment level. ≥4 overlapping subgroups, paradox NOT visible from scanning raw rows (overlapping x-values, noise masking within-group slopes). Subgroup labels derived from binning/clustering, not column headers. Use **multi-mediator** variants (A→M1→M2→B) where single-variable stratification fails. Validate: (a) aggregate vs within-group slope signs differ, (b) naive 100-row sample misses it, (c) subgroups not trivially column-derived.
- **Constraint-boundary** — Data recommends an action; a compound constraint prohibits it. ≥3 conditions with nested disjunction, distributed across ≥2 non-adjacent policy paragraphs. **This is the strongest test of the thesis** — structurally requires cross-source reasoning. The `PolicyDocument.rules` list must contain fully-specified `PolicyRule` objects that the L4 encoder can render as structured constraint vectors.
- **Interaction effect** — ≥2 levers produce non-additive outcome invisible when analyzed independently. Not a textbook-standard pattern. At least half of scenarios must have **3-way or 4-way interactions** where pairwise analysis shows nothing. Validate: (a) individual main effects p>0.10, (b) joint term p<0.05, (c) ≤20% L1-data pilot detection rate.

**Distractor patterns:** ≥2 real-but-non-planted patterns per scenario.

### Scenario Requirements

- **N ≥ 24 scenarios**, structurally varied. Power analysis: d≈0.48 needs N≥28 paired; with mixed-effects (k=3), N≥24 suffices.
- **≥1500 rows** per scenario. **≥8 scenarios at ≥3000 rows.** All rows delivered to LLM — never truncate.
- Realistic RGM column names. ≥5 lever columns per scenario (≥3 of 5 RGM domains). ≥10 lever columns in ≥6 scenarios. ≥2 categorical grouping variables.
- Each scenario includes **≥2 complexity types** (see Scenario Complexity Types below).

### Scenario Complexity Types

Each scenario must include ≥2 from this list, on top of the 3 mandatory planted effects. These ensure raw-text representations are *structurally incapable* of making patterns legible:

1. **Higher-order interactions (3-way, 4-way)** — e.g., price×promotion×channel where elasticity reverses by channel. L4 encodes cross-lever interaction profiles for lever triples; raw CSV does not. **Highest priority.**
2. **Regime-switching data** — DGP changes at unknown breakpoint. Pre-break correlations mislead post-break. Temporal belief objects with decay model this; raw CSV treats all rows equally. ≥4 scenarios.
3. **Temporal coupling** — Lever A at $t$ affects B's optimum at $t+\Delta t$. Statistical profiles with cross-period correlation detect it; raw rows do not.
4. **Contradictory experts with segment-conditional validity** — Expert A correct for segment X, wrong for Y; Expert B the reverse. Structured belief objects with evidence fields enable cross-referencing; raw text forces pick-one-or-average.
5. **Cascading constraint activation** — C1 always active; hitting C1's boundary activates dormant C2 on a different lever pair. Tiered constraint vectors with conditional triggers encode the dependency.

### Discovery and Evaluation

LLM reports **3–5 findings in structured JSON** (columns, direction, magnitude, scope, mechanism, confidence). Category-blind.

**Two-stage rubric matching:**
1. **Code pre-filter** — score Variables and Direction from JSON; eliminate non-matches without LLM call
2. **Batched LLM judge** — 8 dimensions per (finding, GT) pair:
   - Binary (0/1): Variables, Direction, Scope, Mechanism, Quantification
   - Continuous (0–2): Precision (0=vague, 1=approximate, 2=exact), Completeness (0=fragment, 1=partial, 2=full), Specificity (0=generic, 1=partially scoped, 2=fully conditioned on correct subpopulation)
   - Match score = (binary sum) + (continuous sum / 6). Range 0–6. Threshold ≥3.5.

**Vote calibration:** Phase 1 runs 3 votes → Krippendorff's α. If α≥0.85, Phase 2 drops to 1 vote.

### Metrics

- **Primary: MBRS** (Mean Best Rubric Score) — best match per GT effect, averaged per scenario. Normalized to [0,1]. Analyzed via 2×2 repeated-measures ANOVA + Cohen's d + 95% CI.
- **MBRS by effect type** — Separate for Simpson's (data-only), constraint-boundary (cross-source), interaction. The hypothesis predicts cross-source MBRS shows larger encoding × sources interaction than data-only MBRS.
- **Thesis-weighted MBRS** — Interaction effects weight 2, constraint-boundary weight 1, Simpson's weight 1. Rationale: the paper's thesis is about coupled decision levers — interaction effects directly test multi-lever coupling, Simpson's is single-variable confounding. Report both equal-weighted and thesis-weighted. If thesis-weighted is significant and equal-weighted is not, this is evidence that encoding specifically helps with coupling.
- **Secondary:** F1 at ≥3.5/6.0 and ≥4.5/6.0 thresholds.

### Phases

**Phase −1 — Encoding Pre-Flight (1 scenario, 0 LLM calls):**

Before any experimentation, verify encoding quality:
1. Generate all 4 encodings for 1 scenario. Print character counts.
2. L4-all constraint section MUST contain populated rules — not just headers. If empty → fix `PolicyDocument` construction and `_build_constraint_vectors()` before proceeding.
3. L4-all belief objects MUST have populated claims, confidence, decay, evidence, segment_validity.
4. Diff L4-data vs L4-all: delta MUST contain actual constraint rules and belief content.
5. Diff L1-data vs L1-all: delta MUST contain policy prose and expert text.
6. Character ratio [0.7×, 1.5×] achieved via content, NOT padding. Zero `"(no additional signal)"` lines allowed.
7. **If any check fails: STOP and fix the encoding layer.**

**Phase 0 — Difficulty Calibration (3 scenarios, L1-data only, k=3):**
- **Anti-ceiling:** mean MBRS < 0.65 (tightened from 0.80 for harder scenarios). Remediation: increase rows, add confounders, increase noise, weaken signals.
- **Variance:** SD(MBRS) > 0.05 across 3 scenarios.
- **Per-effect:** Each effect type MBRS < 0.67 in ≥1 scenario.
- Reusable in Phase 2 if passed.

**Phase 1 — Pilot (3 scenarios, all 4 cells, k=3):**
- Improvement gate: `MBRS_L4-all − MBRS_L1-data ≥ 0.15`
- Anti-ceiling: no cell SD = 0.00
- Encoding verification: hashes differ, L4 chars within [0.7×, 1.5×] of L1
- **Source ablation diagnostic:** If L4-all < L4-data (sources hurt at L4), test L4-data+policy-only vs L4-data+expert-only on 1 scenario to identify which source degrades. Fix the problematic source encoding before proceeding.
- **Per-effect diagnostic:** Print MBRS by effect type × cell to identify which effects benefit from encoding. If constraint-boundary MBRS drops at L4-all → the constraint encoding is broken.
- **Max 2 revision attempts.** On 3rd failure → switch to fallback abstract (see Abstract Reframing below).
- If gates pass: proceed. If fail: STOP, diagnose, revise.

**Phase 2 — Full (N ≥ 24, k=3 per cell):**
- HARD GATE: p<0.05 on at least one of: (a) interaction, (b) encoding main, (c) cross-source main at L4.
- If all fail: `DESIGN_INVALID`, do NOT paper.
- Report all three tests regardless of significance.

**Phase 3 — Paper + Webapp (only after Phase 2 passes)**

---

## E3: Pipeline Compresses Space

Run full pipeline on all scenarios at L4-all. Separate from factorial.

Compute `naive_space = C(n_levers, 2) × n_segments × n_knowledge_sources`. Report effective compression (naive_space → Stage 3 output):
- Low-dim (5 levers, 2–3 segments): 15–30×
- High-dim (10+ levers, 4+ segments): 100–270×

Report median, IQR, per-scenario. Quality gate scores 5 dimensions (evidence density, constraint alignment, actionability, testability, novelty) → `output/pipeline_scores.json`.

---

## Abstract Reframing Strategy

The abstract claims an encoding × sources interaction. If Phase 1 (with fixed encoding) confirms the interaction → keep the abstract as-is.

**If the interaction fails after 2 revision attempts**, replace the interaction claim with a complexity-conditional encoding effect:

> *"the encoding layer exhibits a complexity-dependent activation pattern: its benefit is negligible for simple analytical tasks but becomes the dominant factor for effects involving multi-lever coupling, where raw-text representations are structurally incapable of making the relevant joint patterns legible."*

This is supported by prior data (interaction-effect MBRS at L4 is 3× L1). The sources main effect remains a separate finding.

**Decision gate after Phase 1:** interaction F-test p < 0.10 → keep interaction claim. p > 0.30 → switch to complexity-conditional reframe. 0.10 < p < 0.30 → expand to 6 pilot scenarios before deciding.

**Framing note:** Do NOT frame the encoding finding as "encoding helps for hard problems" (sounds obvious). Frame as: **"Encoding depth exhibits a phase transition — irrelevant below a complexity threshold and critical above it."**

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
9. **k ≥ 3 runs per cell.** Never reduce. Zero-variance cells make ANOVA meaningless.
10. **NO SIMULATION.** No mock/fake/sim files. Reduce N if budget is tight — never simulate.
11. **Cache validation.** `.llm_cache/` must contain ≥ N×4×k entries.
12. **Batched judge calls** + code pre-filtering mandatory.
13. **Validate Simpson's construction.** After generating each scenario, automated checks: (a) aggregate slope sign ≠ majority within-group slope sign, (b) naive 100-row sample does NOT detect the reversal, (c) subgroup x-ranges overlap with `x_spread ≤ x_std`, (d) noise satisfies `noise_std ≥ 0.8 × |within_slope × x_std|`, (e) subgroup labels derived from binning/clustering, not raw column values. If validation fails, regenerate.
14. **Realistic RGM column names.** No generic `col_1`.
15. **Validate interaction construction.** Main effects p>0.10 individually, joint term p<0.05, not textbook-standard.
16. **Parallelize LLM calls.** For each scenario, dispatch all 4 cells simultaneously in separate subprocesses or tmux panes. Never serialize cells within one scenario. During Phase 2, maintain ≥4 concurrent LLM calls at all times.
17. **No encoding padding.** L4 character ratio must be achieved through real analytical content. If `_build_constraint_vectors()` or `_build_belief_objects()` returns empty/header-only content, the scenario generator is broken — fix it before running.

---

## Known Failure Modes

Prior runs found these anti-patterns. Not hard rules, but documented traps:

1. **Ceiling from easy Simpson's.** Textbook Simpson's scores 0.85–0.98 across all cells. Use multi-mediator variants.
2. **Coarse rubric ceiling.** 5-binary-dim rubric clusters at top. The continuous dimensions (Precision, Completeness, Specificity) break this.
3. **k=1 collapses variance.** Single-run cells → zero within-cell variance → degenerate ANOVA.
4. **≤500 rows too easy.** Frontier LLMs scan 500×15 in one pass. Encoding advantage starts at ≥1500 rows.
5. **Simple constraints trivially parsed.** 2-condition AND in one paragraph is extracted trivially. Need ≥3 conditions with nested disjunction across multiple paragraphs.
6. **Empty L4 structured encoding.** Prior run: `_build_constraint_vectors()` rendered headers but no rules because `PolicyDocument.rules` was empty. The encoder then padded with 2000+ filler lines to meet character ratio. Result: L4-all ≈ L4-data + noise → sources degraded L4 performance. **This single bug killed the interaction effect.** Ensure scenario generator populates `PolicyDocument.rules` with actual `PolicyRule` objects and verify in Phase −1.
7. **Sources hurt at L4.** Prior run Phase 1 showed L4-all (0.234) < L4-data (0.265). If persists after fixing #6: one knowledge source type is adding noise. Use source ablation in Phase 1 to isolate.

---

## Success Criteria

| ID | Criterion | How measured |
|----|-----------|-------------|
| **SC1** | Encoding improves discovery | Encoding main p<0.05, OR interaction p<0.05, OR cross-source main at L4 p<0.05 |
| **SC2** | Cross-source benefits from encoding | Interaction on cross-source MBRS. Fallback: cross-source main at L4 as primary. |
| **SC3** | Pipeline compression scales | High-dim ≥100×. Report full distribution. |
| **SC4** | Three invariants + insufficiency argument | Logical argument in paper |
| **SC5** | Paper compiles from actual data | Compilation + review |
| **SC6** | Claims backed by effect sizes and CIs | Statistical reporting |
| **SC7** | Pipeline architecture matches abstract | `pipeline_scores.json` with 5-dim gate |
| **SC8** | Simpson's construction validated | Automated checks (Hard Rule 13) |
| **SC9** | Design avoids ceiling | No cell SD=0; mean MBRS_L1-data < 0.65 |
| **SC10** | Interaction construction validated | Automated checks (Hard Rule 15) |

---

## Deliverables

```
demos/coupled-decisions/
  output/
    results.json, pipeline_scores.json, encoding_hashes.json
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
1. Phase 2 HARD GATE passed (at least one p<0.05 among interaction, encoding main, cross-source main)
2. E3 pipeline compression results logged to `output/pipeline_scores.json`
3. Paper compiles with all figures from actual experimental data
4. `output/results.json` contains complete per-scenario per-cell per-run metrics + ANOVA results
5. All 10 Success Criteria verified

Writing `deliverable.md` prematurely will cause the server to mark this investigation as complete and kill all agents. The deliverable is the LAST file written, after everything else is done.
