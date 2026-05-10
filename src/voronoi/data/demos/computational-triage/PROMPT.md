# Don't Ask the Solver to Build the Problem: Evidence Encoding for LLM Reasoning Over Constrained Decision Spaces

Produce a complete academic paper — with empirical evidence from controlled experiments — demonstrating that **evidence encoding** (transforming unstructured multi-source evidence into a solver-tractable representation before LLM inference) is a scaling axis for LLM reasoning, and that its benefits **amplify in multi-agent architectures**. The paper must be rigorous enough for a top-tier venue (NeurIPS, ICML, AAAI, Management Science).

---

## Abstract

> Large language models increasingly serve as reasoning engines over high-dimensional decision problems where heterogeneous evidence — quantitative data, policy constraints, and expert beliefs — must be integrated under combinatorial constraint structures. Raw-text prompting forces the model to simultaneously *construct* the constraint graph from unstructured evidence AND *search* for a solution — in a single forward pass. In classical constraint satisfaction, this conflation is catastrophically inefficient: no SAT solver searches without first running unit propagation, arc consistency, and nogood learning. We argue the same principle applies to LLM reasoning — the bottleneck is not model capability but evidence representation.
>
> We formalize **evidence encoding** — the transformation of unstructured evidence into a solver-tractable representation — and propose a three-stage Evidence Encoding Protocol (EEP): (1) signal encoding via statistical profiling replaces raw data with decision-relevant features (analogous to variable ordering), (2) constraint encoding vectorizes policy rules and annotates binding status (analogous to arc consistency), and (3) conflict encoding flags cross-source contradictions explicitly (analogous to nogood clause learning). Together, these stages constitute the same class of operations that make NP-hard constraint satisfaction problems tractable in practice — applied to LLM context.
>
> We validate this framework in two studies. **Study 1** is a pre-registered single-agent factorial ($N \geq 1{,}000$; $\geq 4$ models; six cumulative complexity levels; $\geq 36$ scenarios with known causal DAGs). It establishes six findings: (F1) evidence encoding explains $\geq 70\%$ of variance in reasoning accuracy, rivaling model identity; (F2) the advantage is consistent across complexity levels — no phase transition; (F3) weaker models benefit disproportionately; (F4) encoded representations achieve $\geq 90\%$ Pareto dominance at 38–257$\times$ token compression; (F5) the advantage does not scale with compression magnitude, implicating structural benefits beyond token reduction; (F6) the effect replicates internally and is confirmed non-parametrically.
>
> **Study 2** extends the framework to multi-agent architectures using a $2 \times 2 \times 6$ factorial (encoding $\times$ architecture $\times$ complexity; $N \geq 500$). Three agents independently analyze each scenario, and a synthesizer integrates their findings. Four additional findings emerge: (F7) multi-agent ensembles with encoded context outperform the best single agent with encoded context (amplification); (F8) encoding reduces inter-agent disagreement, producing more coherent ensemble inputs for synthesis; (F9) multi-agent benefit is larger under encoded context than raw text (encoding $\times$ architecture interaction); (F10) the multi-agent advantage increases with complexity — encoding enables ensemble gains precisely where single agents fail.
>
> Together, these results position evidence encoding as a third scaling axis — orthogonal to model scaling (better engine) and test-time compute (more thinking time). Evidence encoding improves the fuel, and multi-agent architectures multiply the return on that investment.

This abstract is the contract. Every claim made above must be substantiated with experimental evidence in the paper. Any finding that fails its statistical gate must be reported honestly — as a null, a trend, or a design limitation. Do NOT fabricate results to match the abstract.

---

## Paradigm Positioning

The paper MUST include a section (Introduction or Related Work) that positions evidence encoding in the progression of context-handling paradigms:

```
                      what changes    what's fixed     bottleneck addressed
─────────────────────────────────────────────────────────────────────────────
RAG era (2020–):      Retrieve →      Concatenate →    Reason
                      (relevant docs)  (raw text)      recall

CoT era (2022–):      Retrieve →      Concatenate →    Think step-by-step → Reason
                      (relevant docs)  (raw text)      reasoning depth

Encode era (this):    Retrieve →      ENCODE →         Reason
                      (relevant docs)  (structured)    evidence quality
─────────────────────────────────────────────────────────────────────────────
```

**The key insight:** RAG solved *what* to retrieve. CoT solved *how* to reason. Both accept raw context — neither asks whether the *representation* of that context is fit for reasoning. Evidence encoding addresses the missing link: the gap between retrieval and reasoning is not a reasoning gap, it is a *representation* gap. You do not need the model to think harder — you need to give it evidence it can think *with*.

CoT and encoding are **orthogonal axes**: CoT extends reasoning time (test-time compute), encoding transforms evidence quality. They compose — an agent can reason step-by-step over encoded evidence. The experiment holds CoT constant (same prompt) while varying only the evidence representation.

---

## Theoretical Framework: Evidence Encoding as CSP Compilation

The paper MUST include a theoretical section that connects evidence encoding to constraint satisfaction. This is not a metaphor — it is a structural equivalence.

**Core observation:** LLM reasoning over multi-source evidence is structurally equivalent to solving a constraint satisfaction problem (CSP) where the solver must simultaneously *construct the constraint graph* from unstructured text AND *search for a solution* — in a single forward pass. In classical CSP solving, this conflation is known to destroy tractability. The standard pipeline is: encode the problem (variable ordering, arc consistency, nogood learning), THEN solve. Our EEP stages are instances of this encoding:

| EEP Stage | Evidence operation | CSP encoding equivalent | What it eliminates |
|:----------|:-------------------|:-----------------------|:-------------------|
| 1. Signal encoding | Statistical profiles, ranked correlations | Variable ordering heuristic — rank variables by marginal impact | Forces attention to highest-signal dimensions first |
| 2. Constraint encoding | Typed vectors with binding status, cascading refs | Arc consistency / bound propagation — propagate bounds through constraint graph | Eliminates provably infeasible lever settings before the solver engages |
| 3. Conflict encoding | Explicit cross-source contradiction flags | Nogood clause learning — record which source combinations are inconsistent | Prunes branches that would lead to contradictions |

**The Darwiche connection:** Knowledge compilation (Darwiche & Marquis, 2002) transforms a propositional theory from one language (CNF) into another (OBDD, DNNF) to make downstream queries tractable. Evidence encoding performs the same operation in a new domain — transforming unstructured evidence into a representation that makes LLM reasoning tractable. The benefit comes from the *structural transformation*, not from compression.

**Why F2 (consistent advantage) follows from CSP theory:** The advantage is flat across complexity because encoding removes a *fixed overhead* — the cost of constructing the constraint model from unstructured text — rather than a complexity-dependent overhead. At low $K$, the search space is small but the LLM still wastes attention parsing raw data to discover constraint structure. At high $K$, the search space is huge but encoding is also more aggressive. The overhead is structural, so the benefit is consistent.

**Caveats:** LLM forward passes are not formally equivalent to CSP solvers. The mapping is structural (same *class* of operations, same *direction* of benefit) rather than formal. The $\eta^2_p$ result is consistent with CSP theory but not derived from it.

## How This Applies to Agents and Multi-Agent Systems

The paper MUST include a section that makes the agent connection explicit, grounded in empirical evidence from both studies. Structure the argument in three layers:

### Layer 1: Per-Call Quality (Study 1)

Every agent — whether it plans, retrieves, reasons, or acts — makes LLM calls. Each call processes context and produces output. Study 1 proves that *the quality of each individual call* improves dramatically under encoding ($\eta^2_p \geq 0.50$). This is the **atomic unit** of agent behavior. If the fuel is low-quality, no architecture compensates.

Practical implication: any agentic system (ReAct, Reflexion, AutoGPT, multi-agent swarms) that feeds evidence into LLM calls benefits from encoding that evidence first. The cost is deterministic (once); the benefit accrues at every call.

### Layer 2: Multi-Agent Coordination (Study 2)

Study 2 tests the simplest non-trivial multi-agent architecture: parallel analysts → synthesizer. This is the *minimal experimental unit* for multi-agent claims. We test whether:

- **Ensemble diversity emerges from stochastic reasoning** — same model, same prompt, same evidence, different reasoning paths
- **Encoded context creates a shared analytical vocabulary** — correlation coefficients, constraint IDs, belief objects — that makes synthesis tractable. Raw text produces findings in incomparable natural language, making synthesis an alignment problem on top of an integration problem
- **Multi-agent benefit is gated by evidence quality** — the encoding × architecture interaction tests whether multi-agent helps *only when* the context is structured enough for meaningful synthesis

### Layer 3: Implications for Agentic Architectures (Discussion)

Ground each claim in specific findings:

| Claim | Evidence | What it means for agents |
|-------|----------|-------------------------|
| Context quality > context quantity | F1: encoding explains $\geq 70\%$ of variance | Agent memory systems should encode stored knowledge, not just retrieve it |
| Encode once, use everywhere | F4: Pareto dominance | In a pipeline of N agents making M calls, encoding cost is O(1) while benefit is O(N×M) |
| Weaker agents gain most | F3: capability × encoding interaction | Cost-sensitive multi-agent swarms benefit disproportionately |
| Encoding enables synthesis | F8: inter-agent agreement under Encoded | Structured representations make agent outputs commensurable — synthesis becomes aggregation, not translation |
| Multi-agent scales with complexity | F10: architecture × complexity interaction | Encoding + multi-agent is most valuable precisely where it's most needed |

**Scope:** We test single-shot (parallel → synthesize), not iterative agents. We test 1 vs 3 agents, not ensemble size optimization. Encoding operates *after* retrieval — RAG + Encoding compose.

---

## Study 1: Single-Agent Factorial (Replication + Extension)

### Purpose

Reproduce and extend the six findings from the evidence encoding framework. This establishes the single-agent baseline (Conditions C and D) that Study 2 builds upon.

### Design: 2 × 6 × M Factorial

**A. Encoding** — 2 levels:

| Level | What the LLM receives |
|-------|----------------------|
| **Raw** | CSV with headers + ALL raw rows, policy as flat prose, expert opinions as prose. No pre-computation. |
| **Encoded** | Statistical profiles (raw rows removed), tiered constraint vectors with cross-references, temporal belief objects with confidence/decay/conflicts. Prose removed. |

Encoded replaces Raw, never appends. The natural compression is a feature — report Encoded/Raw token ratio per scenario.

**B. Knowledge Complexity ($K$)** — 6 cumulative levels:

| Level | Levers | Constraint depth | Sources | Planted conflicts | Rows |
|---|---|---|---|---|---|
| $K_1$ | 3 | 1-hop | 2 | 1 | 1000 |
| $K_2$ | 5 | 1-hop | 3 | 2 | 1500 |
| $K_3$ | 7 | 2-hop | 3 | 3 | 2500 |
| $K_4$ | 10 | 2-hop | 4 | 4 | 3500 |
| $K_5$ | 12 | 3-hop | 4 | 5 | 5000 |
| $K_6$ | 15 | 3-hop | 5 | 7 | 7000 |

Constraint depth = reasoning hops to detect a violation:
- **1-hop:** data says X, policy says not-X
- **2-hop:** data says X → triggers policy A → activates constraint B on lever Y
- **3-hop:** adds temporal dependency (action at $t$ creates constraint at $t+1$)

**C. Model** — $\geq 4$ models spanning the capability range. Use whatever models are available via `copilot` CLI at experiment time. Aim for meaningful capability spread — at least one sub-frontier and one frontier model.

**Always all-sources.** Every cell includes data + policies + expert beliefs + playbook. The question is whether *encoding* sources helps — not whether adding sources helps.

### Scenario Generation

Each scenario defines a causal DAG over lever columns with:
- Mechanistic edges with known coefficients (stored in `ground_truth.json`)
- Moderator edges (channel → elasticity, region → constraint activation)
- Natural collinearity from shared upstream causes
- Noise injection calibrated to the $K$ level and difficulty tier

**Domain: Revenue Growth Management (RGM).** RGM is a canonical instance of high-dimensional constrained decision-making under heterogeneous evidence: continuous/discrete levers (price, promotion depth, distribution coverage, shelf share, trade spend) form a coupled optimization; margin floors, promotion caps, and regulatory limits create a constraint graph with multi-hop cascading; and conflicting sources (data says increase promo, policy caps at 20%, expert says increase further) produce conflicting assignments in the CSP. This is not a synthetic toy problem — it instantiates the structural properties that make real enterprise decision optimization hard.

**Calibrate to realistic distributions:**
- Prices: $1.99–$12.99, modal $3.99
- Promo depth: 10–40%, mass at 15–25%
- SKU counts: 5–200
- Distribution coverage: 0.3–0.95
- Realistic column names. No generic `col_1`.

### Planted Effects (per scenario, ALL mandatory)

1. **Constraint boundary** — Data recommends action; compound constraint prohibits it. At $K_1$: 2-condition constraint. At $K_6$: cascading 4-step chain with temporal trigger. `PolicyDocument.rules` must contain populated `PolicyRule` objects.

2. **Interaction effect** — $\geq 2$ levers produce non-additive outcome. Main effects $p > 0.10$, joint $p < 0.05$. At $K \geq K_4$: 3-way and 4-way interactions.

3. **Simpson's paradox** — Aggregate reverses at segment level. Multi-mediator variants at $K \geq K_3$. Subgroup labels from binning/clustering, not column headers. Validate: aggregate vs within-group slope signs differ, naive 100-row sample misses it.

**Requirements:**
- $\geq 60\%$ of scenarios have conflicting sources
- $\geq 2$ distractor patterns per scenario
- No empty encoder output — verify in Phase −1

### Discovery Prompt (same for all cells)

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

Category-blind. No analytical hints.

---

## Study 2: Multi-Agent Extension

### Purpose

Test whether the benefits of evidence encoding amplify in multi-agent architectures.

Study 1 establishes that encoding improves each LLM call. Study 2 asks: when multiple agents independently reason over the same evidence and a synthesizer integrates their findings, does encoding compound? The hypothesis: encoding creates a shared analytical vocabulary (structured features, typed constraints, explicit conflicts) that makes synthesis tractable. Without it, synthesis is translation *and* integration; with it, synthesis is integration alone.

### Architecture

**Multi-agent pipeline:**

```
3 analyst agents (independent, parallel)
  └── each receives SAME encoded context
  └── each produces 5 findings (same discovery prompt)
  └── findings collected

Synthesizer agent
  └── receives all 15 findings (NO raw data)
  └── resolves conflicts, removes duplicates, weights evidence
  └── produces final 5 consolidated findings

Evaluation
  └── final 5 findings evaluated against ground truth
```

**Single-agent pipeline (baseline):**

```
1 analyst agent
  └── receives encoded context
  └── produces 5 findings (same discovery prompt)

Evaluation
  └── 5 findings evaluated against ground truth
```

### Design: 2 × 2 × 6 × M Factorial

| Factor | Levels |
|--------|--------|
| Encoding | Raw, Encoded |
| Architecture | Single-agent (1 analyst), Multi-agent (3 analysts → synthesizer) |
| Complexity ($K$) | $K_1$ through $K_6$ |
| Model | Same $M$ models as Study 1 |

**Key cells:**

| | Single agent | Multi-agent (3 → synth) |
|---|---|---|
| **Raw** | Cell C (baseline) | Cell A |
| **Encoded** | Cell D (prior result) | Cell B |

Study 1 provides Cells C and D. Study 2 adds Cells A and B.

### Multi-Agent Controls

To isolate the multi-agent effect from trivial explanations:

1. **Same model for all 3 analysts within a cell.** Model diversity is NOT the hypothesis — ensemble diversity from stochastic reasoning is.
2. **Same discovery prompt for all 3 analysts.** Role diversity is NOT the hypothesis — reasoning path diversity is.
3. **Temperature = model default.** Do not manipulate sampling temperature.
4. **Analysts see identical context.** Only the architecture (1 vs 3 → synthesis) differs.
5. **Synthesizer uses the SAME model** as the analysts. No capability uplift from a stronger synthesizer.

### Synthesis Prompt

```
You are a senior analyst consolidating findings from 3 independent analysts
who examined the same business scenario.

Their analyses were conducted independently — they could not see each
other's work. You must integrate their findings into a single coherent
assessment.

TASK: Produce exactly 5 consolidated findings.

RULES:
1. Where multiple analysts found the same pattern, STRENGTHEN the finding
   with combined evidence. Note the agreement count.
2. Where analysts DISAGREE about a pattern's direction or scope,
   investigate the contradiction. Explain which analyst is likely correct
   and why.
3. Remove duplicates — merge overlapping findings into one.
4. Prioritize findings discovered by multiple analysts independently.
5. If one analyst found something the others missed, include it ONLY if
   the evidence and reasoning are compelling on their own merits.
6. For each finding, note how many of the 3 analysts independently
   identified it (agreement: 3/3, 2/3, or 1/3).

ANALYST 1 FINDINGS:
{analyst_1_findings}

ANALYST 2 FINDINGS:
{analyst_2_findings}

ANALYST 3 FINDINGS:
{analyst_3_findings}

Return ONLY a JSON array of 5 consolidated findings:
[{"columns": [...], "direction": "...", "magnitude": "...",
  "scope": "...", "mechanism": "...", "confidence": 0.0,
  "agreement": "3/3|2/3|1/3",
  "resolution": "unanimous|majority_rules|adjudicated"}]
```

Category-blind. Synthesizer sees ONLY findings — never raw data or encoded context.

### Planned Tests (Bonferroni-corrected, $\alpha = 0.05/4 = 0.0125$)

From the 2 × 2 × 6 factorial:

| # | Claim in abstract | Statistical test | What it measures |
|---|---|---|---|
| T1 | Encoding main effect (replication) | Encoded vs Raw, pooled across architecture and $K$ | Does encoding still help? |
| T2 | Architecture main effect | Multi vs single, pooled across encoding and $K$ | Does multi-agent help at all? |
| T3 | Encoding × architecture interaction | $(B - D) > (A - C)$: multi-agent benefit larger under Encoded | Does encoding *enable* multi-agent gains? |
| T4 | Architecture × complexity interaction | Multi-agent advantage at $K_5$–$K_6$ vs $K_1$–$K_2$ | Does multi-agent help more at high complexity? |

**Priority order:** T1 is replication (must pass). T2 is the headline multi-agent finding. T3 is the interaction that justifies the combined story. T4 is secondary/exploratory.

### Multi-Agent Specific Metrics (all deterministic — no LLM judge)

| Metric | Computation |
|---|---|
| **Inter-agent agreement** | Jaccard similarity on variable sets across 3 analysts' findings. Mean per scenario. |
| **Synthesis improvement** | $\text{regret}(\text{synthesis}) - \text{regret}(\text{best individual})$. Negative = synthesis helped. |
| **Synthesis degradation rate** | Proportion of scenarios where synthesis regret $>$ best individual regret. |
| **Agreement × encoding** | Mean agreement under Encoded vs Raw. Prediction: Encoded produces higher agreement (structured input → more convergent reasoning). |
| **Ensemble diversity** | 1 − mean pairwise Jaccard across 3 analysts. Measures reasoning path variety. |
| **Diversity–accuracy tradeoff** | Correlation of ensemble diversity with synthesis regret. Prediction: moderate diversity optimal. |
| **Cost per correct decision** | Total tokens (3 discovery + 1 synthesis) × price / max(1 − regret, 0.01). Compare multi vs single. |
| **Cost amortization ratio** | Multi-agent cost / single-agent cost vs multi-agent regret improvement. Is the extra cost worth it? |

### Multi-Agent Predictions (pre-registered)

These predictions must be tested, not assumed.

1. **Encoded agreement > Raw agreement** — Structured encoding constrains reasoning to shared analytical features, producing more convergent findings. Raw text lets each agent latch onto different surface patterns.
2. **Synthesis helps Encoded more than Raw** — Encoded context produces findings with a common vocabulary (coefficients, constraint IDs, belief objects) that synthesis can aggregate. Raw text produces incomparable findings.
3. **Multi-agent advantage increases with $K$** — At low complexity, a single Encoded agent finds everything. At high complexity, agents miss different effects; encoding makes synthesis of partial views possible.
4. **Synthesis degradation rate $< 20\%$** — Report honestly if the synthesizer discards correct minority findings.
5. **Cost amortization is favorable at high $K$** — At $K_6$, multi-Encoded costs $\sim 4\times$ single-Encoded, but cost per correct decision should decrease if regret drops $> 25\%$.

---

## EEP: The Evidence Encoding Protocol

### Stage 1: Signal Encoding

Replace raw data tables with statistical profiles: means, standard deviations, ranges, pairwise correlations with outcome variables. Rank variables by signal strength. Compute subgroup-level statistics where grouping variables exist. Add cross-lever interaction profiles for lever triples when $K \geq K_3$.

This is NOT feature engineering in the ML sense. LLMs do not learn representations at inference time — they perform a single forward pass through a fixed model. Deterministic encoding is a permanent structural advantage — analogous to variable ordering in CSP solving.

### Stage 2: Constraint Encoding

Parse prose policy documents into typed constraint vectors:
```
C1: promotion <= 0.20 [BINDING: current=0.14, headroom=0.06]
C2: IF promo_depth > 0.25 AND channel = "traditional" → PROHIBIT price_decrease ON base_price
C3: C2 triggers C4 on distribution (cascading)
```
Annotate binding status, headroom, and cascading relationships. Cross-reference with data signals: `"Data recommends increasing discount_pct (r=+0.35). Conflicts with RULE_003."`

### Stage 3: Conflict Encoding

Cross-reference expert beliefs against constraints and data signals. Flag conflicts explicitly:
```
E1 CONFLICT with C1: E1 wants promotion increase but C1 caps at 0.20
DATA-EXPERT CONFLICT: correlation(promo, revenue)=+0.61 but E2 predicts neutral effect
```
This eliminates the implicit $O(s^2)$ search the model would otherwise perform.

### Encoding Rules

- **Encoded replaces Raw — never appends.** Token compression is inherent.
- **No placeholder lines.** No `"(statistical profile complete)"` filler.
- **Character ratio [0.7×, 1.5×]** achieved through real analytical content.
- **Every Encoded constraint section must contain populated rules** — not just headers.
- **Every Encoded belief object must have** populated claims, confidence, decay, evidence, segment_validity.

---

## Metrics

### Co-Primary (deterministic — no LLM judge)

| Metric | How computed | What it measures |
|---|---|---|
| **Decision Regret** | Extract (lever, direction, magnitude) from findings → forward-simulate through known DAG → `regret = E[optimal] − E[recommended]`. Constraint violations penalized at 2× max feasible regret. | Does the recommendation actually improve outcomes? |
| **Constraint Violation Rate (CVR)** | Each recommendation checked against ground-truth rules. Binary per recommendation. | Will the advice get a practitioner in trouble? |

### Token Efficiency (deterministic)

| Metric | How computed |
|---|---|
| Input tokens | Count per-scenario using model-appropriate tokenizer |
| Token compression ratio | $\text{Raw tokens} / \text{Encoded tokens}$ per scenario per $K$ |
| Cost per correct decision | $\text{total tokens} \times \text{price per token} / \max(1 - \text{regret}, 0.01)$ |
| Regret per kilotoken | $\text{regret} / (\text{input tokens} / 1000)$ |

### Secondary (deterministic)

| Metric | How computed |
|---|---|
| Variable Recall | $|\text{found} \cap \text{gt\_vars}| / |\text{gt\_vars}|$ |
| Direction Accuracy | Exact match after normalization |
| Cascade Detection Rate | Per multi-hop chain: did the model detect the full chain? |
| Cross-run $\sigma$ | SD of Decision Regret across $k$ runs |
| Failure Rate | Proportion of runs where best-match score = 0 for any planted effect |
| Causal Edge Recovery F1 | Parse stated mechanisms into (cause, effect, direction) triples. Compare against planted DAG. |

### Evaluation Pipeline

1. **Code pre-filter** (mandatory gate): Score Variables (graduated: $|\text{found} \cap \text{gt}| / |\text{gt}|$) and Direction from JSON. Eliminate non-matches.
2. **Batched LLM judge**: 8 dimensions per (finding, GT) pair. Graduated Variables (0–1), binary Direction/Scope/Mechanism/Quantification, continuous Precision/Completeness/Specificity (0–2). Match threshold $\geq 3.5$.
3. **Vote calibration**: Phase 1 runs 3 judge votes → Krippendorff's α. If $\alpha \geq 0.85$, Phase 2 drops to 1 vote.

---

## Statistical Analysis Plan

### Study 1 Analysis

**3-way mixed ANOVA** on Decision Regret: encoding (within-subject) × complexity (between-subject) × model (between-subject).

| Test | Hypothesis | α (corrected) |
|---|---|---|
| Encoding main effect | Encoded regret < Raw regret | 0.017 |
| Encoding × complexity | Interaction: advantage changes with $K$ | 0.017 |
| Encoding × model | Weaker models gain more | 0.017 |

Supplemented by Wilcoxon signed-rank on cell-mean differences. Cohen's $d$ at each (model, $K$) cell. 95% CIs for all contrasts.

**Pareto analysis**: For each (model, $K$) cell, determine whether Encoded dominates Raw on both accuracy AND token cost. Report dominance share with 95% CI.

### Study 2 Analysis

**4-way mixed ANOVA** on Decision Regret: encoding × architecture × complexity × model.

| Test | Hypothesis | α (corrected) |
|---|---|---|
| T1: Encoding main effect | Encoded < Raw (replication) | 0.0125 |
| T2: Architecture main effect | Multi < Single | 0.0125 |
| T3: Encoding × architecture | Multi-agent benefit larger under Encoded | 0.0125 |
| T4: Architecture × complexity | Multi-agent advantage increases with $K$ | 0.0125 |

Report all four tests regardless of significance. Report effect sizes ($\eta^2_p$, Cohen's $d$) and 95% CIs. Report partial eta-squared for each factor and interaction.

**Multi-agent specific analyses:**
- Paired $t$-test on inter-agent agreement: Encoded vs Raw
- Wilcoxon signed-rank on synthesis improvement: is median negative (synthesis helps)?
- Cost-effectiveness analysis: cost per unit regret reduction for multi vs single

---

## Phases

### Phase −1: Encoding + Synthesis Pre-Flight (0 LLM calls)

For 1 scenario at each $K$ level (6 total):
1. Generate Raw and Encoded encodings. Print token counts and character counts.
2. Encoded constraint sections MUST contain populated rules. If empty → fix scenario generator.
3. Encoded belief objects MUST have all fields populated.
4. Forward-simulate data-optimal action → CVR > 0 at $\geq K_2$.
5. Source conflicts present: data recommends X, policy/expert opposes X.
6. No placeholder filler lines. Character ratio [0.7×, 1.5×] via content.
7. Token compression ratio: report per $K$ level (expect 2–10× at $K_1$, 30–260× at $K_6$).
8. **Dry-run synthesis prompt**: Format 3 sets of mock findings → verify synthesis prompt produces valid JSON with agreement field.

**If any check fails: STOP and fix before proceeding.**

### Phase 0: Complexity Calibration (6 scenarios × 2 encodings × 1 model, k=3 = 36 calls)

Run on the median-capability model. Single-agent only (no multi-agent yet).

Verify:
- **Complexity gradient exists:** Raw regret increases with $K$ (Spearman $\rho > 0.7$)
- **Encoded degrades slower:** Encoded regret increases slower than Raw with $K$
- **Separation at high $K$:** Encoded regret $<$ Raw regret at $K_5$ and $K_6$ by $\geq 0.15$
- **No ceiling at low $K$:** both Raw and Encoded have non-zero regret at $K_1$
- **CVR $> 0$** at $K \geq K_3$ for Raw

If the gradient is too weak, increase constraint depth or add more rows. **Max 2 calibration attempts.**

### Phase 1: Multi-Model + Multi-Agent Pilot (6 scenarios, k=3)

One scenario per $K$ level. Run ALL 4 cells (single-Raw, single-Encoded, multi-Raw, multi-Encoded) × all models.

**Single-agent gates (Study 1):**
- Each model shows encoding benefit at high $K$ ($\text{Encoded regret} < \text{Raw regret}$)
- No model shows Raw > Encoded at low $K$ (encoding never hurts accuracy)
- Token compression ratio consistent across models

**Multi-agent gates (Study 2):**
- Multi-Encoded regret $\leq$ single-Encoded regret in $\geq 50\%$ of (model, $K$) cells (multi-agent doesn't consistently hurt)
- Synthesis produces valid JSON in $\geq 95\%$ of runs
- Inter-agent agreement is computable (findings share enough structure to compare)
- At least one model shows multi-Encoded $<$ single-Encoded at $K \geq K_4$
- Synthesis degradation rate $< 40\%$ (synthesis doesn't make things worse too often)

**If multi-agent gates fail:**
- Check synthesis prompt quality — are findings being discarded arbitrarily?
- Check whether 3 analysts produce sufficiently diverse findings
- If synthesis consistently hurts: diagnose whether the synthesizer is averaging over correct minority findings
- **Max 2 revision attempts.** On 3rd failure → report multi-agent null honestly in the paper.

### Phase 2: Full Experiment

**Study 1:** $\geq 36$ scenarios × 6 $K$ levels × 2 encodings × $M$ models × $k = 3$ runs.
**Study 2:** Same scenarios × 2 architectures × 2 encodings × 6 $K$ levels × $M$ models × $k = 3$ runs.

Phase 2 may reuse Study 1 single-agent data (Cells C and D) — Study 2 only needs to run Cells A and B.

**HARD GATES:**
- **Study 1 gate:** Encoding main effect $p < 0.017$ on Decision Regret.
- **Study 2 gate:** At least one of T2, T3, or T4 at $p < 0.0125$.
- If Study 1 gate fails: `DESIGN_INVALID`, do NOT paper.
- If Study 1 passes but Study 2 fails: Write the paper with Study 1 results. Report the multi-agent null honestly as "future work that did not replicate." This is still a strong paper.

Report ALL planned tests regardless of significance. Report effect sizes ($\eta^2_p$, Cohen's $d$) and 95% CIs for everything.

**Per-difficulty diagnostics:**
- Encoding main-effect $d$ per $K$ level
- Architecture main-effect $d$ per $K$ level
- Encoding × architecture interaction $d$ per $K$ level
- Inter-agent agreement per $K$ level per encoding
- Synthesis improvement per $K$ level per encoding
- Cost per correct decision per cell

### Phase 3: Paper + Figures (only after Phase 2 passes Study 1 gate)

---

## E3: Pipeline Compression

Run full pipeline on all scenarios at Encoded (single-agent). Separate from the factorial.

Report:
- Compression ratio: `naive_space / pipeline_output_size`, expect 15–270× scaling with $K$
- Quality gate scores: evidence density, constraint alignment, actionability, testability, novelty
- **Random baseline:** pipeline shortlist recall vs random 15-item shortlist (paired $t$-test)
- Correlation of compression with $K$ level (expect $\rho > 0.7$)

---

## Key Figures (mandatory for the paper)

### Figure 1: Framework Diagram
Evidence encoding: Raw (top) asks LLM to construct the constraint graph AND reason. Encoded (bottom) offloads deterministic encoding operations (signal, constraint, conflict). Show both single-agent and multi-agent pipelines. Include paradigm progression (RAG → CoT → Encode) as a callout.

### Figure 2: Study 1 Main Result
Direction accuracy by complexity and encoding. Pooled across models + per-model breakdown. Encoded outperforms Raw at every level for every model.

### Figure 3: Consistency / Compression Paradox
Left: Encoded advantage is flat across complexity. Right: compression grows but advantage stays flat. Connect to CSP theory: fixed overhead from constraint graph construction.

### Figure 4: Model × Encoding Interaction
Weaker models benefit most. Advantage magnitude vs model capability.

### Figure 5: Pareto Frontier
Accuracy vs tokens. Encoded up-and-left of Raw everywhere.

### Figure 6: Multi-Agent Amplification (Study 2)
Left: Decision Regret by encoding × architecture (4-cell comparison). Right: Amplification factor (multi/single regret ratio) by $K$ level for Raw vs Encoded.

### Figure 7: Inter-Agent Agreement
Left: Agreement rate (Jaccard) by encoding. Encoded $>$ Raw. Right: Relationship between agreement and synthesis quality.

### Figure 8: Cost-Effectiveness
Cost per correct decision for all 4 cells at $K_4$ (most practically relevant). Multi-Encoded should be cheaper per correct decision than single-Raw, despite higher total cost.

### Figure 9: Phase Diagram
$x$: Complexity ($K_1$–$K_6$). $y$: Encoding benefit (Raw regret $-$ Encoded regret). Separate curves for single-agent and multi-agent. Multi-agent curve should be above single-agent curve at high $K$.

### Figure 10: CSP Analogy + Agent Implications
Combined figure: (a) CSP encoding pipeline mapped to EEP stages, (b) cost structure: encoding is O(1), benefit is O(N×M) across agents and calls, (c) paradigm timeline (RAG → CoT → Encode, showing orthogonal axes).

Design additional figures as needed. These ten are mandatory.

---

## Hard Rules

1. **Same model for all cells within a model's run.** Each model tested independently. Same model for all 3 analysts + synthesizer in multi-agent cells.
2. **Never truncate rows.** All rows delivered to LLM. Reduce columns if context is tight.
3. **Category-blind prompts.** Both discovery and synthesis prompts. No analytical hints.
4. **Encoded replaces Raw, never appends.**
5. **Single entry point:** `run_experiments.py`.
6. **LLM calls via** `copilot -p "<prompt>" -s --no-color --allow-all`. Cache by prompt hash.
7. **Ground truth used only for evaluation.** Never loaded by the reasoning system.
8. **$k \geq 3$ in all phases.** Never $k = 1$.
9. **NO SIMULATION.** No mock/fake/sim files. Reduce $N$ or models if budget is tight — never simulate.
10. **Deterministic metrics are primary evidence.** Decision Regret and CVR from forward-simulation through known DAGs using numpy. No LLM involvement in metric computation.
11. **Token counts are mandatory.** Every run records input_tokens, output_tokens.
12. **Parallelize LLM calls.** $\geq 4$ concurrent calls during Phase 2. For multi-agent cells, dispatch all 3 analysts in parallel.
13. **Validate planted effects at scenario generation time.** Simpson's: aggregate vs within-group slopes differ. Interactions: main effects $p > 0.10$, joint $p < 0.05$. Constraints: CVR $> 0$.
14. **No LLM call may generate experiment metrics JSON.** All statistics computed by deterministic Python code (scipy/numpy).
15. **Replace zero-information scenarios** where all cells produce identical regret within $\varepsilon = 0.001$.
16. **Code pre-filter is mandatory gate.** No finding may score $> 0$ on the rubric unless it passes the code pre-filter.
17. **Multi-agent analysts are independent.** No communication between analysts. They cannot see each other's findings. Only the synthesizer sees all findings.
18. **Synthesizer sees ONLY findings — never raw data or encoded context.** This ensures synthesis operates on the analytical products, not by re-analyzing the evidence.
19. **Report multi-agent null honestly.** If Study 2 gates fail, do NOT fabricate or cherry-pick. Report the null with confidence intervals and discuss why multi-agent did not help (synthesis degradation? insufficient diversity? wrong ensemble size?).

---

## Known Failure Modes from Prior Runs

1. **Ceiling from easy Simpson's.** Textbook Simpson's scores $\geq 0.85$ across all cells. Fix: multi-mediator variants.
2. **$k = 1$ collapses variance.** Fix: $k \geq 3$ always.
3. **$\leq 500$ rows too easy.** Frontier LLMs scan small tables trivially. Fix: $\geq 1000$ rows.
4. **Simple constraints trivially parsed.** Fix: $\geq 3$ conditions with nested disjunction at $K \geq K_2$.
5. **Empty Encoded output.** Prior run: encoder rendered empty constraint headers, padded with filler. Fix: scenario generator must populate rules. Verify Phase −1.
6. **Source content redundant with data.** Fix: $\geq 60\%$ conflicting sources.
7. **Constraint floor effect.** Fix: $\geq 50\%$ CVR $> 0$ at $K \geq K_2$.
8. **Discovery prompt category-hinting.** Fix: genuinely category-blind prompt.
9. **Prior null on frontier model at low $K$.** GPT-5.4 showed $d = -0.13$ when complexity was too low. Fix: the $K$-axis goes high enough to challenge any model.

**Anticipated multi-agent failure modes:**
10. **Synthesizer discards correct minority.** One analyst finds the right answer, two miss it. Synthesizer goes with majority. Fix: synthesis prompt instructs to evaluate evidence quality, not just count votes.
11. **Redundant analysts.** All 3 find the same 5 obvious patterns. No diversity = no ensemble benefit. Fix: verify ensemble diversity metric before Phase 2. If diversity $< 0.1$, consider different temperature settings.
12. **Synthesis adds noise.** An extra LLM call introduces new errors. Fix: monitor synthesis degradation rate. If $> 30\%$, diagnose the synthesis prompt.
13. **Multi-agent overhead not justified.** 4× cost for $< 5\%$ regret improvement. Fix: report cost-effectiveness honestly. This is a legitimate finding — the paper can argue that multi-agent is valuable only above a complexity threshold.

---

## Success Criteria

### Study 1 (Replication — must all pass)

| ID | Criterion | How measured |
|---|---|---|
| **SC1** | Encoding main effect is large | $\eta^2_p \geq 0.50$ on Decision Regret, $p < 0.017$ |
| **SC2** | Consistent advantage (no phase transition) | Encoding × complexity $p > 0.05$ OR advantage positive at all $K$ |
| **SC3** | Weaker models benefit most | Encoding × model interaction $p < 0.05$ OR monotonic decrease in $\Delta$ with capability |
| **SC4** | Pareto dominance | $\geq 80\%$ of (model, $K$) cells |
| **SC5** | Compression paradox | Advantage does not correlate with compression ratio |
| **SC6** | Internal replication | Phase 2 confirms Phase 1, $p < 0.05$ |

### Study 2 (Multi-Agent — pre-registered, report all results)

| ID | Criterion | How measured |
|---|---|---|
| **SC7** | Multi-agent amplification | Architecture main effect $p < 0.0125$ on Decision Regret |
| **SC8** | Encoding enables multi-agent | Encoding × architecture interaction $p < 0.0125$ |
| **SC9** | Agreement is higher under Encoded | Paired $t$-test on inter-agent Jaccard, $p < 0.05$ |
| **SC10** | Multi-agent scales with complexity | Architecture × complexity interaction $p < 0.05$ |
| **SC11** | Cost-effective at high $K$ | Cost per correct decision: multi-Encoded $<$ single-Raw at $K \geq K_4$ |
| **SC12** | Synthesis rarely degrades | Synthesis degradation rate $< 20\%$ |

**If SC1–SC6 pass but SC7–SC12 fail:** The paper is still publishable as a strong single-agent study with an honest multi-agent negative result section. This is scientifically valuable — it establishes the conditions under which multi-agent does NOT help, bounding the claim space for future work.

---

## Call Budget

With $N_{\text{scenarios}} = 36$ (6 per $K$), $M = 4$ models, $k = 3$:

| Phase | Single-agent calls | Multi-agent calls | Judge calls | Total |
|---|---|---|---|---|
| Phase −1 | 0 | 0 | 0 | **0** |
| Phase 0 | 36 | 0 | ~72 | **~108** |
| Phase 1 | $36 \times M = 144$ | $36 \times M \times 4 = 576$ | ~720 | **~1,440** |
| Phase 2 (Study 1) | $216 \times M = 864$ | 0 | ~1,728 | **~2,592** |
| Phase 2 (Study 2) | 0 (reuse) | $216 \times M \times 4 = 3,456$ | ~3,456 | **~6,912** |
| Pipeline | 0 (reuse) | 0 | ~36 | **~36** |

**Total: ~11,088 calls.** Multi-agent is expensive. To reduce:
- Decrease $M$ from 4 to 3 (saves ~25%)
- Decrease scenarios from 36 to 24 (4 per $K$; saves ~33%)
- Run Study 2 on 2 models only (strongest + weakest; saves ~50% of Study 2)
- Never reduce $k$ below 3.

---

## Deliverables

```
demos/computational-triage/
  output/
    study1_results.json           # Single-agent: per-scenario per-encoding per-model per-run
    study2_results.json           # Multi-agent: same + architecture factor
    token_efficiency.json         # Compression ratios, cost per correct decision
    multiagent_metrics.json       # Agreement, diversity, synthesis improvement, degradation
    deterministic_metrics.json    # Variable Recall, Direction Accuracy, etc.
    reliability_metrics.json      # Cross-run σ, failure rate
    pipeline_scores.json          # Trajectory pruning + random baseline
    encoding_hashes.json          # SHA-256 + token counts
    phase_transitions.json        # Per-model K_c estimates (Study 1)
    data/                         # Synthetic scenarios + ground_truth.json
    paper/
      paper.tex + paper.pdf + figures/ + references.bib
    index.html                    # Interactive webapp
  src/                            # All source code
  run_experiments.py              # Single entry point
  .llm_cache/                     # Prompt-hash cache
```

Python 3.11+, numpy, scipy, matplotlib. Copilot CLI for all LLM calls.

When complete: delete agent branches, remove worktrees, kill tmux sessions.

---

## Completion Protocol

**Do NOT write `.swarm/deliverable.md` until ALL of the following are true:**
1. Study 1 Phase 2 HARD GATE passed (encoding main effect $p < 0.017$)
2. Study 2 Phase 2 completed (all 4 tests reported, pass or fail)
3. Pipeline results in `output/pipeline_scores.json`
4. Paper compiles with all figures from actual experimental data
5. `output/study1_results.json` and `output/study2_results.json` complete
6. `output/multiagent_metrics.json` complete
7. All Study 1 success criteria (SC1–SC6) verified
8. All Study 2 success criteria (SC7–SC12) reported (failures reported honestly)

Writing `deliverable.md` prematurely will cause the server to mark this investigation as complete and kill all agents. The deliverable is the LAST file written, after everything else is done.
