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

## Your Mission

Design, build, experimentally validate, and write up a system that fulfils the abstract's three contributions. You own the entire research pipeline — from problem formalization through synthetic-data generation, system architecture, experimental design, analysis, and paper writing.

**What is fixed** (the intellectual commitments from the abstract):
1. The problem is characterized by three structural invariants — lever coupling, knowledge heterogeneity, and the cognitive assembly bottleneck
2. The solution has a multimodal encoding layer that preserves epistemic differences across knowledge types
3. The solution has a progressive space-reduction pipeline with parallel diagnosis → causal synthesis → quality gating
4. The primary instantiation domain is Revenue Growth Management
5. The paper should briefly discuss cross-domain applicability (but this is secondary to encoding and pipeline validation)

**What is yours to decide** (these are the research and engineering contributions):

- The formal definitions of the three invariants and proof that addressing them in isolation is insufficient
- The specific encoding representations (the abstract suggests statistical profiles, constraint vectors, and temporal belief objects — but the exact design is yours)
- The number, specialization, and interaction pattern of reasoning agents
- The dimensions along which diagnostic agents prune the space
- The causal synthesis mechanism
- The quality gate's dimensions and scoring
- The experimental design that convincingly validates each claim
- The synthetic data scenarios — what effects to plant, how many, what makes them hard
- The cross-domain discussion (optionally sketch 1–2 other domains — precision medicine, materials discovery, supply chain, financial risk, or others — but keep it brief)
- The paper's narrative arc and how to present the results compellingly

---

## Playbook Architecture — The Core Complexity

The system must reason over a **decision playbook**: a structured collection of question types, each with its own multi-step process, governed by overlapping rules and shared analytical techniques. The playbook itself is a form of heterogeneous knowledge that must be encoded and reasoned over — distinct from (and interacting with) the quantitative data, policy documents, and expert judgment already described in the abstract.

### Question Taxonomy

Real decision-support work involves fundamentally different types of questions, not just one. The synthetic scenario must include **at least 6 distinct question types** that an analyst would pose against the decision space:

| Type | Description | Example | Typical Steps |
|------|-------------|---------|---------------|
| **What-If (Scenario)** | Simulate impact of hypothetical lever changes | "What if we raise price 5% in urban stores next quarter?" | 3–4 |
| **Root-Cause (Diagnostic)** | Explain observed metric changes | "Why did margin decline 8% in Q3 despite higher volume?" | 3–4 |
| **Optimization** | Find the best lever configuration given constraints | "Optimal price-pack architecture for the premium segment?" | 4–5 |
| **Sensitivity** | Map how outcomes depend on lever intensity | "How sensitive is revenue to promotion depth across segments?" | 2–3 |
| **Trade-Off** | Evaluate competing objectives along a frontier | "Distribution reach vs. assortment depth — where's the sweet spot?" | 2–3 |
| **Compliance (Feasibility)** | Check whether a plan satisfies all hard constraints | "Does Plan X violate any pricing or distribution rules?" | 2 |

You may add additional question types (comparison, forecasting, anomaly detection) if they strengthen the paper.

### Processes, Rules, and Techniques — The Three Overlapping Layers

Each question type has a **process** — an ordered sequence of analytical steps. Each step invokes one or more **techniques** (analytical methods) and is governed by one or more **rules** (constraints on valid execution). These three layers overlap extensively:

**Processes vary in length.** A compliance check may be 2 steps; an optimization may be 5. The system must select and execute the correct process for each question.

**Rules overlap across question types.** For example:
- "Maximum price increase of 10% per quarter" governs what-if scenarios, optimization, AND compliance checks
- "Minimum 70% distribution coverage" constrains optimization, trade-off analysis, AND compliance
- "Seasonal adjustment required for summer months" applies to what-if, sensitivity, AND root-cause questions
- A rule may be a **hard constraint** in one question type (compliance) but a **soft advisory** in another (what-if exploration)

**Techniques are shared.** For example:
- Elasticity estimation appears in what-if, optimization, AND sensitivity processes
- Constraint satisfaction is used in optimization, trade-off, AND compliance processes
- Metric decomposition trees are used in root-cause AND what-if processes
- Cross-lever interaction modeling appears in what-if, optimization, AND trade-off processes

**Step outputs feed across question types.** Answering a root-cause question may require first running a what-if counterfactual. An optimization may depend on a sensitivity analysis. These **cross-question chains** create implicit dependencies that the system must discover and honor.

### Why This Matters for the Paper

The playbook structure introduces a fourth structural complexity beyond the three invariants in the abstract: the **process selection and composition bottleneck**. Even with perfect encoding and perfect cross-source reasoning, a system that applies the wrong process — or applies the right process but misses a shared rule — will produce incorrect answers. This is where the cognitive assembly bottleneck manifests most acutely in practice: human analysts carry the playbook in their heads and silently apply shared rules from memory.

The synthetic data, the encoding layer, and the pipeline must all account for this playbook structure. The experiments must demonstrate that the system selects the correct process, applies shared rules across question types, reuses techniques appropriately, and follows cross-question chains.

---

## Research Quality Standards

This is a paper, not a software demo. Every section must meet academic standards:

### Problem Characterization (Contribution 1)
- Formally define each structural invariant with mathematical precision
- Prove (constructively or by counterexample) that approaches addressing any single invariant in isolation are incomplete — this is a core theoretical claim
- Survey existing approaches and show where each falls short against the three invariants (this becomes your Related Work)
- The characterization must be domain-independent; the invariants should be recognizable in any coupled-decision domain

### Encoding Layer (Contribution 2)
- Design representations for each knowledge type that are machine-readable yet preserve native semantics
- **The encoding layer must handle four knowledge types** — not three: quantitative data, policy documents, expert judgment, AND the playbook itself (process definitions, rule catalog, technique library). The playbook is a distinct knowledge type with its own encoding challenges: it contains procedural logic (sequences of steps), context-dependent constraints (rule strictness varies by question type), and structural relationships (technique sharing, cross-question dependencies).
- The key insight to validate: conflicts between knowledge sources become *diagnostic signals* rather than noise. This applies equally to playbook conflicts — e.g., a rule that contradicts expert judgment, or a process step that assumes an input the data doesn't support.
- **Head-to-head baseline — naive RAG**: The strongest skeptic objection is "why not just paste everything into an LLM prompt?" The baseline must represent what a competent practitioner would actually do today: take a data sample AND all available knowledge (rules, expert opinions, playbook), serialize everything as plain text, stuff it into the context window, and query. This is "naive RAG" — and it's a strong baseline because the LLM sees ALL the same information, just without structured encoding. You MUST include this baseline. If your encoding doesn't clearly win against naive RAG, the contribution is not established.
- **Critical constraint — same sample size across ALL levels**: Every encoding level receives the SAME number of data rows (recommend N=500, minimum N=200). The experimental variable is ENCODING QUALITY, not data quantity. Using different row counts per level (e.g., 30 rows for raw table, 500 for structured encoding) is a confound that invalidates the comparison.
- **Critical constraint — all levels include ALL knowledge sources**: Every encoding level receives data AND policies AND beliefs AND playbook — the difference is HOW they are encoded, not WHICH sources are included. A baseline that only sees data while the full system sees data+policies+beliefs+playbook is testing knowledge availability, not encoding quality. The cross-source experiment (a separate experiment) tests knowledge availability.
- **Encoding ablation ladder**: Test at least these representation strategies, all using the same LLM, same prompt structure, same data sample, and same knowledge sources:
  1. *Naive RAG* — ALL knowledge sources as plain text. Data as a flat markdown table of N rows (no statistical pre-computation — no correlations, no regressions, no segment splits, no distribution summaries). Policies as a bullet list of rule statements. Expert beliefs as paragraphs. Playbook as prose narrative. The LLM must do ALL analytical reasoning from raw numbers.
  2. *Statistical pre-computation* — Data replaced with statistical profiles (distributions, cross-lever correlations, temporal patterns, sub-population splits, anomaly flags — computed in Python via numpy/scipy). All other knowledge sources still as unstructured text. This isolates the value of Python-computed analytics.
  3. *Type-aware knowledge encoding* — Statistical profiles PLUS typed constraint vectors (with scope and strictness per question type) PLUS temporal belief objects (with confidence, recency, decay). Playbook still as unstructured text. This isolates the value of epistemic typing.
  4. *Full structured encoding* — Statistical profiles + typed constraints + temporal beliefs + structured playbook (process graphs, typed rule catalog, technique registry with cross-question dependencies). This is the complete system.
- For each level, measure: (a) discovery precision/recall of planted cross-lever effects, (b) frequency of hallucinated or spurious effects, (c) ability to detect conflicts between knowledge sources, (d) quality of causal mechanism explanations, **(e) process selection accuracy on the query set, (f) rule overlap correctness**
- Report pairwise effect sizes (Cohen's d or equivalent) with 95% CIs between each adjacent rung and between naive-RAG vs full-encoding
- **The planted effects must be DESIGNED so that naive RAG genuinely struggles.** Mere correlation-based coupling effects are NOT sufficient — Python pre-computes correlations, so any effect Pearson's r can find will be trivially surfaced at Level 2+. Instead, plant effects that are genuinely misleading in raw rows. Required categories:
  - **Simpson's paradox** (≥2 scenarios): Aggregate correlation tells one story; segment-level analysis tells the opposite. Raw rows mislead; statistical profiles with sub-population splits resolve correctly.
  - **Confounded coupling** (≥1 scenario): Two levers appear correlated in raw data due to a shared temporal confound (e.g., both spike in summer). Temporal detrending in the statistical profile removes the spurious correlation. Raw rows present it as real.
  - **Constraint-boundary effect** (≥2 scenarios): A lever combination looks attractive in the data but violates a hard constraint. As typed constraint vectors with scope and strictness, the violation is flagged. As a bullet in a long text list, the LLM is likely to miss or misweight it.
  - **Decayed belief trap** (≥1 scenario): An expert belief was true historically but the data has structurally shifted. Only detectable when the belief has explicit temporal metadata (date, decay function) AND the statistical profile shows a trend break. As unstructured text, both signals are buried.
  - **Nonlinear segment interaction** (≥1 scenario): Two levers interact but only in a sub-population. Linear Pearson correlation across all rows shows nothing. Segment-aware statistics surface it.
- Show that collapsing knowledge types into a single representation (e.g., converting everything to text, or everything to numbers) loses critical information — this is implicitly tested by comparing Level 1 (everything as text) vs. Levels 3–4 (typed encoding)
- **Show that encoding the playbook as structured data (process graphs, typed rules) outperforms providing it as unstructured text** — this is the Level 3 vs. Level 4 gap

### Progressive Pipeline (Contribution 3)
- The pipeline must demonstrably compress a combinatorial space by orders of magnitude
- Each stage must be independently evaluable — you should be able to measure what each stage contributes
- Final outputs should be structured interventions (not just "raise price") — specify lever, direction, magnitude, scope, mechanism, and supporting evidence

### Experimental Validation
Design experiments that are *genuinely convincing* to a skeptical reviewer. At minimum:

- **Ablation**: Remove each major component and show degradation. The full system must meaningfully outperform every ablated variant
- **Encoding fidelity (primary experiment)**: Run the full encoding ablation ladder (naive RAG → statistical pre-computation → type-aware encoding → full structured encoding) on identical synthetic scenarios WITH identical sample sizes and identical knowledge source availability. This is the paper's most critical experiment — allocate the most scenarios and the most careful analysis here. The full encoding must statistically significantly outperform naive RAG on at least precision, recall, and hallucination rate. Use ≥8 scenarios per condition to ensure adequate statistical power (target 0.80 power to detect d=1.0 effects).
- **Cross-source reasoning** (separate from encoding ablation): Using the FULL encoding for all conditions, vary which knowledge sources are INCLUDED: (a) data-only, (b) data+policies, (c) data+policies+beliefs, (d) all sources. This experiment tests knowledge availability, not encoding quality — so ALL included sources use their best encoding. Plant at least 3 effects that are INVISIBLE in data alone and require policy knowledge, expert beliefs, or playbook structure to discover (e.g., an effect that the data supports but a hard constraint prohibits, or a pattern that only makes sense when combined with expert domain context that is not deducible from numbers). If data-only achieves the same discovery rate as all-sources, the effects are too easy and must be redesigned.
- **Space reduction**: Quantify compression at each pipeline stage
- **Playbook-driven reasoning** *(new, critical)*: Show that the system correctly handles the playbook complexity:
  - **Process selection accuracy**: Given a diverse question set spanning all question types, measure whether the system selects the correct process for each question. Report accuracy and confusion matrix across question types.
  - **Rule overlap handling**: Show that shared rules are correctly applied across question types. Plant at least 3 scenarios where a rule that is "hard" in one question type but "soft" in another produces different answers — the system must respect the context-dependent rule semantics.
  - **Technique reuse**: Show that the system correctly reuses analytical techniques across question types rather than re-deriving results (e.g., an elasticity estimate computed during a sensitivity question should be available and consistent when answering a subsequent what-if question on the same lever).
  - **Cross-question chains**: Measure performance on questions that require output from a prior question of a different type. Compare: (a) answering in correct dependency order vs. (b) answering each question in isolation. The chained approach must outperform.
  - **Process length robustness**: Show that the system handles both short (2-step compliance check) and long (5-step optimization) processes without truncating steps or hallucinating extra ones.
- **Generalization** *(secondary, brief)*: Sketch applicability to 1–2 additional domains to show the architecture is not RGM-specific, but keep this concise — a short qualitative discussion is sufficient. Do not invest significant experimental effort here.

For all experiments: report effect sizes, confidence intervals, and statistical tests. Negative or weak results must be reported honestly.

### Synthetic Data

You must generate your own synthetic data with *planted ground truth* so you can rigorously measure discovery performance. The synthetic data has **four layers** — transactional data, knowledge sources, the playbook itself, and a query set — each with its own realism requirements.

#### Layer 1: Transactional Data

Generate datasets that mimic the volume and granularity of real enterprise data:

- **Transaction-level data**: ≥100,000 rows per scenario (e.g., weekly store×SKU observations across 50+ stores, 200+ SKUs, 2+ years)
- **Multiple scenarios**: At least 8–10 distinct synthetic scenarios, each with different planted effects, coupling structures, and noise profiles
- **High dimensionality**: Each scenario should include ≥15 decision levers/features with realistic covariance structure
- The sample sizes must be large enough that statistical tests have adequate power (≥0.8) to detect the planted effects at their true magnitudes
- **Same-sample rule**: When the same scenario is used across encoding levels, every level must receive the same data sample (same rows, same N). Use N=500 as default. This prevents confounding encoding quality with data quantity.
- Reproduce real-world distributional shapes: skewed revenue distributions, fat-tailed promotional lifts, zero-inflated sparse assortment matrices
- Include temporal structure: seasonality (weekly, monthly, annual cycles), trend, promotional calendar effects, holiday spikes
- Inject realistic noise: measurement error, reporting lags, missing data (MCAR, MAR, and MNAR patterns at 5–15% rates), outliers, and data entry errors
- Model realistic confounders: price–promotion correlation, store-size effects, geographic clustering, brand-level halo effects
- Include heterogeneous sub-populations (e.g., urban vs. rural stores, premium vs. value segments) with different response functions

#### Layer 2: Knowledge Sources

Generate companion knowledge artifacts with realistic imperfection:

- **Policy documents** (15+ rules): Mix of hard constraints ("never exceed 10% price increase per quarter"), soft guidelines ("prefer promotional bundling in Q4"), and conditional rules ("if store is premium tier, minimum assortment width is 40 SKUs"). Each rule must have a defined scope (which question types it governs) and a strictness level that varies by context.
- **Expert judgment** (15–20 beliefs): Mix of correct, outdated, conditionally-true, and flat-wrong beliefs with confidence scores. Include temporal decay (beliefs that were true 2 years ago but no longer hold). Include at least 3 experts with systematically different biases (e.g., one overestimates promotion impact, another undervalues distribution).
- **Ambiguity and contradiction**: At least 5 cases where policy and expert judgment conflict (e.g., policy says "no price increases in rural stores" but expert says "rural stores can absorb 3% increases"). At least 2 cases where experts contradict each other.

#### Layer 3: The Playbook

Generate a structured decision playbook as machine-readable knowledge:

- **Process definitions**: For each of the 6+ question types, define an ordered list of steps. Each step specifies: (a) what technique(s) it uses, (b) what rule(s) govern it, (c) what inputs it requires, (d) what outputs it produces. Processes must vary in length (2 to 5 steps).
- **Rule catalog** (20+ rules): Each rule has: (a) a unique ID, (b) a natural-language statement, (c) a formal condition, (d) a list of question types it applies to, (e) a strictness level per question type (hard/soft/advisory). At least **8 rules must apply to 2+ question types** (this is the overlap). At least **3 rules must change strictness depending on question type** (hard in compliance, soft in what-if).
- **Technique library** (10+ techniques): Each technique has: (a) a unique ID, (b) a description, (c) required inputs, (d) outputs, (e) a list of process steps that invoke it. At least **5 techniques must appear in 2+ question types** (this is the sharing).
- **Cross-question dependencies**: Explicitly define at least 3 question chains where one question's output is another question's required input (e.g., "before optimizing pack-price architecture, you must run a sensitivity analysis on price elasticity by segment").

#### Layer 4: Query Set

Generate a diverse set of **30–50 questions** that exercise the playbook:

- **Coverage**: At least 4 questions per question type, spread across easy/medium/hard difficulty
- **Ground-truth traces**: For each question, record the correct answer AND the full answer trace: which process was selected, which steps were executed, which rules were applied, which techniques were used, and which cross-question dependencies (if any) were followed
- **Planted traps** — at least 5 questions where the correct answer requires handling playbook complexity:
  1. **Wrong-process trap**: A question that superficially resembles one type but is actually another (e.g., "Why is Plan X underperforming?" looks like root-cause but is actually a compliance failure — wrong process gives wrong diagnosis)
  2. **Missing shared-rule trap**: A what-if question where the correct answer depends on a pricing constraint usually encountered in compliance checks — an agent that only loads what-if rules will miss it
  3. **Technique-reuse trap**: Two questions that share a technique (e.g., elasticity estimation) but with different scoping — the system must adapt the technique's output, not blindly reuse it
  4. **Cross-chain trap**: A question that can only be answered correctly if a prior question of a different type was answered first — answering in isolation produces a subtly wrong result
  5. **Context-dependent strictness trap**: A question where a rule that is "soft" in this question type is erroneously treated as "hard" (or vice versa), leading to an overly conservative or overly aggressive answer
- **Difficulty gradient**: Easy questions (single process, no rule overlap, no chains) through hard questions (multi-process, extensive rule overlap, multi-step chains, conflicting knowledge sources)

#### Cross-Cutting Data Requirements

- **Encoding-sensitive**: Include effects that are genuinely misleading when presented as raw rows but correctly interpretable with statistical pre-computation (Simpson's paradox, confounders, nonlinear segment interactions). If an effect is trivially discoverable from a random sample of raw rows, it does not test the encoding hypothesis.
- **Cross-source-sensitive**: Include effects that are invisible in data alone and require policy knowledge, expert beliefs, or playbook structure to discover. If data-only analysis finds everything, the cross-source hypothesis is untested.
- **Challenging**: Include effects that require cross-lever, cross-source, AND cross-question-type reasoning to discover
- **Measurable**: Every planted effect has a known ground-truth magnitude. Every planted trap has a known correct answer trace. You can compute precision/recall for both effect discovery and process correctness.
- **Non-trivial**: A naive approach — analyzing each lever independently OR applying a generic one-size-fits-all process to all question types — must fail on at least some questions. This is how you prove that both coupling AND playbook structure matter.

Keep the ground-truth specification (answer key + traces) completely separate from the reasoning system. The system must never see the answer key.

### Paper Writing

The paper follows standard academic conventions (LaTeX, proper bibliography, figures from real data, honest limitations). One non-standard requirement: the Experimental Setup section MUST name the exact LLM model used (from the model identification query below).

---

## Technical Constraints

- Python 3.11+
- Only stdlib + matplotlib + numpy + scipy (no ML frameworks, no pip install openai/anthropic)
- **Copilot CLI is mandatory** for ALL reasoning, analysis, synthesis, and evaluation: `copilot -p "<prompt>" -s --no-color --allow-all`. Every component that performs judgment, interpretation, or inference MUST route through the LLM — there is NO heuristic fallback, NO rule-based shortcut, and NO hard-coded scoring logic anywhere in the pipeline. Specifically:
  - Diagnostic agents MUST use LLM calls to analyze data and generate findings — not statistical heuristics or threshold-based rules
  - Causal synthesis MUST use LLM reasoning to assemble evidence into interventions — not template filling or pattern matching
  - Quality gating MUST use LLM evaluation to score candidates — not weighted-sum heuristics or rule engines
  - Encoding evaluation and conflict detection MUST use LLM interpretation — not string matching or numeric comparisons
  - If `copilot` is not in PATH, the pipeline MUST fail immediately with a clear error message rather than silently degrading to heuristics
  - Any code path that makes a judgment call without an LLM invocation is a bug
- **Model identification is mandatory**: At startup, the pipeline MUST query `copilot -p "What model are you? Reply with only your model name and version." -s --no-color --allow-all`, parse the response, and record the model name (e.g., "GPT-4o", "Claude 3.5 Sonnet") in `results.json` under a top-level `"model"` key.
- All LLM calls cached in `demos/coupled-decisions/.llm_cache/` by prompt hash for reproducibility. First run hits the LLM; subsequent runs replay from cache.
- Full pipeline should complete in <60 minutes first run, <5 minutes from cache (increased budget to accommodate large-scale data generation and LLM-intensive evaluation)

---

## Deliverables

All output scoped under `demos/coupled-decisions/`. The framework handles `.swarm/` artifacts (deliverable, journal, belief map) automatically — do NOT duplicate those here.

**Demo-specific artifacts** (these are NOT standard framework output — agents must create them explicitly):

```
demos/coupled-decisions/
  output/
    results.json            # All experimental results + top-level "model" key
    validation_report.json  # Validation gate verdicts and audit trail
    index.html              # Interactive webapp (single HTML, Chart.js + D3.js via CDN)
    data/
      transactions/          # Layer 1: transactional data (CSV/parquet per scenario)
      knowledge/             # Layer 2: policy docs, expert beliefs (JSON/YAML)
      playbook/              # Layer 3: process definitions, rule catalog, technique library (JSON)
      queries/               # Layer 4: query set with ground-truth traces (JSON)
      ground_truth.json      # Answer key — NEVER loaded by reasoning system
  src/                      # Pipeline source code
  .llm_cache/               # LLM response cache (by prompt hash)
```

The paper (LaTeX source, compiled PDF, figures, tables, bibliography) goes under `output/paper/` — standard academic structure; agents know what to produce.

### Interactive Webapp
Single self-contained HTML file. Must include:
- Framework architecture visualization
- Interactive ablation comparison
- Pipeline compression visualization
- Results from all experiments
- Reads `results.json`, graceful fallback if missing

---

## Success Criteria

The paper succeeds if a skeptical reviewer would agree that:

1. **The problem characterization is rigorous** — the three invariants are formally defined and the incompleteness of partial approaches is demonstrated
2. **The encoding layer matters** — reasoning with structured encoding significantly outperforms naive RAG (same data + same knowledge, all as plain text). Specifically: structured statistical profiles outperform raw row dumps, typed constraint/belief encoding outperforms unstructured text, and structured playbook encoding outperforms playbook-as-prose.
3. **Cross-source reasoning works** — the system discovers effects that require synthesizing multiple knowledge types, and data-only analysis (even with full structured encoding) misses them. If data-only achieves the same performance as all-sources, the planted effects are too easy.
4. **The pipeline compresses effectively** — a combinatorial space is reduced by orders of magnitude to a tractable set of interventions with zero hard-constraint violations
5. **Ablation is convincing** — removing any major component produces measurable degradation
6. **Playbook-driven reasoning is correct** — the system selects the right process for each question type, applies shared rules with correct context-dependent strictness, reuses techniques across question types, and follows cross-question dependency chains. Process selection accuracy ≥80% on the full query set; a flat (single-process) baseline achieves ≤60%.
7. **Generalization is plausible** — a brief discussion argues the architecture applies beyond RGM, but deep multi-domain experiments are not required
8. **Results are validated** — all claims pass statistical audit, methodology critique, and adversarial review before appearing in the paper
9. **Limitations are honest** — the paper reports what didn't work, what was weak, and what assumptions might not hold

---

## Cleanup Requirements

When the demo run completes (whether successfully or not):
- Delete ALL local and remote agent branches (`agent-*` pattern)
- Remove ALL git worktrees created during the run; run `git worktree prune`
- Kill any tmux sessions/windows created for agents
- `.llm_cache/` MAY be preserved for reproducibility
- Verify: `git branch -a | grep agent` returns nothing, `git worktree list` shows only main worktree
