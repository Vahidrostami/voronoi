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

## Three Claims → Three Experiments

The abstract makes three claims. Each gets **one clean experiment** with a **direct signal chain**. No experiment tests more than one claim.

| # | Abstract claim | Experiment | What varies | What's measured |
|---|---------------|------------|-------------|-----------------|
| **E1** | Encoding layer enables cross-type reasoning that reveals effects invisible to siloed analyses | **L1 vs L4 discovery** | Encoding level (raw text vs full structured) | Effect discovery F1 |
| **E2** | Encoding preserves epistemic differences; conflicts become diagnostic signals | **All-sources vs data-only** at L4 | Knowledge sources included | Effect discovery recall |
| **E3** | Progressive pipeline compresses a large candidate space | **Pipeline compression** at L4 | — (observational) | Compression ratio per stage |

The problem characterization (three structural invariants, single-invariant insufficiency) is a **logical argument** in the paper — no experiment needed.

---

## Core Hypothesis

**Structured encoding of heterogeneous knowledge enables an LLM to discover cross-lever effects that it misses when the same information is presented as plain text.**

This experiment tests **encoding quality**, not retrieval. All levels receive the same complete information. The independent variable is *representation*. L1 = "everything retrieved, nothing structured"; L4 = "everything retrieved, fully structured."

---

## E1: Encoding Layer Matters (Primary Experiment)

### Signal Chain

```
encoding → discovery → evaluation
```

That's it. **No pipeline between encoding and evaluation.** Diagnostic agents, causal synthesis, and quality gate are NOT in this path — they are tested separately in E3.

### Design

```
For each scenario (N ≥ 12, balanced across effect types):
    For each level in [L1, L4]:
        encoded_context = encode(scenario, level)
        findings = LLM(discovery_prompt + encoded_context)   # single direct call
        scores = rubric_match(findings, ground_truth)        # 3-vote majority judge
    repeat k=5 times per (scenario, level)
```

### Encoding Levels

Only **L1 and L4** are compared. L2/L3 may be included for a gradient plot in the paper but are not required for the primary hypothesis test.

| Level | Data | Knowledge | Playbook |
|-------|------|-----------|----------|
| **L1: Raw text** | CSV with column headers + raw rows. NO summary statistics, NO aggregations, NO correlations — just the table as a competent analyst would paste it | Policy sentences as flat prose | Playbook as flat prose |
| **L4: Full structured** | Statistical profiles (raw rows REMOVED) | Tiered constraint vectors + temporal belief objects (prose REMOVED) | Process graph + rule catalog (prose REMOVED) |

**Why this is the contribution, not a flaw:** LLMs cannot reliably compute subgroup means, detrend time series, or check constraint thresholds by scanning raw numbers. The encoding layer pre-computes these statistics using deterministic code, then delivers the results to the LLM in its context window. The LLM still does all the reasoning — pattern recognition, cross-source conflict detection, causal inference — but over pre-computed statistical summaries instead of raw rows. This is the paper's thesis: offloading numerical computation to code and giving the LLM structured results to reason over outperforms giving it raw data and hoping it does the math. The paper must frame this explicitly.

**L4 character count must be within [0.7×, 1.5×] of L1.** Encoding REPLACES raw content, never appends to it. Same LLM model for both levels.

### Planted Effects

Each scenario has **3 ground-truth effects**, drawn from these encoding-sensitive categories:

- **Simpson's paradox** — Aggregate correlation tells one story; segment-level tells the opposite. Use ≥3 subgroups. **Construction requirements (MANDATORY):** Groups must overlap heavily in the raw data — inter-group mean separation must be ≤1× within-group standard deviation (i.e., `x_spread ≤ x_std`). Group x-means must be placed non-monotonically (not a visible gradient). Noise must partially mask the within-group slope (`noise_std ≥ 0.6 × |within_slope × x_std|`). At 500+ rows, an LLM scanning raw values cannot reliably compute per-subgroup means; L4 hands them pre-computed. If groups are non-overlapping or arranged on a monotone staircase, the paradox is trivially visible from raw CSV and the experiment stops testing encoding.
- **Constraint-boundary** — Data says go; a multi-condition constraint says stop. The constraint must be compound — at minimum two conditions joined by AND (e.g., "promotional depth > 30% is prohibited when store_tier = Premium AND quarter ∈ {Q3, Q4} AND base_price < 5.00"). At L1, this is buried in 10+ prose sentences requiring multi-hop parsing. At L4, it is a typed constraint vector with all conditions explicit and each threshold directly comparable against the statistical profile. **Single-condition constraints must not be used** — a simple threshold like "discount ≤ 30%" can be found in prose without structured encoding.

These two types had the highest detection rates in prior runs. Agents MAY add effect types if they can demonstrate ≥30% detection at L1 and ≥60% detection at L4 in the pilot. Do NOT add effect types that achieve 0% detection — they structurally cap recall.

**Distractor patterns (MANDATORY):** Each scenario must include ≥2 real-but-non-planted statistical patterns (e.g., genuine correlations, seasonal trends, outlier clusters) that are NOT ground-truth effects. This prevents the LLM from trivially finding "the only 3 interesting things" in clean data and tests whether encoding helps distinguish signal from noise.

**Scenario variation (MANDATORY):** Scenarios must vary structurally — different column sets, different numbers of subgroups, different constraint types, different lever combinations. A set of 12 scenarios with identical column structure and different numbers is pseudo-replication, not independent samples.

**Minimum lever count (MANDATORY):** Each scenario must include **≥ 5 lever columns** covering at least 3 of the 5 RGM domains (pricing, promotion, assortment, distribution, pack-price architecture). At least 4 scenarios must include levers from **all 5 domains**. With 5 levers, there are $C(5,2)=10$ lever pairs; with 8 levers, $C(8,2)=28$ pairs. This creates a combinatorial space large enough that exhaustive enumeration is impractical and the pipeline's compression is genuinely useful.

**Segment depth (MANDATORY):** Each scenario must include **≥ 2 categorical grouping variables** (e.g., store_tier AND region, or channel AND brand_tier). This creates cross-segment interactions (e.g., Simpson's paradox in one grouping but not another) and a combinatorial segment space that scales multiplicatively. With 2 grouping variables of 3 and 4 levels respectively, the segment space is 12 — not 3.

### Discovery Prompt (Category-Blind)

The LLM must report **3–5** high-confidence findings as **effect descriptions** (not intervention recommendations). Each finding must include: the specific effect, exact columns involved, direction/magnitude, scope/segment, and mechanism.

**Do NOT name effect categories** (no "look for Simpson's paradox"). Do NOT ask for "all" findings — constrain to the strongest 3–5.

### Rubric Matching

For each (finding, GT-effect) pair, the LLM judge scores 5 dimensions (0/1 each):

| Dimension | 1 if... |
|-----------|---------|
| **Variables** | Correct columns identified |
| **Direction** | Correct direction of effect |
| **Scope** | Correct subgroup/segment/conditioning variable |
| **Mechanism** | Describes why the effect arises |
| **Quantification** | Provides an approximate magnitude, ratio, or threshold value (e.g., within-group vs aggregate direction reversal ratio, constraint threshold value, effect size estimate). Accept any reasonable numeric estimate — exact values not required, but pure qualitative descriptions score 0. |

This 5th dimension is the key discriminator: L4 hands the LLM pre-computed statistics and explicit threshold values; L1 leaves all quantification to the LLM's unreliable mental arithmetic over raw rows.

**Pre-registered match threshold: score ≥ 3/5.** This threshold is fixed before any data is generated. Do not adjust after seeing results. Run each judgment **3 times**; for each dimension, accept 1 only if ≥2/3 votes agree. Report Krippendorff's alpha — if α < 0.40 for any dimension, revise the judge prompt.

**Vocabulary normalization:** The judge prompt must include: "The finding and ground truth describe the same dataset. Accept any reasonable synonym or business-domain equivalent for dataset column names (e.g., 'pricing' for base_price, 'volume' for units_sold). Focus on whether the same statistical phenomenon is described, not whether identical terms are used."

### Metrics

- **Primary: Mean Best Rubric Score (MBRS)** — For each GT effect, take the highest rubric score (0.0–1.0) achieved by any of the **top-3 ranked findings** (by LLM confidence order). Do NOT consider findings ranked 4th or 5th — rank-5 lucky guesses should not inflate MBRS and mask encoding differences. Average across all GT effects in a scenario. Paired t-test on MBRS, L4 vs L1, report Cohen's d and 95% CI.
- **Secondary**: F1 at pre-registered threshold (≥3/5), effect-type coverage, mean rubric score across matched pairs.
- **Report F1 at multiple thresholds** (≥3/5 and ≥4/5) as sensitivity analysis.

### Phases

**Phase 1 — Pilot (2 scenarios, L1 vs L4 only):**
- HARD GATE: `recall_l4 − recall_l1 ≥ 0.20`, `recall_l1 ≤ 0.35`, `recall_l4 ≥ 0.55`, encoding hashes differ, L4 chars within [0.7×, 1.5×] of L1
- If any gate fails: STOP, diagnose, create REVISE task. Do NOT proceed.

**Phase 2 — Full (N ≥ 12 scenarios, k=5 runs each):**
- HARD GATE: L4 mean MBRS > L1 mean MBRS with p < 0.05
- If gate fails: flag `DESIGN_INVALID`, do NOT proceed to paper

**Phase 3 — Paper + Webapp (only after Phase 2 passes)**

---

## E2: Cross-Source Reasoning

Same scenarios as E1. Run at L4 only, two conditions:

| Condition | Knowledge included |
|-----------|--------------------|
| **All-sources** | Data + policies + expert beliefs + playbook |
| **Data-only** | Data only |

Same discovery prompt, same rubric matching, same finding count (3–5), k=5 runs.

**GT effect design for E2:** Each scenario should contain at least 1 GT effect discoverable from data alone (e.g., Simpson's paradox) AND at least 1 GT effect requiring cross-source information (e.g., constraint-boundary). This way data-only can still find the data-only effects (control) while missing the cross-source effects (treatment).

**Metric**: MBRS computed separately for (a) data-only GT effects and (b) cross-source GT effects. The hypothesis is that cross-source MBRS is significantly higher with all-sources than data-only, while data-only MBRS is comparable across both conditions (control).

---

## E3: Pipeline Compresses Space

Run the **full pipeline** (diagnostic agents → causal synthesis → quality gate) on all scenarios at L4. This is **separate from E1/E2** — the pipeline is not in the E1 evaluation path.

### Why This Must Be Adaptive

The abstract claims the framework is an **alternative to classical optimization** for navigating unknown coupled decision spaces. In a real use case, you don't know the dimensionality upfront — you don't know how many lever interactions exist, how many constraints bind, or how many segments matter. The pipeline must **discover** the structure of the space, not enumerate a fixed number of pre-allocated slots.

**Why dimensionality matters for E3:** With 3 levers and 1 grouping variable, the naive space is ~150 — trivially enumerable. The pipeline adds no value over brute force. With 5–8 levers and 2+ grouping variables, the naive space is 2,000–10,000+. Now the pipeline's ability to focus on the relevant subspace is the core value proposition. E3 only convincingly demonstrates compression if the input space is large enough that compression matters.

**HARD RULE: No fixed candidate quotas.** Diagnostic agents must NOT be told "generate exactly N signals." Instead, each agent explores the encoded context and reports **all signals it finds above a minimum confidence threshold** (e.g., confidence ≥ 0.3). The number of Stage 1 signals is an **emergent property** of the data complexity, not a design parameter.

### Measuring Real Compression

The input to Stage 1 is not "however many signals the agents produce" — it is the **theoretical combinatorial space** that the pipeline avoids having to enumerate. Compute the naive space size for each scenario:

```
naive_space = C(n_levers, 2) × n_segments × n_knowledge_sources
```

where `n_levers` = number of lever columns, `n_segments` = product of unique values across categorical columns (capped at a reasonable bound like 200), and `n_knowledge_sources` = number of distinct knowledge items (policies + beliefs). This is the space a brute-force approach would need to scan.

Report **two compression metrics**:
1. **Pipeline compression**: Stage 1 output → Stage 3 output (what the pipeline actually does)
2. **Effective compression**: naive_space → Stage 3 output (what the user avoids by using the framework instead of exhaustive search)

The effective compression is what matters for the "alternative to optimization" claim.

### Protocol

```
For each scenario at L4:
    encoded_context = encode(scenario, L4)

    # Stage 1: Adaptive discovery (no fixed quotas)
    for each diagnostic agent (≥ 2, complementary dimensions):
        signals = agent(encoded_context)   # returns ALL signals above confidence threshold
        # Agent decides how many to report based on what it finds

    stage1_count = total unique signals across all agents
    naive_space  = computed from scenario metadata

    # Stage 2: Causal synthesis
    interventions = synthesize(all_stage1_signals)  # merge, deduplicate, structure
    stage2_count = len(interventions)

    # Stage 3: Quality gate (5 dimensions)
    final = quality_gate(interventions)    # NO hard cap on output count
    stage3_count = len(final)
```

**HARD RULE: No MAX_STAGE3 cap.** The quality gate filters by score threshold only. If 15 candidates pass the gate, report 15. If 2 pass, report 2. The output count must be an empirical result, not a design parameter.

Report per stage:
1. Number of candidate signals entering (emergent, not fixed)
2. Number surviving each stage
3. Pipeline compression ratio (stage1 / stage3)
4. Effective compression ratio (naive_space / stage3)
5. Naive space size and how it was computed

Quality gate must score all 5 abstract-claimed dimensions: evidence density, constraint alignment, actionability, testability, novelty. Log scores in `output/pipeline_scores.json`.

**Metric**: Median effective compression ≥ 100× (naive space to final output). With ≥ 5 levers and ≥ 2 grouping variables, the naive space should be ≥ 2,000 per scenario. Pipeline compression ratio is secondary — it only measures internal efficiency, not the framework's value proposition vs. exhaustive search.

**Diagnostic agent structure for high-dimensional scenarios:** With 5+ levers, diagnostic agents should partition their exploration along the lever-pair space — not just apply different analytical methods to the same small set of variables. One agent might focus on pricing×promotion interactions, another on assortment×distribution. The partition strategy is an agent decision, but the agents must report **which subspaces they explored** (log lever pairs examined) so the paper can show coverage of the combinatorial space.

---

## Hard Rules

1. **Same model for all levels.** If L1 context is too long, reduce row count — never switch models.
2. **Never truncate context.** Reduce N instead.
3. **Never name effect categories in discovery prompts.** Category-blind only.
4. **Encoding replaces, never appends.** L4 chars within [0.7×, 1.5×] of L1.
5. **Single entry point:** `run_experiments.py`.
6. **All LLM calls via** `copilot -p "<prompt>" -s --no-color --allow-all`. Cache by prompt hash. Record model in `results.json`.
7. **Ground truth never loaded by the reasoning system.** Used only for evaluation.
8. **Minimum 500 rows per scenario.** Do NOT drop below 500 rows — this is the floor that creates the numerical computation gap where encoding matters. If L1 context length becomes a problem, reduce *column count* or trim *text knowledge length*, never row count. At 150 rows or fewer, modern LLMs can scan the entire table and the encoding advantage disappears.

---

## What Agents Decide

Agents own all implementation decisions not specified above:

- Scenario count (≥12), rows per scenario, store/SKU/lever counts
- Exact encoding representations (statistical profiles, constraint vectors, belief objects)
- Number and specialization of diagnostic agents for E3 (≥2 parallel, complementary dimensions). Each agent must use a **confidence threshold** (not a fixed count) to determine how many signals to report
- Causal synthesis output schema (must include lever, direction, scope, mechanism)
- Quality gate scoring weights and threshold (but NO hard cap on output count — the gate filters by score only)
- Whether to include L2/L3 in the paper (optional gradient plot)
- Whether to add effect types beyond Simpson's + constraint-boundary (must pass detection pilot first)
- Paper structure, related work, figure design
- Webapp layout

---

## Success Criteria

| ID | Criterion | How measured |
|----|-----------|-------------|
| **SC1** | L4 > L1 on MBRS | p < 0.05, paired t-test, k=5 × N≥12 |
| **SC2** | All-sources > data-only on cross-source MBRS at L4 | Paired test, positive difference |
| **SC3** | Effective compression ≥ 100× (naive space → final output); pipeline has no fixed candidate quotas | Median ratio across scenarios; verify Stage 1 counts vary across scenarios |
| **SC4** | Three invariants formally defined + single-invariant insufficiency shown | Logical argument in paper |
| **SC5** | Paper compiles, figures from actual data, all abstract claims substantiated | Compilation + review |
| **SC6** | All claims backed by effect sizes and CIs | Statistical reporting |
| **SC7** | Pipeline architecture matches abstract (≥2 agents, synthesis tuples, 5-dim gate) | `pipeline_scores.json` |

---

## Deliverables

```
demos/coupled-decisions/
  output/
    results.json            # Per-scenario per-level per-run metrics + aggregate + model key
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

---

## Cleanup

When complete: delete all agent branches (local + remote), remove worktrees, prune, kill tmux sessions. `.llm_cache/` may be preserved.
