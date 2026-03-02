# Navigating Coupled Decision Spaces with Fragmented and Heterogeneous Knowledge: A System of Agents for Reasoning

Build a multi-agent system that reasons over coupled decision levers using heterogeneous knowledge sources, validate it experimentally against planted ground truth, and write a complete academic paper with the results.

---

## The Research Problem

A broad class of applied decision problems share three structural invariants:

1. **Lever Coupling**: Adjusting one decision variable alters the optimal configuration of others. Independent optimization is invalid.
2. **Knowledge Heterogeneity**: The information needed to navigate the space is fragmented across sources with incompatible semantics — quantitative measurements, codified rules, and expert judgment.
3. **Cognitive Assembly Bottleneck**: No single source or analysis is sufficient. Someone (or something) must synthesize across all sources to reach sound decisions. Today this is done ad-hoc by humans.

**The thesis**: A system of LLM-powered agents, given knowledge that has been encoded to preserve epistemic differences across types, can perform this cognitive assembly — discovering interaction effects that siloed analysis misses.

**Your job**: Design and build such a system, then prove it works.

---

## The Experimental Scenario: "BevCo"

A simulated beverage company. This is your testbed — the data is synthetic with **known ground truth** so you can measure whether your system actually discovers what's planted.

### Scale
- 50 SKUs across 5 categories (A–E)
- 200 retail stores in 4 regions
- 104 weeks (2 years) of data
- ~1M transaction rows

### The 5 Commercial Levers

| Lever | Variables | Range | Key Couplings |
|-------|-----------|-------|---------------|
| **Pricing** | Base price per SKU per region | $0.50–$8.00 | Promotion (discount depth), pack-price (per-unit economics) |
| **Promotion** | Type × frequency × depth per SKU | 12 types × 0–4/month × 10–50% off | Pricing (margin erosion), distribution (display allocation) |
| **Assortment** | SKU inclusion per store cluster | Binary per SKU × 20 clusters | Distribution (shelf space), pricing (portfolio margin) |
| **Distribution** | Coverage × shelf facings × display | Coverage %, 1–8 facings, display binary | Assortment (space allocation), promotion (display lift) |
| **Pack-Price Architecture** | Pack sizes × price points per SKU | 3–6 sizes, price ladders | Pricing (cannibalization), assortment (portfolio coherence) |

**Total naive decision space**: ~10^18 combinations.

### Planted Ground-Truth Effects (5 total)

These are embedded in the synthetic data. Your system should discover them; siloed analysis should miss them.

1. **Price-Promotion Trap**: Category A SKUs show positive promo ROI when analyzed independently, but a 5% base-price reduction with no promotions yields 12% higher net revenue. The promo effect is an artifact of subsidizing price-insensitive loyal customers.

2. **Assortment-Distribution Synergy**: Removing 8 low-velocity SKUs frees shelf space that, when reallocated to top SKUs, increases category revenue by 9%. Neither lever alone works — assortment change alone loses 3%, distribution change alone gains only 2%.

3. **Pack-Price Cannibalization Mask**: A 12-pack at $9.99 appears to grow volume +15%, but cannibalizes the 6-pack at $5.99 by 22%, net destroying $0.43/unit margin. Only visible when pack-price and pricing data are analyzed jointly.

4. **Cross-Source Signal**: Quantitative data shows declining Category B sales. Policy mandates 30% shelf share for Category B. Expert says "Category B decline is seasonal, will reverse in Q3." The correct intervention requires synthesizing all three sources — no single source gives the right answer.

5. **Constraint-Coupling Conflict**: An expert recommends aggressive premium pricing, but policy constrains minimum margin at 25%. The correct answer: the expert is directionally right but must be scoped to only 3 of 12 premium SKUs where margin headroom exists.

### Three Knowledge Sources

**Source 1 — Quantitative Data (Numerical)**
- `sales_transactions.csv`: ~1M rows (week, store_id, sku_id, region, category, units_sold, revenue, price_paid, promo_flag, promo_type, promo_depth, display_flag, facings, pack_size)
- `price_elasticity.csv`: Own-price and cross-price elasticities per SKU pair per region. Include noise (σ=0.15) and systematically biased estimates.
- `market_share.csv`: Weekly category-level market share by region with competitor effects.

**Planted multi-collinearity** (realistic — levers rarely move independently):
- Price–Promotion: ρ ≈ –0.6 (deeper promos correlate with higher base prices)
- Assortment–Distribution: ρ ≈ 0.5 (more SKUs → fewer facings per SKU)
- Promotion–Display: ρ ≈ 0.7 (promoted SKUs get display placement — confounding)
- Pack-Size–Price: ρ ≈ 0.85 (larger packs → lower per-unit price — near-linear)

**Source 2 — Policy Knowledge (Codified Rules)**
- `policies.json`: ~15 rules, each with: `{rule_id, type: "hard"|"soft", lever, scope, threshold, rationale}`
- Includes: minimum margin thresholds (hard), max promo frequency (soft), shelf space minimums (hard), pricing corridor rules, brand portfolio rules

**Source 3 — Expert Judgment (Qualitative)**
- `expert_beliefs.json`: 15–20 statements, each with: `{statement, confidence: 0.0–1.0, recency: date, domain: [levers], basis: "experience"|"analysis"|"intuition"}`
- Mix of correct, outdated/wrong, and conditionally-correct beliefs

---

## What to Build

### 1. Data Generator
Generate the synthetic BevCo scenario with all 5 ground-truth effects and multi-collinearity structures embedded. Deterministic with seed. The ground truth definitions must be kept separate and never exposed to the reasoning agents.

### 2. Multi-Agent Reasoning System

**This is the core design problem.** Build a system of LLM-powered agents that:
- Transforms the three knowledge sources into representations suitable for LLM reasoning
- Analyzes the coupled decision space using one or more reasoning agents
- Produces a ranked set of recommended interventions

**Design decisions that are YOURS to make:**
- How to encode/represent each knowledge type for LLM consumption
- How many agents, what each one does, and how they're specialized
- Whether and how agents communicate with each other
- How to structure the reasoning pipeline (single-pass, multi-round, debate, etc.)
- How to synthesize agent outputs into final recommendations
- How to score and filter recommendations

**Constraints you MUST satisfy:**
- Agents must use Copilot CLI for all LLM reasoning: `copilot -p "<prompt>" -s --no-color --allow-all`
- All LLM calls must be cached by prompt hash in `.llm_cache/` for reproducibility
- If `copilot` is not available, fall back to heuristic-based reasoning (numpy/scipy) so experiments can still run. Label which mode produced results.
- Only stdlib + numpy + scipy + matplotlib (no ML frameworks, no direct LLM API libraries)
- The system must reduce ~10^18 combinations to ≤15 recommendations with zero hard-constraint violations

### 3. Experiments

Run these four experiments. How you implement them is up to you — what matters is the measurements.

**Experiment 1: Encoding Validation**
Does your knowledge encoding help LLM agents reason better than raw data?
- Design 20 queries requiring reasoning across 2+ knowledge types
- Measure: your encoding vs. raw data concatenation vs. single LLM call with everything
- Measure: how many of the 5 planted cross-source conflicts does the system detect?

**Experiment 2: Ablation Study**
Which components of your system are necessary? Run at least these configurations:
- **Full system**: everything you built
- **No encoding**: agents get raw CSV/JSON/text instead of your encoded representations
- **No coupling awareness**: agents analyze levers independently
- **No multi-agent pipeline**: single LLM call with all information

For each: effects discovered (out of 5), precision/recall vs. ground truth, constraint violations, simulated revenue impact.

**The key validation**: Full system must discover ≥4/5 effects. Removing any major component must degrade to ≤3/5.

**Experiment 3: Progressive Reduction**
How does your system compress the decision space at each stage? Measure the candidate count and ground-truth coverage at each step of your pipeline.

**Experiment 4: Cross-Domain Generalization**
Apply your same architecture (not just your code — your design pattern) to two mini-domains:
- **Precision Medicine**: 3 coupled treatment levers (drug, dose, timing), 100 synthetic patients, 1 planted cross-lever effect
- **Supply Chain**: 3 coupled levers (sourcing, inventory, routing), 50 synthetic nodes, 1 planted effect

Must discover the planted effect in each using the same pipeline architecture.

### 4. Academic Paper

Write a complete LaTeX paper with:
- **Sections**: Introduction, Problem Characterization (the 3 invariants), Your Method (encoding + agents + pipeline), Experimental Setup, Results (all 4 experiments), Discussion, Generalization, Conclusion
- **Figures** (generated from real results): architecture diagram, ablation comparison, pipeline compression, encoding fidelity, quality scores, generalization comparison, and others as appropriate
- **Tables**: ablation results, top interventions, generalization results, and others as appropriate
- **Bibliography**: 30–40 relevant references
- Compile to PDF if pdflatex is available

### 5. Interactive Webapp

Single self-contained HTML file (Chart.js + D3.js via CDN). Must include:
- Visualization of the framework architecture
- Interactive ablation comparison (toggle components on/off, see effect on results)
- Pipeline compression visualization
- Results from all experiments
- Reads `output/results.json`, graceful fallback if missing

---

## Success Criteria

The system succeeds if:

1. **Full system discovers ≥4/5 planted ground-truth effects**; best ablation discovers ≤3/5
2. **Encoding matters**: ≥80% cross-type query accuracy with encoding vs. ≤50% without
3. **Space reduction**: 10^18 → ≤15 recommendations with zero hard-constraint violations
4. **Ablation is clear**: removing any major component degrades at least 2 metrics
5. **Generalization**: discovers planted effects in 2/2 secondary domains
6. **Paper**: compiles to PDF with all figures/tables populated from real experimental data
7. **Webapp**: opens in browser with interactive results
8. **Architecture justification**: the paper explains WHY the chosen architecture works, not just that it does

---

## Technical Constraints

- Python 3.11+
- Only stdlib + matplotlib + numpy + scipy (no ML frameworks, no pip install openai/anthropic)
- **Copilot CLI** (`copilot` in PATH) for all LLM reasoning — no API keys needed
- All LLM calls cached in `.llm_cache/` by prompt hash for reproducibility
- Heuristic fallback if copilot unavailable (must label results accordingly)
- Deterministic from cache (first run hits LLM, subsequent runs replay)
- Full experiment should complete in <30 minutes first run, <5 minutes from cache
- Paper compiles with standard pdflatex + bibtex
- Webapp is a single HTML file, no build step

---

## Output Structure

```
output/
  results.json          # All experiment results (format: your design)
  paper/
    paper.tex           # Main LaTeX document
    paper.pdf           # Compiled PDF (if pdflatex available)
    figures/            # Generated figure PDFs
    tables/             # Generated LaTeX table fragments
  index.html            # Interactive webapp
  data/                 # Generated synthetic data files
```

---

## What This Prompt Does NOT Specify (Intentionally)

The following are **design decisions for the system to make**, not for this prompt to dictate:

- ❌ Number of agents or what each one analyzes
- ❌ Agent communication pattern (independent, shared memory, debate, hierarchical)
- ❌ Exact encoding representations (StatisticalProfile, ConstraintVector, etc.)
- ❌ Class hierarchy or interface definitions
- ❌ File/module structure within `src/`
- ❌ Pipeline stage count or architecture
- ❌ Prompt templates for LLM agents
- ❌ Quality scoring dimensions or weights
- ❌ Synthesis algorithm
- ❌ How agents specialize across analytical dimensions

The architecture is part of the contribution. The paper must justify the design choices by showing they lead to the experimental results.
