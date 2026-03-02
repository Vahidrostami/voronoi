# Navigating Coupled Decision Spaces with Fragmented and Heterogeneous Knowledge: A System of Agents for Reasoning

Build a computational framework and full experimental validation for a multi-agent system that reasons over coupled decision levers using heterogeneous knowledge sources, then write a complete academic paper with figures, tables, and LaTeX output.

## Abstract

A broad class of applied decision problems—including revenue growth management, precision medicine, materials discovery, supply chain design, and financial risk management—share a common underlying structure. In these settings, the decision space is combinatorial over interdependent levers, the feasible region is constrained by hard operational limits, and the knowledge required to navigate the space is fragmented across sources with incompatible semantics, noise characteristics, and epistemic status. Adjusting one decision variable alters the optimal configuration of others, rendering independent optimization invalid. At the same time, the heterogeneity of available knowledge—ranging from quantitative measurements and codified rules to expert judgment—creates a representational bottleneck that prevents joint reasoning and forces reliance on ad‑hoc human cognitive synthesis.

This paper makes three contributions. First, we formally characterize this problem class through three structural invariants: lever coupling, knowledge heterogeneity, and the cognitive assembly bottleneck. We show that approaches addressing any single invariant in isolation necessarily produce incomplete solutions. This characterization defines the structural conditions under which a unified framework can generalize across domains. Second, we introduce a multimodal encoding layer that transforms each knowledge type into a reasoning‑ready representation while preserving its native semantics: quantitative data are encoded as statistical profiles, policy knowledge as tiered constraint vectors, and expert judgment as temporal belief objects equipped with confidence and decay functions. By preserving epistemic differences rather than collapsing them, the framework enables agents to reason jointly across all knowledge types. Conflicts between sources—such as quantitative signals contradicting established heuristics—become diagnostic signals of potential structural change rather than unresolvable noise. Third, we present a progressive space‑reduction pipeline operating over coupled levers in three stages. Parallel diagnostic agents prune the combinatorial space along complementary analytical dimensions; a causal synthesis layer assembles the surviving evidence into structured interventions specifying lever, direction, scope, and mechanism; and a multidimensional quality gate filters candidates based on evidence density, constraint alignment, actionability, testability, and novelty.

We instantiate the framework in the domain of Revenue Growth Management, where commercial levers—including pricing, promotion, assortment, distribution, and pack‑price architecture—are deeply coupled and where knowledge is distributed across numerical data, policy documents, and subject‑matter expertise. We show that the encoding layer enables cross‑type reasoning that reveals interaction effects invisible to siloed analyses, and that the progressive reduction pipeline efficiently compresses a large candidate space into a focused set of causally grounded, testable hypotheses. We conclude by identifying the structural conditions under which the framework generalizes to other domains characterized by coupled decision levers.

---

## The Experiment

### Overview

We validate the framework through a **synthetic-but-realistic Revenue Growth Management (RGM) scenario** with known ground truth. This lets us measure whether the system discovers interaction effects that siloed approaches miss, and whether the progressive pipeline correctly prioritizes causally grounded interventions.

The scenario has:
- **5 coupled commercial levers** with known interaction structure
- **3 heterogeneous knowledge sources** with planted signals
- **Planted ground-truth interventions** (some discoverable only through cross-source reasoning)
- **Controlled ablation conditions** to validate each contribution independently

### The RGM Scenario: "BevCo"

A simulated beverage company with 50 SKUs across 5 categories, 200 retail stores in 4 regions, operating over 104 weeks (2 years).

#### The 5 Commercial Levers

| Lever | Variables | Range | Coupling |
|-------|-----------|-------|----------|
| **Pricing** | Base price per SKU per region | $0.50–$8.00 | Coupled with promotion (discount depth), assortment (premium mix), pack-price (per-unit economics) |
| **Promotion** | Promo type × frequency × depth per SKU | 12 promo types × 0–4/month × 10–50% off | Coupled with pricing (margin erosion), distribution (display allocation) |
| **Assortment** | SKU inclusion per store cluster | Binary per SKU × 20 clusters | Coupled with pricing (portfolio margin), distribution (shelf space) |
| **Distribution** | Store coverage × shelf facings × display | Coverage %, 1–8 facings, display binary | Coupled with assortment (space allocation), promotion (display lift) |
| **Pack-Price Architecture** | Pack sizes × price points per SKU | 3–6 pack sizes, price ladders | Coupled with pricing (cannibalization), assortment (portfolio coherence) |

**Total naive decision space**: ~10^18 combinations (intractable without structure).

#### Known Interaction Effects (Ground Truth)

Plant these specific interaction effects into the synthetic data generator. The system should discover them; siloed analysis should miss them.

1. **Price-Promotion Trap**: SKUs in Category A show positive ROI on 30% promotions when analyzed independently, but when pricing is jointly optimized, a 5% base-price reduction with no promotions yields 12% higher net revenue. The promotion effect is an artifact of price-insensitive loyal customers being subsidized.

2. **Assortment-Distribution Synergy**: Removing 8 low-velocity SKUs (assortment) frees shelf space that, when reallocated to top SKUs (distribution), increases category revenue by 9%. Neither lever alone produces this effect — the assortment change alone loses 3% revenue, the distribution change alone gains only 2%.

3. **Pack-Price Cannibalization Mask**: Introducing a 12-pack at $9.99 appears to grow volume +15% in isolation, but it cannibalizes the 6-pack at $5.99 by 22%, net destroying $0.43/unit margin. This is only visible when pack-price and pricing data are analyzed jointly.

4. **Cross-Source Signal**: Quantitative data shows declining Category B sales. Policy documents mandate minimum 30% shelf share for Category B. Expert judgment (planted) says "Category B decline is seasonal and will reverse in Q3." The correct intervention depends on synthesizing all three: maintain shelf share (policy), don't panic-promote (expert), but shift mix toward higher-margin B SKUs (data).

5. **Constraint-Coupling Conflict**: An expert suggests aggressive pricing on premium SKUs, but policy constrains minimum margin at 25%. The diagnostic agents should identify that the expert signal, while directionally correct, must be scoped to only 3 of 12 premium SKUs where margin headroom exists.

### Knowledge Sources

#### Source 1: Quantitative Data (Numerical)

Generate synthetic datasets:

- **`data/sales_transactions.csv`**: 104 weeks × 50 SKUs × 200 stores = ~1M rows. Columns: week, store_id, sku_id, region, category, units_sold, revenue, price_paid, promo_flag, promo_type, promo_depth, display_flag, facings, pack_size.
- **`data/price_elasticity.csv`**: Estimated own-price and cross-price elasticities per SKU pair per region. Include noise (σ=0.15) and some systematically biased estimates (to test robustness).
- **`data/market_share.csv`**: Weekly category-level market share by region. Include competitor effects.

The data generation must embed the 5 ground-truth interaction effects above. The data alone should be sufficient to discover effects 1–3 if analyzed with the right cross-lever lens, but effect 4 requires cross-source synthesis, and effect 5 requires constraint awareness.

**Multi-collinearity**: Introduce realistic multi-collinearity between levers in the generated data. In real RGM data, levers rarely move independently — when prices drop, promotions often intensify; when assortment expands, distribution spreads thin. Embed the following collinear structures:
- **Price–Promotion** (ρ ≈ –0.6): Deeper promotions correlate with higher base prices (retailers compensate discounts with higher list prices)
- **Assortment–Distribution** (ρ ≈ 0.5): Stores carrying more SKUs tend to allocate fewer facings per SKU
- **Promotion–Display** (ρ ≈ 0.7): Promoted SKUs are much more likely to have display placement, confounding the independent effect of each
- **Pack-Size–Price** (ρ ≈ 0.85): Larger packs have proportionally lower per-unit prices, creating near-linear dependence

This multi-collinearity serves two purposes: (1) it makes the data realistic — agents that naïvely estimate independent lever effects will produce inflated or sign-flipped coefficients, and (2) it tests whether the diagnostic agents (especially the Elasticity and Interaction agents) can disentangle confounded lever effects from genuine causal interactions. The Interaction Agent should flag collinear lever pairs and adjust its interaction detection to partial correlations rather than raw correlations. Record the ground-truth correlation matrix in `src/data/ground_truth.py` so scoring can verify whether agents correctly identify vs. are fooled by multi-collinearity.

#### Source 2: Policy Knowledge (Codified Rules)

- **`data/policies.json`**: A structured document containing:
  - Minimum margin thresholds per category (hard constraints)
  - Maximum promotion frequency per quarter per SKU (soft constraints)
  - Shelf space minimums per category (hard constraints)
  - Pricing corridor rules (max price gap between adjacent pack sizes)
  - Brand portfolio rules (minimum SKU count per brand tier)

Format each policy as: `{rule_id, type: "hard"|"soft", lever, scope, threshold, rationale}`

#### Source 3: Expert Judgment (Qualitative)

- **`data/expert_beliefs.json`**: 15–20 expert statements, each with:
  - `statement`: Natural language belief (e.g., "Premium segment is under-priced relative to market")
  - `confidence`: 0.0–1.0 (how sure the expert is)
  - `recency`: Date of the belief
  - `domain`: Which lever(s) it concerns
  - `basis`: "experience" | "analysis" | "intuition"
  
  Plant some beliefs that are correct, some that are outdated/wrong, and some that are only correct when combined with quantitative evidence.

### What to Build and Measure

#### Experiment 1: Encoding Layer Validation

Test that the multimodal encoding preserves information and enables cross-type reasoning.

**Metrics:**
- **Encoding fidelity**: Can the original information be reconstructed from the encoded form? Measure information loss for each type.
- **Cross-type query success**: Given 20 pre-designed queries that require reasoning across 2+ knowledge types, measure how many produce correct answers with encoding vs. raw concatenation vs. LLM-only baseline.
- **Conflict detection rate**: Of the 5 planted conflicts, how many does the system surface?

#### Experiment 2: Ablation Study — Invariants in Isolation

Run the system in 4 configurations. **All configurations use the same LLM** — the only variable is what information the LLM receives and how it's structured. This isolates the framework's contribution from the LLM's raw capability.

| Config | Lever Coupling | Knowledge Heterogeneity | Cognitive Assembly |
|--------|---------------|------------------------|-------------------|
| **Full system** | ✓ (coupling graph in prompt) | ✓ (encoded representations) | ✓ (multi-agent pipeline) |
| **No coupling** (independent lever optimization) | ✗ (agents see one lever at a time) | ✓ (encoded representations) | ✓ (multi-agent pipeline) |
| **No encoding** (raw data in prompt) | ✓ (coupling graph in prompt) | ✗ (raw CSV/JSON/text dumped into prompt) | ✓ (multi-agent pipeline) |
| **No pipeline** (single-pass LLM) | ✓ (coupling graph in prompt) | ✓ (encoded representations) | ✗ (one LLM call with everything, no staged agents) |

**Why this ablation is now meaningful**: 
- "No encoding" gives the **same LLM** raw data instead of encoded representations. If encoding helps, the LLM discovers more effects with structured input.
- "No pipeline" gives the **same LLM** all encoded knowledge in a single prompt instead of staged diagnostic agents. If the pipeline helps, staged reasoning outperforms monolithic reasoning.
- "No coupling" gives agents encoded data but **removes the coupling graph** so they analyze levers independently. If coupling helps, cross-lever effects are missed.

**Metrics for each**:
- Number of ground-truth effects discovered (out of 5)
- Precision and recall of generated interventions vs. ground truth
- Number of constraint violations in proposed interventions
- Revenue impact of top-5 recommendations (simulated)

#### Experiment 3: Progressive Reduction Pipeline

Measure the pipeline's compression and quality at each stage:

| Stage | Input Size | Output Size | Quality Metric |
|-------|-----------|-------------|----------------|
| **Stage 1: Diagnostic agents** (parallel) | Full combinatorial space (~10^18) | Candidate regions (~10^3) | Coverage of ground-truth effects |
| **Stage 2: Causal synthesis** | ~10^3 candidates | ~50 structured interventions | Causal coherence score |
| **Stage 3: Quality gate** | ~50 interventions | ~8–12 final recommendations | Multi-dimensional quality score |

**Diagnostic agent types** (run in parallel):
1. **Elasticity Agent**: Analyzes price/cross-price elasticities, identifies lever sensitivities
2. **Interaction Agent**: Detects statistical interaction effects between lever pairs
3. **Constraint Agent**: Maps feasible regions given policy constraints
4. **Temporal Agent**: Identifies trend, seasonality, and structural breaks
5. **Portfolio Agent**: Analyzes SKU-level portfolio effects (cannibalization, halo)

Each agent operates on a complementary analytical dimension. Their outputs are structured evidence packets.

#### Experiment 4: Cross-Domain Generalization Signal

Apply the same framework to 2 stripped-down secondary domains to show structural generalization (not full instantiation — just enough to demonstrate the invariants transfer):

- **Precision Medicine (mini)**: 3 coupled treatment levers (drug, dose, timing), heterogeneous knowledge (trial data, clinical guidelines, physician judgment). Synthetic dataset, 100 patients.
- **Supply Chain Design (mini)**: 3 coupled levers (sourcing, inventory, routing), heterogeneous knowledge (cost data, compliance rules, supplier assessments). Synthetic dataset, 50 nodes.

**Metric**: Does the framework discover at least 1 planted cross-lever interaction in each domain using the same pipeline architecture?

### Expected Results

The paper should demonstrate:
1. **Full system discovers 5/5 ground-truth effects**; best ablation discovers ≤3/5
2. **Encoding layer** enables 85%+ cross-type query success vs. ~40% for raw concatenation
3. **Pipeline** compresses 10^18 → ~10 recommendations with zero constraint violations
4. **Revenue impact**: Full system recommendations yield 8–15% simulated revenue improvement vs. 2–5% for siloed approach
5. **Generalization**: Framework discovers planted effects in 2/2 secondary domains

---

## Architecture

### Shared Foundation (src/core/) — BUILD FIRST

- `types.py`: Core type definitions — Lever, KnowledgeSource, Intervention, EvidencePacket, QualityScore. All typed with dataclasses.
- `encoding.py`: The multimodal encoding layer:
  - `StatisticalProfile`: Encodes quantitative data (distribution params, confidence intervals, trend, seasonality decomposition)
  - `ConstraintVector`: Encodes policy knowledge (tiered hard/soft constraints with scope and threshold)
  - `TemporalBelief`: Encodes expert judgment (statement, confidence, decay function, basis, domain mapping)
  - `encode_quantitative(data) → StatisticalProfile`
  - `encode_policy(rule) → ConstraintVector`
  - `encode_expert(belief) → TemporalBelief`
  - `cross_query(query, encoded_sources) → ReasoningResult`: Joint reasoning across encoded types
- `coupling.py`: Lever coupling model — represents pairwise and higher-order interactions between levers as a weighted graph. Methods: `get_coupled_levers(lever)`, `interaction_strength(lever_a, lever_b)`, `propagate_change(lever, direction, magnitude)`.
- `config.py`: All hyperparameters — number of SKUs, stores, weeks, noise levels, agent thresholds, pipeline parameters.
- `utils.py`: Shared utilities — data loading, JSON I/O, logging, random seed management.

### Data Generation (src/data/) — BUILD FIRST (parallel with core)

- `generator.py`: Master data generator that creates the BevCo synthetic scenario.
  - Generates sales transactions with embedded interaction effects
  - Creates price elasticity matrices with noise and bias
  - Produces market share time series with competitor dynamics
  - All 5 ground-truth effects are controllable via config flags
  - Deterministic with seed for reproducibility
- `policies.py`: Generates the policy document (constraints, rules, thresholds)
- `experts.py`: Generates expert belief statements with planted correct/incorrect/conditional signals
- `ground_truth.py`: Defines the 5 ground-truth interaction effects as structured objects. Used for scoring — never exposed to the agents.

### Encoding Layer (src/encoding/) — BUILD AFTER core

- `statistical_profile.py`: Quantitative data → StatisticalProfile
  - Fits distribution (mean, std, skew, kurtosis)
  - Computes confidence intervals
  - Decomposes trend and seasonality (simple moving average + Fourier)
  - Identifies structural breaks (CUSUM-like detection)
  - Outputs a fixed-schema JSON-serializable object
- `constraint_vector.py`: Policy → ConstraintVector
  - Parses rule into: {lever, direction, bound, hardness, scope, interactions}
  - Computes feasible region boundaries per lever
  - Identifies constraint conflicts (mutually exclusive rules)
- `temporal_belief.py`: Expert statement → TemporalBelief
  - Parses natural language into structured lever/direction/magnitude
  - Attaches confidence score with exponential decay from recency
  - Classifies basis quality (analysis > experience > intuition)
  - Flags when belief conflicts with quantitative evidence
- `cross_encoder.py`: Joint reasoning engine
  - Takes a query + all encoded sources
  - Identifies relevant encodings per query
  - Detects cross-source conflicts and concordances
  - Produces a `ReasoningResult` with evidence trail and confidence

### Diagnostic Agents (src/agents/) — BUILD AFTER encoding

**CRITICAL DESIGN PRINCIPLE**: Each diagnostic agent is an **LLM-powered reasoner**, not a deterministic algorithm. The agent receives encoded knowledge as structured context in its prompt, then uses LLM reasoning to analyze patterns, generate hypotheses, and produce evidence packets. This is the core of the paper's argument: the encoding layer transforms heterogeneous knowledge into representations that enable effective LLM reasoning across knowledge types.

#### Why LLM Agents (Not Algorithms)?
The paper's central claim is that the encoding layer enables *reasoning* over coupled decisions with heterogeneous knowledge. If agents are deterministic numpy functions, they don't *reason* — they compute. The encoding layer would be mere data preprocessing, not a reasoning enabler. By using LLM agents:
- The **encoding layer's value** becomes testable: same LLM with encoded vs. raw knowledge → measurable difference in reasoning quality
- The **ablation study** becomes meaningful: "no encoding" means the LLM gets raw data dumps instead of structured representations
- **Cross-source conflicts** become genuine reasoning challenges, not just programmatic comparisons
- The **cognitive assembly bottleneck** (Contribution 1) is directly addressed: LLMs perform the assembly that humans currently do ad-hoc

#### Agent Architecture

Each agent is a standalone module implementing:

```python
class DiagnosticAgent:
    def __init__(self, config, encoded_knowledge, llm_client):
        """Initialize with encoded knowledge and LLM client.
        
        The encoded_knowledge dict contains:
          - 'quantitative': list[StatisticalProfile]  (structured numeric summaries)
          - 'policy': list[ConstraintVector]           (tiered constraint representations)
          - 'expert': list[TemporalBelief]             (confidence-weighted judgment objects)
          - 'coupling': CouplingGraph                  (lever interaction structure)
        
        The llm_client provides:
          - llm_client.reason(system_prompt, user_prompt) -> str
        """
        pass
    
    def diagnose(self) -> list[EvidencePacket]:
        """Build a structured prompt from encoded knowledge, send to LLM,
        parse the LLM's reasoning into typed EvidencePackets."""
        pass
    
    def get_pruned_space(self) -> dict:
        """Return the reduced candidate space from this dimension."""
        pass
```

#### LLM Client Abstraction (src/agents/llm_client.py)

The framework uses **Copilot CLI** as its LLM backend — no API keys needed. Since users already have Copilot authenticated, this is zero-config.

```python
class CopilotLLMClient:
    """LLM reasoning via Copilot CLI subprocess with caching for reproducibility.
    
    Uses `copilot -p <prompt> -s --no-color --allow-all` in non-interactive mode.
    The -s (silent) flag outputs only the agent response, no stats or formatting.
    
    All responses are cached by prompt hash — once experiments run once, 
    subsequent runs replay from cache for perfect reproducibility.
    """
    def __init__(self, cache_dir=".llm_cache", timeout=120):
        """
        cache_dir: directory for cached responses (hash-keyed JSON files)
        timeout: max seconds to wait for Copilot CLI response
        """
    
    def reason(self, system_prompt: str, user_prompt: str) -> str:
        """Combine system+user prompt, send to Copilot CLI, return response.
        
        Implementation:
        1. cache_key = sha256(system_prompt + user_prompt)[:16]
        2. If .llm_cache/{cache_key}.json exists → return cached response
        3. combined = f"{system_prompt}\\n\\n{user_prompt}\\n\\nRespond with ONLY valid JSON."
        4. result = subprocess.run(
               ["copilot", "-p", combined, "-s", "--no-color", "--allow-all"],
               capture_output=True, text=True, timeout=self.timeout
           )
        5. Parse and cache result.stdout
        6. Return response
        """
    
    def reason_structured(self, system_prompt: str, user_prompt: str, schema: dict) -> dict:
        """Same as reason() but appends JSON schema hint and parses response as dict.
        Includes retry logic: if JSON parsing fails, re-prompt with error feedback."""
```

**Why Copilot CLI instead of direct API calls?**
- **Zero configuration**: No API keys, no environment variables — if the user has Copilot CLI installed (they do, since they're running this framework), it just works
- **Model-agnostic**: Copilot CLI routes to whatever model is configured (Claude, GPT-4, etc.) — the framework doesn't need to know or care
- **Authentication handled**: GitHub handles auth, billing, rate limits — the framework is pure application logic
- **Subprocess isolation**: Each agent's LLM call is a clean subprocess with no shared state — agents are truly independent

**Key flags**:
- `-p "<prompt>"` — non-interactive mode, exits after completion
- `-s` / `--silent` — output only the response text, no stats or banners
- `--no-color` — strip ANSI codes for clean parsing
- `--allow-all` — no permission prompts (subprocess would hang otherwise)

**Caching implementation**:
```python
cache_key = hashlib.sha256(f"{system_prompt}\n---\n{user_prompt}".encode()).hexdigest()[:16]
cache_file = self.cache_dir / f"{cache_key}.json"
# Cache stores: {"prompt_hash": str, "system": str, "user": str, "response": str, "timestamp": str}
```

**Fallback mode**: If `copilot` binary is not found in PATH, the client falls back to heuristic-based reasoning (the current numpy/scipy logic). The results section must clearly label which mode was used. Set `LLM_MODE=fallback` in config to force this.

#### How Each Agent Uses the LLM

Each agent follows the same pattern:
1. **Format encoded knowledge into a structured prompt** — this is where encoding matters. The StatisticalProfile becomes a readable summary ("SKU-12 in Region-North: mean revenue $4.2K/week, declining trend -2.1%/week, seasonal peak Q3, structural break at week 67"). The ConstraintVector becomes "Hard constraint: minimum 25% margin on Category A (current: 23.1% — BINDING)". The TemporalBelief becomes "Expert [confidence: 0.8, basis: analysis, age: 3 months]: Premium segment is under-priced."
2. **Ask the LLM a focused analytical question** specific to that agent's dimension
3. **Parse the LLM's structured response** into typed EvidencePacket objects

#### Agent Modules:

- `src/agents/elasticity_agent.py`: **Prompt**: "Given these statistical profiles of SKU-level price sensitivity [encoded data], identify which SKU × region combinations show significant price elasticity. For each, state the direction, magnitude, confidence, and whether cross-price effects suggest substitution or complementarity." **LLM reasons** over the encoded profiles to identify patterns a human analyst would find — but across all 50 SKUs simultaneously.

- `src/agents/interaction_agent.py`: **Prompt**: "Given these statistical profiles [encoded quant data] and this lever coupling structure [from CouplingGraph], identify lever pairs where the joint effect differs from the sum of independent effects. Watch for multi-collinearity (these pairs are correlated: [from encoding]) — distinguish genuine interactions from confounded signals." **LLM reasons** about interaction vs. confounding, which is genuinely hard reasoning that benefits from structured encoding.

- `src/agents/constraint_agent.py`: **Prompt**: "Given these constraint vectors [encoded policies] and these statistical profiles [encoded data showing current state], identify: (1) which constraints are currently binding, (2) which have slack, (3) which pairs of constraints conflict, and (4) which expert beliefs [encoded experts] would violate constraints if followed." **LLM reasons** about constraint feasibility with full cross-source awareness.

- `src/agents/temporal_agent.py`: **Prompt**: "Given these time series profiles [encoded with trend, seasonality, breaks] and these expert beliefs about temporal dynamics [encoded experts with decay], identify: (1) which expert beliefs align with or contradict the data trends, (2) which structural breaks suggest regime changes, (3) which seasonal patterns the experts are correctly or incorrectly accounting for." **LLM reasons** about temporal alignment across quantitative and expert sources.

- `src/agents/portfolio_agent.py`: **Prompt**: "Given these cross-SKU elasticity profiles [encoded data] and pack-price architecture [encoded data], identify: (1) cannibalization pairs where one SKU's gain is another's loss, (2) halo effects where changes cascade positively, (3) portfolio-level effects of assortment changes. Consider the policy constraints [encoded policies] on minimum SKU counts." **LLM reasons** about portfolio-level effects that require synthesizing data and policy knowledge.

#### The Encoding Difference (What the Ablation Tests)

| What the LLM sees | "With Encoding" | "Without Encoding" (ablation) |
|---|---|---|
| Quantitative data | "SKU-12: mean=$4.2K, trend=-2.1%/wk, CI=[3.8K,4.6K], break@wk67" | Raw CSV rows: "12,North,47,4182.3,3.99,1,BOGO,0.3,0,4,6" × 10000 |
| Policy | "HARD: margin≥25% on Cat-A (scope: all regions, binding at 23.1%)" | JSON: {"rule_id":"P3","type":"hard","lever":"pricing",...} |
| Expert belief | "Expert [conf:0.8, analysis, 3mo]: 'Premium under-priced' → direction:increase, magnitude:moderate, CONFLICTS with margin constraint P3 on 9/12 SKUs" | "Premium segment is under-priced relative to market" |

The encoded version gives the LLM *reasoning-ready* representations with cross-references already surfaced. The raw version forces the LLM to do its own parsing, aggregation, and cross-referencing — which it does poorly at scale.

### Causal Synthesis (src/synthesis/) — BUILD AFTER agents

- `assembler.py`: Takes evidence packets from all 5 diagnostic agents and **uses LLM reasoning** to assemble them into candidate interventions. This is the "cognitive assembly" step that the paper argues cannot be done by algorithms alone — it requires reasoning about causal chains across heterogeneous evidence.
  - **Prompt pattern**: "Here are evidence packets from 5 independent diagnostic analyses: [structured evidence]. Identify causal chains: where does an elasticity signal + an interaction effect + no constraint violation combine to suggest a specific intervention? Where do temporal trends support or undermine the evidence? Where do expert beliefs add context that changes the interpretation?"
  - The LLM assembles evidence into `Intervention` objects: {lever, direction, magnitude, scope, mechanism, evidence_trail, confidence}
  - Merges overlapping interventions via LLM-judged similarity
  - Resolves conflicting evidence: the LLM is given the epistemic hierarchy (quantitative > policy > expert) as a system prompt guideline, but can override when confidence-weighted evidence from a "lower" source is compelling — this is genuine reasoning, not a lookup table

### Quality Gate (src/quality/) — BUILD AFTER synthesis

- `gate.py`: Multi-dimensional scoring and filtering of candidate interventions.
  - **Evidence density**: How many independent evidence sources support this intervention? (0–1)
  - **Constraint alignment**: Does this intervention violate any hard constraints? Any soft constraints? (0–1, binary fail on hard violation)
  - **Actionability**: Is the intervention specific enough to implement? (lever + direction + magnitude + scope all specified?) (0–1)
  - **Testability**: Can this intervention be tested in a controlled way? (A/B testable, measurable outcome) (0–1)
  - **Novelty**: Is this a non-obvious finding? (Penalize interventions that any single-lever analysis would find) (0–1)
  - **Composite score**: Weighted combination, with hard-constraint veto
  - Filter to top-K interventions (configurable, default K=10)

### Pipeline Orchestrator (src/pipeline/) — BUILD AFTER all components

- `runner.py`: Orchestrates the full pipeline:
  1. Load and encode all knowledge sources
  2. Run 5 diagnostic agents in sequence (parallel in concept — sequential in implementation for determinism)
  3. Collect evidence packets
  4. Run causal synthesis
  5. Run quality gate
  6. Output final recommendations
  7. Score against ground truth
  
- `ablation.py`: Runs the 4 ablation configurations from Experiment 2. Each disables one component and measures degradation.

### Experiment Runner (src/experiments/) — BUILD AFTER pipeline

- `experiment_1_encoding.py`: Encoding layer validation (fidelity, cross-type queries, conflict detection)
- `experiment_2_ablation.py`: 4-way ablation study
- `experiment_3_pipeline.py`: Progressive reduction measurement (space size at each stage)
- `experiment_4_generalization.py`: Cross-domain mini-experiments (precision medicine + supply chain)
- `run_all.py`: Master runner — generates data, runs all 4 experiments, collects results

### Paper Generator (src/paper/) — BUILD AFTER experiments

- `results_analyzer.py`: Processes experiment outputs into paper-ready statistics, tables, and findings.
- `figure_generator.py`: Produces all paper figures using matplotlib:
  1. **Figure 1**: Problem structure diagram — 3 invariants shown as overlapping constraints on a Venn diagram
  2. **Figure 2**: Encoding layer architecture — flow diagram showing 3 input types → encoded representations → cross-encoder
  3. **Figure 3**: Pipeline architecture — funnel diagram showing progressive reduction (10^18 → 10^3 → 50 → 10)
  4. **Figure 4**: Ablation results — grouped bar chart showing ground-truth discovery rate per configuration
  5. **Figure 5**: Encoding fidelity — information-loss heatmap across knowledge types and encoding dimensions
  6. **Figure 6**: Cross-type query performance — bar chart comparing full system vs. baselines
  7. **Figure 7**: Pipeline compression curve — log-scale plot of candidate space size at each stage
  8. **Figure 8**: Quality gate radar — spider chart showing multi-dimensional scores for top interventions
  9. **Figure 9**: Ground-truth discovery matrix — which effects were found by which configuration
  10. **Figure 10**: Generalization results — side-by-side comparison across 3 domains

- `table_generator.py`: Produces all paper tables as LaTeX:
  1. **Table 1**: Decision domains sharing the 3 structural invariants (RGM, medicine, materials, supply chain, finance)
  2. **Table 2**: Knowledge type encoding summary (input → encoded form → properties preserved)
  3. **Table 3**: Diagnostic agent specifications (agent, analytical dimension, input, output)
  4. **Table 4**: Quality gate dimensions and weights
  5. **Table 5**: Ablation experiment results (full numeric table)
  6. **Table 6**: Top-10 recommended interventions with scores
  7. **Table 7**: Cross-domain generalization results

- `latex_writer.py`: Assembles the full paper as LaTeX:
  - Populates each section from templates + generated content
  - Inserts figures and tables at correct positions
  - Generates bibliography from a curated reference list
  - Produces `output/paper/paper.tex` + `output/paper/figures/*.pdf`
  - Compiles to PDF if `pdflatex` is available

### Paper Sections (templates in src/paper/sections/)

Each section is a template with placeholders for data-driven content:

- `01_introduction.tex`: Motivates the problem, three contributions, paper outline
- `02_problem_characterization.tex`: Formal definition of the 3 invariants, proof that isolation is insufficient
- `03_encoding_layer.tex`: Statistical profiles, constraint vectors, temporal beliefs, cross-encoder
- `04_pipeline.tex`: Diagnostic agents, causal synthesis, quality gate
- `05_experimental_setup.tex`: BevCo scenario, data generation, metrics, baselines
- `06_results.tex`: All 4 experiments with figures and tables (auto-populated from results)
- `07_discussion.tex`: Interpretation, limitations, what the ablation reveals
- `08_generalization.tex`: Cross-domain results and structural conditions for transfer
- `09_conclusion.tex`: Summary, future work
- `appendix_a.tex`: Full implementation details and hyperparameters
- `appendix_b.tex`: Complete ground-truth specification
- `references.bib`: Curated bibliography (30–40 key references)

### Interactive Webapp (output/index.html) — BUILD IN PARALLEL with paper

A single self-contained HTML file that visualizes the framework and experimental results. Opens in any browser, no server needed. Reads `output/results.json`.

**Tech stack**: Vanilla HTML/CSS/JS + Chart.js + D3.js (both via CDN). No React, no build step, no npm. Everything in ONE file.

**Design**: Clean academic aesthetic — white background, navy/teal accent colors, crisp typography (system fonts). Responsive.

#### Section 1: Hero — "The Reasoning Framework"
- Title + subtitle: *"How multi-agent systems navigate coupled decisions with fragmented knowledge"*
- Animated diagram: 5 levers connected by pulsing lines (coupling), 3 knowledge source icons feeding in
- "Explore Results ↓" button

#### Section 2: The Problem — "Three Invariants"
- Interactive Venn diagram (D3.js): 3 overlapping circles for the invariants
- Click each circle to highlight what happens when you address only that invariant
- Shows the ablation results: removing any circle degrades performance
- Below: brief text explanation of each invariant

#### Section 3: The Encoding Layer — "Preserving Epistemic Differences"
- 3-column layout showing each knowledge type's encoding
- Interactive example: click a raw data point → see it encoded → see how it participates in cross-type reasoning
- Conflict detection visualization: when quantitative signal contradicts expert belief, show the diagnostic output
- Encoding fidelity bar chart

#### Section 4: The Pipeline — "From 10^18 to 10"
- Animated funnel diagram showing progressive reduction
- Each stage is clickable → shows the evidence packets / interventions at that stage
- Log-scale compression chart
- Quality gate radar chart for top interventions

#### Section 5: Results — "Head-to-Head"
- Ablation comparison table (interactive, sortable)
- Ground-truth discovery matrix (heatmap: rows = configurations, columns = effects)
- Revenue impact comparison (bar chart)
- Toggle between domains (RGM, medicine, supply chain)

#### Section 6: Discovery — "Build Your Own Pipeline"
- Toggle panel: enable/disable each pipeline component
  - ☑ Encoding Layer ☑ Coupling Model ☑ Diagnostic Agents ☑ Causal Synthesis ☑ Quality Gate
- As you toggle, the results update from pre-computed ablation data
- Shows which ground-truth effects are found/missed with your configuration
- "Your configuration discovers X/5 effects and produces Y constraint violations"

#### Section 7: Conclusion
- Key findings as numbered bullet points with bold stats
- Link to download the generated paper PDF
- "Run it yourself" call to action

#### Fallback behavior
- If `results.json` not found, show placeholder with instructions
- Charts degrade to static images if JS is disabled

---

## Data Outputs

### output/results.json

```json
{
  "scenario": {
    "name": "BevCo Revenue Growth Management",
    "skus": 50,
    "stores": 200,
    "weeks": 104,
    "levers": ["pricing", "promotion", "assortment", "distribution", "pack_price"],
    "knowledge_sources": ["quantitative", "policy", "expert"],
    "decision_space_size": "~10^18"
  },
  "experiments": {
    "encoding_validation": {
      "fidelity_scores": {"quantitative": 0.95, "policy": 0.99, "expert": 0.82},
      "cross_type_query_success": {"full_system": 0.87, "raw_concatenation": 0.41, "llm_baseline": 0.52},
      "conflicts_detected": 4,
      "conflicts_total": 5
    },
    "ablation": {
      "full_system": {"effects_found": 5, "precision": 0.89, "recall": 0.92, "violations": 0, "revenue_impact": 0.12},
      "no_coupling": {"effects_found": 2, "precision": 0.71, "recall": 0.40, "violations": 2, "revenue_impact": 0.04},
      "no_encoding": {"effects_found": 3, "precision": 0.62, "recall": 0.60, "violations": 1, "revenue_impact": 0.07},
      "no_pipeline": {"effects_found": 3, "precision": 0.45, "recall": 0.55, "violations": 3, "revenue_impact": 0.05}
    },
    "pipeline_reduction": {
      "stage_0_input": 1e18,
      "stage_1_diagnostic": 1247,
      "stage_2_synthesis": 48,
      "stage_3_quality_gate": 10,
      "ground_truth_coverage_per_stage": [1.0, 1.0, 1.0, 1.0]
    },
    "generalization": {
      "precision_medicine": {"effects_found": 1, "effects_total": 1, "pipeline_functional": true},
      "supply_chain": {"effects_found": 1, "effects_total": 1, "pipeline_functional": true}
    }
  },
  "top_interventions": [
    {
      "rank": 1,
      "lever": "pricing+promotion",
      "direction": "reduce_base_price+eliminate_promo",
      "scope": "Category A, all regions",
      "mechanism": "Price-promotion trap resolution",
      "quality_score": 0.94,
      "evidence_density": 0.91,
      "constraint_alignment": 1.0,
      "revenue_impact": "+12%"
    }
  ],
  "discovery_text": "..."
}
```

### output/paper/

- `paper.tex` — Main LaTeX document
- `paper.pdf` — Compiled PDF (if pdflatex available)
- `figures/fig1_problem_structure.pdf` through `figures/fig10_generalization.pdf`
- `tables/` — Generated LaTeX table fragments

### output/data/

- `sales_transactions.csv`
- `price_elasticity.csv`
- `market_share.csv`
- `policies.json`
- `expert_beliefs.json`

---

## File Scope per Agent

- **Agent core**: src/__init__.py, src/core/__init__.py, src/core/types.py, src/core/encoding.py, src/core/coupling.py, src/core/config.py, src/core/utils.py
- **Agent data**: src/data/__init__.py, src/data/generator.py, src/data/policies.py, src/data/experts.py, src/data/ground_truth.py
- **Agent encoding**: src/encoding/__init__.py, src/encoding/statistical_profile.py, src/encoding/constraint_vector.py, src/encoding/temporal_belief.py, src/encoding/cross_encoder.py
- **Agent elasticity**: src/agents/__init__.py, src/agents/llm_client.py, src/agents/elasticity_agent.py
- **Agent interaction**: src/agents/interaction_agent.py
- **Agent constraint**: src/agents/constraint_agent.py
- **Agent temporal**: src/agents/temporal_agent.py
- **Agent portfolio**: src/agents/portfolio_agent.py
- **Agent synthesis**: src/synthesis/__init__.py, src/synthesis/assembler.py
- **Agent quality**: src/quality/__init__.py, src/quality/gate.py
- **Agent pipeline**: src/pipeline/__init__.py, src/pipeline/runner.py, src/pipeline/ablation.py
- **Agent experiments**: src/experiments/__init__.py, src/experiments/experiment_1_encoding.py, src/experiments/experiment_2_ablation.py, src/experiments/experiment_3_pipeline.py, src/experiments/experiment_4_generalization.py, src/experiments/run_all.py
- **Agent paper**: src/paper/__init__.py, src/paper/results_analyzer.py, src/paper/figure_generator.py, src/paper/table_generator.py, src/paper/latex_writer.py, src/paper/sections/*.tex, src/paper/references.bib
- **Agent webapp**: output/index.html

## Technical Requirements

- Python 3.11+
- stdlib + matplotlib + numpy + scipy for computation
- **Copilot CLI** (`copilot` binary in PATH) for LLM-powered agent reasoning — no API keys or additional LLM libraries needed
- **LLM-powered agents**: Diagnostic agents and causal synthesis use Copilot CLI (`copilot -p <prompt> -s --no-color --allow-all`) in non-interactive subprocess mode. Each call is a clean subprocess — no shared state between agents.
- **Response caching**: All LLM calls are cached by prompt hash in `.llm_cache/`. Once experiments run once, subsequent runs replay from cache — making results deterministic and reproducible with zero additional LLM calls.
- **Fallback mode**: If `copilot` is not in PATH or `LLM_MODE=fallback` is set in config, agents fall back to heuristic-based reasoning (numpy/scipy). Results section must clearly label which mode was used. The fallback exists so the codebase can be tested without Copilot CLI, but the paper's primary results MUST use LLM mode.
- Each agent module is self-contained (no cross-agent imports, only imports from src/core/)
- Webapp is a single HTML file using Chart.js + D3.js via CDN
- Paper compiles with standard pdflatex + bibtex
- Total codebase under 6000 lines (Python) + ~600 lines (HTML/JS) + ~2000 lines (LaTeX)
- Full experiment should complete in under 30 minutes on a modern CPU (first run with LLM calls; <5 minutes from cache)

## Dependency Graph

```
Wave 1: core + data (foundation — parallel)
Wave 2: encoding (needs core types)
Wave 3: elasticity + interaction + constraint + temporal + portfolio (5 agents — parallel, need encoding)
Wave 4: synthesis (needs all agents)
Wave 5: quality (needs synthesis)
Wave 6: pipeline (needs quality — orchestrates everything)
Wave 7: experiments (needs pipeline)
Wave 8: paper + webapp (parallel — need experiment results)
```

## Success Criteria

The experiment succeeds if:
1. **Full system discovers 5/5 planted ground-truth effects**; best ablation ≤ 3/5
2. **Encoding layer** achieves ≥80% cross-type query accuracy vs. ≤50% for baselines
3. **Pipeline** reduces 10^18 → ≤15 recommendations with **zero hard-constraint violations**
4. **Ablation** clearly shows each invariant is necessary — removing any one degrades at least 2 metrics
5. **Generalization** works on 2/2 secondary domains with same pipeline architecture
6. **Paper** compiles to PDF with all figures, tables, and sections populated from real experimental data
7. **Webapp** opens in browser and displays all interactive sections with real experiment data
8. **"Build Your Own Pipeline"** toggle shows different results for different component combinations
