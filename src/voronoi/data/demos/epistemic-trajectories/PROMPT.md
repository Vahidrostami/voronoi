# Phase Transitions in Multi-Source Reasoning: Knowledge Compilation Complexity Thresholds Across LLM Capability Tiers

Produce a complete academic paper demonstrating that LLM reasoning over heterogeneous knowledge sources exhibits **phase transitions** as knowledge complexity increases — and that epistemic-type-preserving encoding shifts the critical threshold. The paper must be rigorous enough for a top-tier venue (NeurIPS, ICML, AAAI).

---

## Abstract

> Large language models increasingly serve as reasoning engines over heterogeneous knowledge — quantitative data, policy constraints, and expert judgment with incompatible truth conditions. We study whether **knowledge compilation** (transforming sources into epistemic-type-preserving representations before reasoning) provides lasting value as model capabilities improve, or whether it is a temporary crutch that frontier models outgrow.
>
> We introduce a benchmark with **deterministic ground truth**: synthetic decision scenarios with known causal DAGs, planted cross-source constraints, and forward-simulable outcomes — enabling evaluation without LLM-as-judge variance. Scenarios are parameterized along a **knowledge complexity axis** $K$ (3–15 coupled decision levers, 1-hop to 3-hop constraint chains, 2–5 heterogeneous sources with planted conflicts) and tested across **4–5 models** spanning sub-frontier to frontier capability.
>
> Three findings. First, every model exhibits a **complexity phase transition**: below a critical $K_c(M)$, raw-text and compiled encodings perform equivalently; above $K_c$, raw-text performance collapses while compiled encodings maintain reasoning quality. The transition is sharp, not gradual. Second, $K_c$ increases with model capability — frontier models break later — but **no model tested is immune**: sufficiently complex multi-hop constraint chains defeat even the strongest models without compilation. Third, knowledge compilation is **Pareto-optimal across the entire complexity range**: below $K_c$ it delivers equivalent accuracy at 2–5× fewer input tokens; above $K_c$ it delivers superior accuracy at lower cost. The cost-accuracy Pareto frontier provides practitioners a decision function for when to invest in knowledge engineering.
>
> The benchmark, all code, and full results are released for reproducibility.

This abstract is the contract. Every claim must be substantiated.

---

## Core Thesis

Knowledge compilation is not a capability crutch — it is a **complexity management mechanism** with a model-dependent activation threshold. The paper maps the interaction surface of (model capability) × (knowledge complexity) × (encoding format) with deterministic evaluation.

**The gap this fills:** Scaling laws characterize compute/data trade-offs. Prompt engineering studies vary input phrasing. RAG benchmarks test retrieval relevance. Nobody has mapped how **input structural complexity** interacts with model capability and encoding format using deterministic evaluation over known causal ground truth.

---

## Experimental Design: 2 × 6 × M Factorial

### Independent Variables

**A. Encoding** — 2 levels:

| Level | What the LLM receives |
|-------|----------------------|
| **L1 (raw text)** | CSV with headers + raw rows, policy as prose, expert opinions as prose. No pre-computation. |
| **L4 (compiled)** | Statistical profiles (raw rows removed), tiered constraint vectors with cross-references, temporal belief objects with confidence/decay/conflicts. Prose removed. |

L4 replaces L1, never appends. The natural compression is a feature — report L4/L1 token ratio as a diagnostic.

**B. Knowledge Complexity ($K$)** — 6 levels:

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

$K$ levels are **cumulative** — each adds complexity atop the previous. $K_6$ includes everything from $K_1$–$K_5$.

**C. Model** — 4–5 models spanning the capability range. Use whatever models are available via `copilot` CLI at experiment time. Aim for meaningful capability spread — not 5 models from the same family at similar capability. At least one sub-frontier and one frontier model.

### Design Matrix

All-sources always (no D vs A split — source diversity is held constant). Every scenario gets all sources.

$6 (K) \times 2 (\text{encoding}) \times M (\text{models}) \times 6 (\text{scenarios per K}) \times 3 (\text{runs}) = 36 \times 2 \times M \times 3$ discovery calls per model.

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
- **Data:** Statistical profiles — means, correlations, subgroup-level stats, cross-lever interaction profiles. Raw rows removed.
- **Constraints:** Each rule as `RULE_ID: IF cond_1 AND cond_2 [OR cond_3 AND cond_4] → PROHIBIT action ON lever`. Cross-referenced with data: `"Data recommends increasing discount_pct (r=+0.35). Conflicts with RULE_003."` Conflict surface annotated.
- **Expert beliefs:** Temporal belief objects with claim, confidence [0,1], decay_rate, evidence_basis, segment_validity, conflicts_with.
- **No placeholder lines.** No `"(statistical profile complete)"` filler. If a section has no content, omit it.

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

### Phase −1: Encoding Pre-Flight (0 LLM calls)

Generate encodings for 1 scenario at each $K$ level (6 scenarios total). Verify:
1. L4 constraint sections contain populated rules at every $K$ level — not empty headers
2. L4 belief objects have all fields populated
3. L1→L4 diff contains real analytical content
4. Token compression ratio is reasonable (expect 2–10× depending on $K$)
5. Forward-simulate data-optimal action → CVR > 0 at ≥ $K_2$
6. Source conflicts present
7. No placeholder filler lines

**If any check fails: STOP and fix before proceeding.**

### Phase 0: Complexity Calibration (1 scenario per K × 2 encodings × 1 model, k=3)

Run on the median-capability model. 6 scenarios × 2 encodings × 3 runs = 36 calls.

Verify:
- **Complexity gradient exists:** L1 regret increases monotonically with $K$ (rank correlation > 0.7)
- **L4 is flat or shallow:** L4 regret increases slower than L1 with $K$
- **Separation at high K:** L4 regret < L1 regret at $K_5$ and $K_6$ by ≥0.15
- **No ceiling at low K:** both L1 and L4 have non-zero regret at $K_1$
- **CVR > 0** at $K \geq K_3$ for L1

If the complexity gradient is too weak (L1 doesn't degrade), increase constraint depth, add more conflicting sources, or increase row counts at high $K$. **Max 2 calibration attempts.**

### Phase 1: Multi-Model Pilot (6 scenarios × 2 encodings × all models, k=3)

One scenario per $K$ level. Purpose: verify the phase transition pattern holds across models.

Gates:
- Each model shows encoding benefit at its highest $K$ level (L4 regret < L1 regret)
- Weaker models break at lower $K$ than stronger models
- No model shows L1 > L4 at low $K$ (encoding never hurts accuracy)
- Token compression ratio consistent across models (encoding is model-independent)
- **Max 2 revision attempts.** On 3rd failure → `DESIGN_INVALID`.

### Phase 2: Full Experiment (36 scenarios × 2 encodings × all models, k=3)

6 scenarios per $K$ level × 2 encodings × $M$ models × 3 runs.

**Statistical analysis:**

1. **3-way ANOVA:** Encoding × Complexity × Model on Decision Regret
2. **Primary test:** Encoding × Complexity interaction (p < 0.017, Bonferroni-corrected)
3. **Per-model breakpoint $K_c$:** Logistic regression on binary "encoding improved regret" indicator → estimate threshold $K_c(M)$ per model
4. **Cohen's d** at each (Model, $K$) cell
5. **CVR analysis:** L4 CVR < L1 CVR at $K \geq K_3$ (p < 0.05)
6. **Cascade Detection Rate** by $K$ level and encoding
7. **Token efficiency:** compression ratio, cost per correct decision, Pareto frontier
8. **Pipeline compression** scaling with $K$

**HARD GATE:** Encoding × Complexity interaction p < 0.017 **OR** CVR improvement at high $K$ p < 0.05.
If both fail: `DESIGN_INVALID`, do NOT paper.

Report all planned tests regardless of significance. Report effect sizes and 95% CIs for everything.

### Phase 3: Paper + Figures (only after Phase 2 passes)

---

## Key Figures (the paper's visual argument)

The paper lives or dies on these figures. Implement them from actual data.

### Figure 1: Phase Diagram
$x$-axis: Knowledge Complexity ($K_1$–$K_6$). $y$-axis: Encoding benefit (L1 regret − L4 regret). One curve per model. Each model's curve crosses zero at its $K_c$ — the phase transition point. Weaker models cross earlier.

### Figure 2: Pareto Frontier
$x$-axis: Input tokens. $y$-axis: Accuracy (1 − regret). One L1 curve and one L4 curve per model, each with 6 points ($K_1$–$K_6$). L4 should be up-and-left of L1 everywhere (same or better accuracy, fewer tokens).

### Figure 3: Cascade Detection Heatmap
Rows: models (weakest to strongest). Columns: constraint depth (1-hop, 2-hop, 3-hop). Cell color: detection rate. Should show a diagonal boundary — each model handles more hops, but all models eventually fail on raw text while succeeding on compiled encoding.

### Figure 4: Cost Per Correct Decision
Bar chart: for each model at $K_4$ (the most practically relevant complexity), show cost per correct decision for L1 vs L4. L4 should be cheaper everywhere.

Design additional figures as needed. These four are mandatory.

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
4. **L4 replaces L1, never appends.** Token compression is a feature.
5. **Single entry point:** `run_experiments.py`.
6. **LLM calls via** `copilot -p "<prompt>" -s --no-color --allow-all`. Cache by prompt hash.
7. **Ground truth used only for evaluation.** Never loaded by the reasoning system.
8. **k ≥ 3 in all phases.** Never k=1.
9. **NO SIMULATION.** No mock/fake/sim files. Reduce N or models if budget is tight.
10. **Deterministic metrics are primary evidence.** Decision Regret and CVR from forward-simulation through known DAGs using numpy.
11. **Token counts are mandatory.** Every run records input_tokens, output_tokens, token costs.
12. **Parallelize LLM calls.** ≥4 concurrent calls during Phase 2.
13. **Validate planted effects at scenario generation time.** Simpson's: aggregate vs within-group slopes differ. Interactions: main effects p>0.10, joint p<0.05. Constraints: CVR > 0 for data-optimal action.
14. **No LLM call may generate results.json.** All statistics computed by deterministic Python code.
15. **Replace zero-information scenarios** (identical regret across all cells, within ε=0.001).

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
9. **Prior null on frontier model.** GPT-5.4 showed d=-0.13 on the original design — encoding didn't help because task complexity was too low ($K \approx K_2$–$K_3$). **This motivates the entire $K$-axis design.** The complexity must go high enough to break the frontier model.

---

## Success Criteria

| ID | Criterion | How measured |
|---|---|---|
| **SC1** | Encoding × Complexity interaction | 3-way ANOVA on Decision Regret, p < 0.017 |
| **SC2** | CVR reduction at high K | L4 CVR < L1 CVR at $K \geq K_4$, p < 0.05 |
| **SC3** | Phase transition detectable | Per-model $K_c$ estimable via logistic breakpoint |
| **SC4** | L4 Pareto-dominates on cost-accuracy | L4 has ≤ tokens AND ≤ regret in ≥80% of (Model, K) cells |
| **SC5** | Pipeline compression scales with K | Compression × K correlation > 0.7 |
| **SC6** | Paper compiles from actual data | All figures from real experimental results |

---

## Call Budget

With 36 scenarios, 2 encodings, M models, k=3:

| Phase | Scenarios | Encodings | Models | k | Discovery | Judge | Total |
|---|---|---|---|---|---|---|---|
| Phase −1 | 6 (1 per K) | 2 | 0 | 0 | 0 | 0 | **0** |
| Phase 0 | 6 | 2 | 1 | 3 | 36 | ~72 | **~108** |
| Phase 1 | 6 | 2 | M | 3 | 36M | ~72M | **~108M** |
| Phase 2 | 36 | 2 | M | 3 | 216M | ~432M | **~648M** |
| Pipeline | 36 | 1 | 1 | 1 | 0 (reuse) | ~36 | **~36** |

For M=4: ~2,700 discovery + ~5,400 judge ≈ **~3,200 total** (with batching/caching).
To reduce: decrease M, decrease N per K level, or decrease k to 3 (already minimum). Never simulate.

---

## Deliverables

```
demos/epistemic-trajectories/
  output/
    results.json              # Per-scenario per-encoding per-model per-run: regret, CVR, tokens
    token_efficiency.json     # Compression ratios, cost per correct decision, Pareto data
    deterministic_metrics.json
    reliability_metrics.json
    pipeline_scores.json      # Trajectory pruning + random baseline
    cascade_detection.json    # Per constraint chain: detected? by which model/encoding?
    encoding_hashes.json      # SHA-256 + token ratios
    phase_transitions.json    # Per-model K_c estimates + confidence intervals
    data/                     # Synthetic scenarios + ground_truth.json per scenario
    paper/
      paper.tex + paper.pdf + figures/ + references.bib
    index.html                # Interactive webapp
  src/
  run_experiments.py
  .llm_cache/
```

Python 3.11+, numpy, scipy, matplotlib. Copilot CLI for all LLM calls.

When complete: delete agent branches, remove worktrees, kill tmux sessions.

---

## Completion Protocol

**Do NOT write `.swarm/deliverable.md` until ALL of the following are true:**
1. Phase 2 HARD GATE passed
2. Pipeline results in `output/pipeline_scores.json`
3. Paper compiles with all figures from actual data
4. `output/results.json` complete
5. `output/token_efficiency.json` complete
6. `output/phase_transitions.json` complete
7. All 6 Success Criteria verified

Writing `deliverable.md` prematurely will cause the server to mark this investigation as complete and kill all agents. The deliverable is the LAST file written, after everything else is done.
