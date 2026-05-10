# Capability Thresholds in Multi-Source Reasoning: When Knowledge Compilation Starts to Matter

**The question.** LLMs are increasingly used as reasoning engines over heterogeneous knowledge — quantitative data, policy constraints, and expert judgment with incompatible truth conditions. Does **knowledge compilation** (transforming sources into epistemic-type-preserving representations before reasoning) provide lasting value as model capabilities improve, or is it a temporary crutch that frontier models outgrow?

Produce a complete academic paper answering this question. The paper must be rigorous enough for a top-tier venue (NeurIPS, ICML, AAAI). Framing must be honest: we report a **capability threshold** $K_c(M)$, estimated via logistic breakpoint, and test whether the transition is **sharp** against a smooth-sigmoid null — we do not assume sharpness.

---

## Abstract (contract)

> Large language models increasingly serve as reasoning engines over heterogeneous knowledge. We study whether **knowledge compilation** — transforming sources into epistemic-type-preserving representations before reasoning — provides lasting value as model capabilities improve.
>
> We introduce a benchmark with **deterministic ground truth**: synthetic decision scenarios with known causal DAGs, planted cross-source constraints, and forward-simulable outcomes — enabling evaluation without LLM-as-judge variance. Scenarios are parameterized along a **difficulty axis** $K$ bundling constraint depth, lever count, and source count (see §Design: difficulty vs. decomposition), plus an **orthogonal slice at $K_4$** that separates depth, width, and source-conflict dimensions. Models span sub-frontier to frontier capability and are ranked by an **a-priori capability proxy** (GPQA / MMLU-Pro / release date) fixed before data collection.
>
> Three findings. First, every model exhibits a **capability threshold** $K_c(M)$: below $K_c$, raw-text and compiled encodings perform equivalently; above $K_c$, raw-text performance degrades while compiled encodings hold. We explicitly compare a changepoint model against a smooth sigmoid and report which fits better — we do not assume the transition is sharp. Second, $K_c$ scales with the a-priori capability proxy (reported slope and 95% CI); **no model tested is immune** at $K_6$. Third, the $K_4$ orthogonal slice isolates **constraint depth** — not lever count or source count — as the dimension that compilation specifically neutralizes, and a **null-encoder control ($L_4'$: scrambled cross-references, decoy conflicts)** shows the benefit is not mere noise-removal.
>
> Compilation delivers equivalent-or-better accuracy at 2–5× fewer input tokens across all (Model, $K$) cells tested. The benchmark, encoder prompts (SHA-256 pinned), and all code are released.

This abstract is the contract. Every claim must be substantiated, or the claim is removed before submission.

---

## Core Thesis

Knowledge compilation is not a capability crutch — it is a **complexity management mechanism** with a model-dependent activation threshold. The paper maps the interaction surface of (model capability) × (knowledge complexity) × (encoding format) with deterministic evaluation, **and isolates which dimension of complexity compilation specifically addresses** via an orthogonal slice at $K_4$ plus a null-encoder control.

**The gap this fills:** Scaling laws characterize compute/data trade-offs. Prompt engineering studies vary input phrasing. RAG benchmarks test retrieval relevance. Nobody has mapped how **input structural complexity** interacts with model capability and encoding format using deterministic evaluation over known causal ground truth — and nobody has decomposed which kind of complexity compilation neutralizes.

---

## Experimental Design: 3 × (6 + 3) × M Factorial

> **Difficulty vs. decomposition.** The $K$ axis bundles five knobs (levers, constraint depth, source count, conflicts, rows). A threshold on $K$ alone would be a *difficulty* result, not a *complexity-decomposition* result. We therefore add an **orthogonal slice at $K_4$** (§Orthogonal slice below) so the paper can attribute the compilation benefit to a specific dimension of complexity, not to bundled difficulty.

### Independent Variables

**A. Encoding** — 3 levels:

| Level | What the LLM receives |
|-------|----------------------|
| **L1 (raw text)** | CSV with headers + raw rows, policy as prose, expert opinions as prose. No pre-computation. |
| **L4 (compiled)** | Statistical profiles (raw rows removed), tiered constraint vectors with cross-references, temporal belief objects with confidence/decay/conflicts. Prose removed. |
| **L4′ (null-encoder control)** | Same structural template and token budget as L4 — same object types, same section headers — but cross-references are **scrambled** (linked to random rules), conflict annotations are **decoys**, and belief ↔ constraint links are permuted. Compression is preserved; epistemic structure is destroyed. |

L4 and L4′ replace L1, never append. The natural compression is a feature — report L4/L1 token ratio as a diagnostic. **L4′ is the critical control**: if L4 beats L1 but L4′ also beats L1 by a similar margin, the benefit is noise-removal, not epistemic-type preservation. If L4 beats both L1 and L4′, the paper's specific thesis holds.

#### Encoder provenance (load-bearing)

- The L4 encoder is an **LLM call** (not a hand-written Python function), given **only** the L1 artifacts for the scenario. It **MUST NOT** have access to `ground_truth.json`, the SEM, the scenario generator seeds, or the discovery prompt's expected-finding format.
- The L4 encoder prompt is **pinned and SHA-256-hashed** before Phase 1. Any change invalidates all downstream runs. The prompt is reproduced verbatim in the paper appendix.
- The L4′ encoder takes a completed L4 artifact and applies a **deterministic scrambling transform** (seeded permutation of cross-references, random re-assignment of conflict flags). The transform preserves token count ±5%.
- An automated audit runs at scenario generation: diff of L4 output against L1 input must show **no novel lever names, no novel numeric values** that were not derivable from L1. Any hallucination fails the scenario.

**B. Difficulty ($K$) — 6 cumulative levels:**

| Level | Levers | Constraints | Constraint depth | Sources | Planted conflicts | Rows |
|---|---|---|---|---|---|---|
| $K_1$ | 3 | 1 simple (2 conditions) | 1-hop | 2 | 1 | 1000 |
| $K_2$ | 5 | 2 compound (3 conditions each) | 1-hop | 3 | 2 | 1500 |
| $K_3$ | 7 | 3 compound + 1 cascading | 2-hop | 3 | 3 | 2500 |
| $K_4$ | 10 | 4 compound + 2 cascading | 2-hop | 4 | 4 | 3500 |
| $K_5$ | 12 | 5 compound + 3 cascading + temporal coupling | 3-hop | 4 | 5 | 5000 |
| $K_6$ | 15 | 6 compound + 4 cascading + temporal + contradictory experts | 3-hop | 5 | 7 | 7000 |

"Constraint depth" = reasoning hops to detect a violation:
- **1-hop:** data says X, policy says not-X
- **2-hop:** data says X → triggers policy A → activates constraint B on lever Y
- **3-hop:** adds temporal dependency (action at $t$ creates constraint at $t+1$)

The $K$ levels are **cumulative** along the bundled axis — $K_6$ includes everything from $K_1$–$K_5$. This bundling is intentional for the main sweep (it is how real-world difficulty scales) but means the main sweep alone **cannot** identify which dimension drives the effect. The orthogonal slice (below) addresses this.

#### Orthogonal slice at $K_4$ (the decomposition)

Three additional cells anchored at $K_4$'s nominal difficulty, each varying one dimension while holding the others near $K_1$ baseline:

| Cell | Levers | Constraint depth | Sources | Conflicts | Rows |
|---|---|---|---|---|---|
| $K_4^{\text{depth}}$ | 5 | 3-hop cascading | 2 | 2 | 2000 |
| $K_4^{\text{width}}$ | 15 | 1-hop | 2 | 2 | 2000 |
| $K_4^{\text{sources}}$ | 5 | 1-hop | 5 | 7 | 2000 |

Claim: **if compilation specifically neutralizes constraint depth, then $L_1$–$L_4$ gap is largest at $K_4^{\text{depth}}$ and near-zero at $K_4^{\text{width}}$ / $K_4^{\text{sources}}$.** Pre-registered directional prediction. Tested with a 1-df planned contrast.

**C. Model** — 4–5 models spanning the capability range via `copilot` CLI. Each model is assigned an **a-priori capability score** fixed *before* data collection:

- Primary proxy: GPQA Diamond score (or MMLU-Pro if GPQA unavailable).
- Tiebreak: public release date.
- Scores are recorded in `models.json` with source URL and retrieval timestamp. **Never updated after Phase 1 begins.**
- The model legend on Figure 1 shows the proxy score; the $K_c$-vs-capability linear fit reports slope ±95% CI.

At least one sub-frontier and one frontier model. Do not use 5 models from the same family at similar capability.

### Design Matrix

Main sweep: $6(K) \times 3(\text{encoding}) \times M(\text{models}) \times 6(\text{scenarios per K}) \times 3(\text{runs})$.
Orthogonal slice: $3(K_4 \text{ cells}) \times 3(\text{encoding}) \times M \times 6 \times 3$.

L4′ only runs at $K_4$, $K_5$, $K_6$ in the main sweep (where the L1–L4 gap is expected) and across all three orthogonal-slice cells. This keeps call budget bounded while still providing the critical null control where it matters.

### Source Condition

Always **all-sources**: data + policies + expert beliefs + playbook. The question is not "does adding sources help?" (tested in prior run — answer depends on model). The question is "does *compiling* sources help, and when?"

---

## Scenario Generation

### Structural Equation Model (SEM)

Each scenario defines a DAG over lever columns with mechanistic edges. The scenario generator must produce:
- Causal edges with known coefficients (stored in `ground_truth.json`)
- Moderator edges (channel → elasticity, region → constraint activation)
- Natural collinearity from shared upstream causes
- Noise injection calibrated to the $K$ level

**Calibrate to realistic distributions** — RGM domain:
- Prices: $1.99–$12.99, modal $3.99
- Promo depth: 10–40%, mass at 15–25%
- SKU counts: 5–200
- Distribution coverage: 0.3–0.95

Use realistic column names. The domain is Revenue Growth Management but the structural claims generalize.

### Planted Effects (per scenario)

Each scenario has **3 ground-truth effects**:

1. **Constraint boundary** (primary) — Data recommends action; compound constraint prohibits it. Requires cross-source reasoning. At $K_1$: simple 2-condition constraint. At $K_6$: cascading 4-step chain with temporal trigger.

2. **Interaction effect** (supporting) — ≥2 levers produce non-additive outcome. Individual main effects p>0.10, joint term p<0.05. At higher $K$: 3-way and 4-way interactions.

3. **Simpson's paradox** (supporting) — Aggregate reverses at segment level. Multi-mediator variants at higher $K$.

**Requirements:**
- ≥60% of scenarios must have conflicting sources (data suggests X, policy prohibits X)
- ≥2 distractor patterns per scenario (real but non-planted)
- `PolicyDocument.rules` must be fully populated — never empty headers
- At higher $K$ levels, add regime-switching data, temporal coupling, contradictory experts with segment-conditional validity, cascading constraint activation

### Complexity Progression

The $K$ dimension is the experimental manipulation. The scenarios MUST be designed so that:
- At $K_1$–$K_2$: a strong model can reason correctly from raw text
- At $K_3$–$K_4$: raw text starts introducing errors (missed constraint chains, information overload)
- At $K_5$–$K_6$: raw text reasoning collapses for most models (too many levers, too many cross-references, constraints too deep)

Test this in Phase 0 calibration. If raw text doesn't degrade with $K$, increase the structural complexity (more constraint hops, more conflicting sources, more rows).

---

## Encoding Specifications

### L1 (Raw Text)
- CSV with headers + ALL raw rows. No statistics, no aggregations.
- Policy as flat prose paragraphs.
- Expert opinions as flat prose.
- Playbook as flat prose.

### L4 (Compiled)
- Generated by the **pinned L4 encoder LLM prompt** (see §Encoder provenance). Input: only L1 artifacts for the scenario.
- **Data:** Statistical profiles — means, correlations, subgroup-level stats, cross-lever interaction profiles. Raw rows removed.
- **Constraints:** Each rule as `RULE_ID: IF cond_1 AND cond_2 [OR cond_3 AND cond_4] → PROHIBIT action ON lever`. Cross-referenced with data: `"Data recommends increasing discount_pct (r=+0.35). Conflicts with RULE_003."` Conflict surface annotated.
- **Expert beliefs:** Temporal belief objects with claim, confidence [0,1], decay_rate, evidence_basis, segment_validity, conflicts_with.
- **No placeholder lines.** No `"(statistical profile complete)"` filler. If a section has no content, omit it.
- **Hallucination audit** (automated, mandatory): no lever names, numeric values, or entities appear in L4 that are not derivable from L1. Fail → scenario regenerated.

### L4′ (Null-encoder control)
- Same object types, same section headers, same token count (±5%) as L4.
- Cross-references permuted by a seeded random transform: each `conflicts_with: RULE_X` pointer is replaced with a random RULE_ID from the same scenario.
- Conflict annotations in data statistics (`"Conflicts with RULE_003"`) are re-drawn uniformly from the rule pool.
- Belief `segment_validity` fields are shuffled across beliefs.
- Rule bodies themselves are **not** altered — only the linking structure. This isolates "structural epistemic information" from "compression and de-prose."

---

## Discovery Prompt

Same prompt for all cells. Only the encoded content changes.

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

Category-blind. No hints about constraint checking, subgroup analysis, or interaction testing.

---

## Metrics

### Co-Primary (deterministic — no LLM judge)

| Metric | How computed |
|---|---|
| **Decision Regret** | Extract (lever, direction, magnitude) from findings → forward-simulate through known DAG → `regret = E[optimal] − E[recommended]`. Constraint violations penalized at 2× max feasible regret. |
| **Constraint Violation Rate (CVR)** | Each recommendation checked against ground-truth rules. Binary per recommendation. Rate = violated / total. |

### Token Efficiency (deterministic — no LLM call needed)

| Metric | How computed |
|---|---|
| **Input tokens** | Tokenize encoded context (L1 vs L4) using model-appropriate tokenizer. Report per-scenario. |
| **Output tokens** | Tokenize LLM response. Report per-scenario. |
| **Token compression ratio** | `L1_input_tokens / L4_input_tokens` per scenario per $K$ level. |
| **Cost per correct decision** | `total_tokens × price_per_token / max(1 − regret, 0.01)`. Price from public API pricing. |
| **Regret per kilotoken** | `regret / (input_tokens / 1000)`. Efficiency-normalized accuracy. |

Token counts are free — you already have the encodings and responses. Just count.

### Secondary (deterministic)

| Metric | How computed |
|---|---|
| Variable Recall | `|found ∩ gt_vars| / |gt_vars|` |
| Direction Accuracy | Exact match after normalization |
| Cascade Detection Rate | Per multi-hop constraint chain: did the model detect the full chain? Binary per chain. **New metric for this design.** |
| Cross-run σ | SD of Decision Regret across k runs |
| Failure Rate | Proportion of runs with best-match score = 0 |

### Evaluation Pipeline

1. **Code pre-filter:** score Variables and Direction from JSON. Eliminate non-matches.
2. **Batched LLM judge:** 8 dimensions per (finding, GT) pair. Match threshold ≥3.5.
3. **Vote calibration:** Phase 1 runs 3 judge votes → Krippendorff's α. If α≥0.85, Phase 2 drops to 1 vote.

---

## Phases

### Phase −1: Encoding Pre-Flight (0 discovery LLM calls)

Generate encodings for 1 scenario at each $K$ level (6 scenarios) plus the 3 orthogonal-slice cells. Run the pinned L4 encoder, then produce L4′ via the scrambling transform. Verify:
1. L4 constraint sections contain populated rules at every $K$ level — not empty headers
2. L4 belief objects have all fields populated
3. L1→L4 diff contains real analytical content; **L4 hallucination audit passes** (no novel lever names or numeric values vs L1)
4. L4′ preserves L4 token count within ±5%, object types and section headers identical, but `conflicts_with` / decoy annotations are demonstrably permuted (randomness check: ≥50% of links differ from L4)
5. Token compression ratio is reasonable (expect 2–10× depending on $K$)
6. Forward-simulate data-optimal action → CVR > 0 at ≥ $K_2$
7. Source conflicts present
8. No placeholder filler lines
9. `generator_lock.json` is written with the SHA-256 of generator code + config + encoder prompts

**If any check fails: STOP and fix before proceeding.**

### Phase 0: Difficulty Calibration (1 scenario per K × 2 encodings × 1 model, k=3)

Run on the median-capability model. L1 and L4 only (no L4′ yet — it needs a stable L4 first). 6 scenarios × 2 encodings × 3 runs = 36 calls.

Verify:
- **Difficulty gradient exists:** L1 regret increases monotonically with $K$ (rank correlation > 0.7)
- **L4 is flat or shallow:** L4 regret increases slower than L1 with $K$
- **Separation at high K:** L4 regret < L1 regret at $K_5$ and $K_6$ by ≥0.15
- **No ceiling at low K:** both L1 and L4 have non-zero regret at $K_1$
- **CVR > 0** at $K \geq K_3$ for L1

If the difficulty gradient is too weak (L1 doesn't degrade), tune the scenario generator (increase constraint depth, add conflicting sources, increase row counts at high $K$). **Max 2 calibration attempts.**

#### Generator freeze (anti-p-hack gate)

Phase 0 uses scenario seeds `0–5` (one per $K$). Phase 1 and Phase 2 run on seeds `≥ 100` — a disjoint, held-out range. Once Phase 0 passes:

1. The scenario generator config (code + config files + encoder prompts) is **frozen** and the combined SHA-256 is written to `output/generator_lock.json`.
2. All Phase 1 / Phase 2 / orthogonal-slice runs verify this hash at startup; mismatch → abort.
3. Any post-freeze change to the generator requires a **fresh Phase 0** run on new seeds. No exceptions.

This prevents tuning the generator until Phase 2 shows the predicted result on the same scenarios.

### Phase 1: Multi-Model Pilot (6 scenarios × 2 encodings × all models, k=3)

One scenario per $K$ level (seeds from the held-out range). L1 and L4 only. Purpose: verify the threshold pattern holds across models before committing Phase 2 budget.

Gates:
- Each model shows encoding benefit at its highest $K$ level (L4 regret < L1 regret)
- Models with lower a-priori capability score show earlier degradation than higher-capability models (rank correlation between capability proxy and estimated $K_c$ > 0.5)
- No model shows L1 > L4 at low $K$ by more than noise (encoding never meaningfully hurts accuracy)
- Token compression ratio consistent across models (encoding is model-independent)
- Generator hash matches `generator_lock.json`
- **Max 2 revision attempts.** On 3rd failure → `DESIGN_INVALID`.

### Phase 2: Full Experiment (main sweep + orthogonal slice + null-encoder)

**Main sweep:** 36 scenarios (6 per $K$) × L1 + L4 × $M$ models × 3 runs, plus L4′ at $K_4, K_5, K_6$.
**Orthogonal slice:** 6 scenarios each at $K_4^{\text{depth}}$, $K_4^{\text{width}}$, $K_4^{\text{sources}}$ × L1 + L4 + L4′ × $M$ models × 3 runs.

**Statistical analysis (pre-registered):**

1. **Primary model:** mixed-effects regression on Decision Regret with a **beta** (or logit-link Gaussian) family since regret ∈ [0, 1] and is heteroscedastic. Fixed effects: Encoding, $K$, Model, Encoding×$K$, Encoding×Model. Random intercepts by scenario.
2. **Primary test:** Encoding×$K$ interaction, likelihood-ratio test, $p < 0.017$ (Bonferroni over 3 primary tests).
3. **Null-encoder test (critical):** planned contrast $L_1 - L_4$ vs $L_1 - L_{4'}$ at $K \geq K_4$. L4 must beat L4′ by $\geq 0.10$ regret units ($p < 0.017$). **If this fails, the paper's thesis is noise-removal, not epistemic-type preservation — rewrite accordingly.**
4. **Decomposition test:** planned 1-df contrast at the $K_4$ orthogonal slice: $(L_1 - L_4)_{\text{depth}}$ vs mean$[(L_1 - L_4)_{\text{width}}, (L_1 - L_4)_{\text{sources}}]$, one-sided, $p < 0.017$.
5. **Per-model threshold $K_c$:** logistic regression on binary "encoding improved regret" indicator → breakpoint estimate per model with 95% bootstrap CI.
6. **Sharp vs smooth:** fit both a changepoint (piecewise-constant) and a smooth sigmoid to the same encoding-benefit data; report AIC/BIC difference and a likelihood-ratio test where nested. Do **not** claim "sharp" unless the changepoint is preferred.
7. **Capability scaling:** linear regression of estimated $K_c$ on a-priori capability proxy; report slope and 95% CI. This is the quotable claim.
8. **Effect sizes:** Cohen's $d$ at each (Model, $K$) cell, bootstrap 95% CI.
9. **CVR analysis:** paired comparison, L4 CVR < L1 CVR at $K \geq K_3$ ($p < 0.05$).
10. **Cascade Detection Rate** by $K$ level and encoding (descriptive).
11. **Token efficiency:** compression ratio, cost per correct decision, and accuracy-at-matched-token-budget (see SC4).

**HARD GATE (all three required):** (a) Encoding×$K$ interaction $p < 0.017$; (b) null-encoder contrast L4 > L4′ $p < 0.017$ at $K \geq K_4$; (c) decomposition contrast $p < 0.017$ **or** the orthogonal slice explicitly reported as null with reframed claims.

If (a) or (b) fails: `DESIGN_INVALID`, do NOT paper. If only (c) fails: the paper still goes out, but the title and abstract change from "compilation neutralizes constraint depth" to "compilation helps across complexity; dimension-specific attribution inconclusive."

Report all planned tests regardless of significance. Report effect sizes and 95% CIs for everything.

### Phase 3: Paper + Figures (only after Phase 2 passes)

---

## Key Figures (the paper's visual argument)

The paper lives or dies on these figures. Implement them from actual data.

### Figure 1: Capability-Threshold Diagram
$x$-axis: Difficulty ($K_1$–$K_6$). $y$-axis: Encoding benefit (L1 regret − L4 regret). One curve per model. Each model's curve crosses zero at its $K_c$. **Legend shows the a-priori capability proxy score** (GPQA / MMLU-Pro). Inset: scatter of estimated $K_c$ vs capability proxy with linear fit, slope and 95% CI annotated. Overlay the best-fit changepoint *and* smooth sigmoid with AIC/BIC difference reported in the caption.

### Figure 2: Accuracy at Matched Token Budget
$x$-axis: Input tokens (log scale). $y$-axis: Accuracy (1 − regret). One L1 curve and one L4 curve per model, each with 6 points ($K_1$–$K_6$). The L4 curve should sit at or above L1 for any given input-token budget — the honest reframing of "Pareto."

### Figure 3: Cascade Detection Heatmap
Rows: models (ordered by capability proxy). Columns: constraint depth (1-hop, 2-hop, 3-hop). Cell color: detection rate. Three sub-panels: L1, L4, L4′. The contrast L4 vs L4′ is the paper's sharpest visual claim — scrambling structure while keeping compression should degrade detection back toward L1 levels.

### Figure 4: The Decomposition (orthogonal $K_4$ slice)
Bar chart at $K_4$ nominal difficulty: L1 regret, L4 regret, L4′ regret for each of the three orthogonal cells ($K_4^{\text{depth}}$, $K_4^{\text{width}}$, $K_4^{\text{sources}}$). **This figure is the paper's theoretical punchline.** If compilation specifically addresses depth, the $L_1-L_4$ gap should be dramatically larger in the depth cell than in the width or sources cells.

### Figure 5: Cost Per Correct Decision
Bar chart: for each model at $K_4$ (the most practically relevant difficulty), show cost per correct decision for L1 vs L4. L4 should be cheaper everywhere.

Design additional figures as needed. These five are mandatory.

---

## E3: Feasible Trajectory Pruning

Run full pipeline on all scenarios at L4. Separate from the factorial.

Report:
- Compression ratio: `naive_space / pipeline_output_size`, expect 15–270× scaling with $K$
- Quality gate scores (evidence density, constraint alignment, actionability, testability, novelty)
- **Random baseline comparison:** pipeline shortlist recall vs random 15-item shortlist recall (paired t-test)
- Correlation of compression ratio with $K$ level (expect > 0.7)

---

## Hard Rules

1. **Same model for all cells within a model's Phase 2 run.** Each model runs independently.
2. **Never truncate rows.** All rows delivered. Reduce columns if context is tight.
3. **Category-blind discovery prompt.** Same prompt everywhere. No analytical hints.
4. **L4 and L4′ replace L1, never append.** Token compression is a feature.
5. **Single entry point:** `run_experiments.py`.
6. **LLM calls via** `copilot -p "<prompt>" -s --no-color --allow-all`. Cache by prompt hash.
7. **Ground truth used only for evaluation.** Never loaded by the reasoning system or the L4 encoder.
8. **L4 encoder is pinned.** Prompt SHA-256 recorded in `generator_lock.json`. No edits after Phase 0 passes.
9. **Capability proxy is a-priori.** `models.json` is frozen before Phase 1. Never updated.
10. **Generator freeze.** Phase 1/2 verify `generator_lock.json` hash on startup. Mismatch → abort.
11. **Held-out seeds.** Phase 0 uses seeds `0–5`; Phase 1 and Phase 2 use seeds `≥ 100`.
12. **k ≥ 3 in all phases.** Never k=1.
13. **NO SIMULATION.** No mock/fake/sim files. Reduce N or models if budget is tight.
14. **Deterministic metrics are primary evidence.** Decision Regret and CVR from forward-simulation through known DAGs using numpy.
15. **Token counts are mandatory.** Every run records input_tokens, output_tokens, token costs.
16. **Parallelize LLM calls.** ≥4 concurrent calls during Phase 2.
17. **Validate planted effects at scenario generation time.** Simpson's: aggregate vs within-group slopes differ. Interactions: main effects p>0.10, joint p<0.05. Constraints: CVR > 0 for data-optimal action.
18. **No LLM call may generate experiment_metrics.json.** All statistics computed by deterministic Python code.
19. **Replace zero-information scenarios** (identical regret across all cells, within ε=0.001).
20. **Failure handling (pre-registered):**
    - JSON-parse failure → one retry with identical prompt. Still fails → record `regret = max_feasible_regret`, `cvr = 1.0`, flag as `parse_fail`. Included in all primary analyses.
    - Model refusal / content flag → flag as `refusal`, log reason, **exclude** from primary analysis but report count per (Model, $K$, Encoding) cell.
    - Stall / timeout > 5 min → one retry. Still fails → same treatment as parse fail.
    - Refusal rate > 10% in any cell → flag in discussion; sensitivity analysis with refusals treated as max regret.

---

## Calibration History

Prior runs found these patterns — documented to prevent repeating mistakes:

1. **Ceiling from easy Simpson's.** Textbook Simpson's trivially detected. Fix: multi-mediator variants.
2. **k=1 collapses variance.** Fix: k≥3 always.
3. **≤500 rows too easy.** Frontier LLMs scan small tables trivially. Fix: ≥1000 rows at $K_1$, scaling up to ≥7000 at $K_6$.
4. **Simple constraints trivially parsed.** 2-condition AND easily extracted. Fix: ≥3 conditions with nested disjunction at $K \geq K_2$, cascading chains at $K \geq K_3$.
5. **Empty L4 encoding.** Prior run: encoder rendered empty constraint headers, padded with filler. L4-A ≈ L4-D + noise. Fix: scenario generator must populate `PolicyDocument.rules`. Verify in Phase −1.
6. **Source content redundant with data.** 14/36 scenarios showed no source differentiation. Fix: ≥60% conflicting sources.
7. **Constraint floor effect.** Only 7/36 scenarios triggered violations. Fix: ≥50% CVR > 0 at $K \geq K_2$.
8. **Discovery prompt category-hinting.** Original prompt had hints mapping 1:1 to effect types. Fix: genuinely category-blind prompt.
9. **Prior null on frontier model.** GPT-5.4 showed d=-0.13 on the original design — encoding didn't help because task complexity was too low ($K \approx K_2$–$K_3$). **This motivates the entire $K$-axis design.** The difficulty must go high enough to break the frontier model.
10. **Phase-transition framing was unfalsifiable under the original design.** Logistic-regression $K_c$ cannot distinguish sharp from gradual transitions; six $K$ levels is too coarse for finite-size scaling. Fix: claim "capability threshold," explicitly compare changepoint vs smooth sigmoid, only claim sharpness if data prefers the former.
11. **Bundled difficulty axis obscured attribution.** Varying 5 knobs together (levers, depth, sources, conflicts, rows) makes it impossible to say which complexity dimension compilation addresses. Fix: orthogonal slice at $K_4$ with 1-df planned contrast.
12. **Encoder leakage is the largest quiet threat.** If the L4 encoder sees ground truth or the DAG, L4 is the answer key. Fix: pinned encoder prompt SHA, L1-only input, hallucination audit at generation.
13. **Compression looks like a win by construction.** Reporting "Pareto dominance in tokens" trivially holds because L4 is compressed. Fix: headline metric is **accuracy at matched token budget**, not raw Pareto.
14. **Generator tuning until the result appeared.** "Max 2 calibration attempts" with no held-out seeds is p-hacking-adjacent. Fix: freeze generator via SHA-256 and run Phase 1/2 on disjoint seed range.
15. **Noise-removal confound.** L4 beats L1 could mean "compilation works" *or* "L1 has 10k tokens of prose noise." Fix: L4′ null-encoder control with scrambled cross-references at same token count.

---

## Success Criteria

| ID | Criterion | How measured |
|---|---|---|
| **SC1** | Encoding × $K$ interaction | Mixed-effects beta/logit LRT on Decision Regret, $p < 0.017$ |
| **SC2** | CVR reduction at high $K$ | L4 CVR < L1 CVR at $K \geq K_4$, $p < 0.05$ |
| **SC3** | Capability threshold $K_c$ estimable and scales with capability proxy | Per-model logistic breakpoint + linear fit $K_c$ vs GPQA/MMLU-Pro, slope 95% CI excludes 0 |
| **SC4** | L4 ≥ L1 accuracy at matched input-token budget | In ≥80% of (Model, $K$) cells, interpolated L1 accuracy at L4's token count ≤ observed L4 accuracy |
| **SC5** | Pipeline compression scales with $K$ | Compression × $K$ correlation > 0.7 |
| **SC6** | Paper compiles from actual data | All figures from real experimental results |
| **SC7** | Null-encoder control passes | L4 beats L4′ by $\geq 0.10$ regret units at $K \geq K_4$, $p < 0.017$ |
| **SC8** | Decomposition (orthogonal slice) | Planned contrast: $(L_1-L_4)$ at $K_4^{\text{depth}}$ > mean at $K_4^{\text{width}}, K_4^{\text{sources}}$, $p < 0.017$ — **OR** reported as null with reframed claims (still passes) |
| **SC9** | Generator freeze intact | `generator_lock.json` SHA-256 matches on every Phase 2 run; held-out seeds verified |

---

## Call Budget

Main sweep: 36 scenarios × {L1, L4} × M × 3, plus L4′ at $K_4, K_5, K_6$ (18 scenarios × 1 encoding × M × 3).
Orthogonal slice: 18 scenarios (6 × 3 cells) × {L1, L4, L4′} × M × 3.

| Phase | Discovery calls | Judge calls | Total |
|---|---|---|---|
| Phase −1 | 0 | 0 | **0** |
| Phase 0 | 36 | ~72 | **~108** |
| Phase 1 | 36M | ~72M | **~108M** |
| Phase 2 main | 216M + 54M (L4′) | ~540M | **~810M** |
| Phase 2 orth | 162M | ~324M | **~486M** |
| Pipeline | 0 (reuse) | ~36 | **~36** |

For $M=4$: ~1700 discovery + ~3800 judge ≈ **~5500 total** (with batching/caching). To reduce: drop L4′ from the orthogonal slice (keep it in main sweep) — saves ~648 calls, but weakens SC7 interpretation. Alternative: reduce scenarios per $K$ from 6 to 4 in main sweep. Never simulate. Never drop k below 3.

---

## Deliverables

```
demos/epistemic-trajectories/
  output/
    runner/
      experiment_metrics.json # Per-scenario per-encoding per-model per-run: regret, CVR, tokens
    token_efficiency.json     # Compression ratios, cost per correct decision, matched-budget accuracy
    deterministic_metrics.json
    reliability_metrics.json
    pipeline_scores.json      # Trajectory pruning + random baseline
    cascade_detection.json    # Per constraint chain: detected? by which model/encoding/L4′?
    encoding_hashes.json      # SHA-256 + token ratios (L1, L4, L4′)
    phase_transitions.json    # Per-model K_c estimates + CIs + changepoint-vs-sigmoid AIC/BIC
    null_encoder_contrast.json # L4 vs L4′ at K >= K_4: effect size, CI, p
    orthogonal_slice.json     # K_4 depth/width/sources results + decomposition contrast
    generator_lock.json       # SHA-256 of generator code + config + encoder prompts + seed ranges
    models.json               # A-priori capability proxy scores (frozen before Phase 1)
    failures.json             # Parse fails, refusals, timeouts by cell
    data/                     # Synthetic scenarios + ground_truth.json per scenario
    paper/
      paper.tex + paper.pdf + figures/ + references.bib
      appendix_encoder_prompt.md  # Full pinned L4 encoder prompt
    index.html                # Interactive webapp
  src/
  run_experiments.py
  .llm_cache/
```

Python 3.11+, numpy, scipy, statsmodels (for mixed-effects beta/logit), matplotlib. Copilot CLI for all LLM calls.

When complete: delete agent branches, remove worktrees, kill tmux sessions.

---

## Completion Protocol

**Do NOT write `.swarm/deliverable.md` until ALL of the following are true:**
1. Phase 2 HARD GATE passed (Encoding×$K$ interaction + null-encoder contrast; decomposition pass or explicit reframing)
2. Pipeline results in `output/pipeline_scores.json`
3. Paper compiles with all figures from actual data, including the pinned encoder prompt in the appendix
4. `output/runner/experiment_metrics.json` complete
5. `output/token_efficiency.json` complete (matched-budget accuracy included)
6. `output/phase_transitions.json` complete (includes changepoint vs sigmoid AIC/BIC)
7. `output/null_encoder_contrast.json` complete
8. `output/orthogonal_slice.json` complete
9. `output/generator_lock.json` hash verified against every Phase 1/2 run
10. All 9 Success Criteria verified (SC1–SC9)

Writing `deliverable.md` prematurely will cause the server to mark this investigation as complete and kill all agents. The deliverable is the LAST file written, after everything else is done.
