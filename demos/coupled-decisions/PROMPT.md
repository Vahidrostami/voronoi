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

## Research Quality Standards

This is a paper, not a software demo. Every section must meet academic standards:

### Problem Characterization (Contribution 1)
- Formally define each structural invariant with mathematical precision
- Prove (constructively or by counterexample) that approaches addressing any single invariant in isolation are incomplete — this is a core theoretical claim
- Survey existing approaches and show where each falls short against the three invariants (this becomes your Related Work)
- The characterization must be domain-independent; the invariants should be recognizable in any coupled-decision domain

### Encoding Layer (Contribution 2)
- Design representations for each knowledge type that are machine-readable yet preserve native semantics
- The key insight to validate: conflicts between knowledge sources become *diagnostic signals* rather than noise. Design experiments that demonstrate this
- **Head-to-head baseline — raw table dump**: The strongest skeptic objection is "why not just paste the CSV into an LLM prompt?" You MUST include a baseline that serializes the same data as a plain numeric table (CSV/markdown) and sends it to the same LLM with an equivalent task prompt. Compare against your structured encoding on identical scenarios. If your encoding doesn't clearly win, the contribution is not established.
- **Encoding ablation ladder**: Test at least these representation strategies, all using the same LLM and prompt structure:
  1. *Raw table dump* — flat CSV / markdown table of numbers, no semantic annotation
  2. *Narrated table* — raw numbers plus natural-language column descriptions
  3. *Type-collapsed encoding* — all knowledge types forced into a single representation (e.g., everything as text, or everything as feature vectors)
  4. *Full structured encoding* — your proposed statistical profiles + constraint vectors + temporal belief objects
- For each level, measure: (a) discovery precision/recall of planted cross-lever effects, (b) frequency of hallucinated or spurious effects, (c) ability to detect conflicts between knowledge sources, (d) quality of causal mechanism explanations
- Report pairwise effect sizes (Cohen's d or equivalent) with 95% CIs between each adjacent rung and between raw-table-dump vs full-encoding
- Show at least one scenario where the raw table dump *actively misleads* the LLM (e.g., Simpson's paradox, confounded correlation, unit mismatch) while the structured encoding surfaces the correct interpretation
- Show that collapsing knowledge types into a single representation (e.g., converting everything to text, or everything to numbers) loses critical information

### Progressive Pipeline (Contribution 3)
- The pipeline must demonstrably compress a combinatorial space by orders of magnitude
- Each stage must be independently evaluable — you should be able to measure what each stage contributes
- Final outputs should be structured interventions (not just "raise price") — specify lever, direction, magnitude, scope, mechanism, and supporting evidence

### Experimental Validation
Design experiments that are *genuinely convincing* to a skeptical reviewer. At minimum:

- **Ablation**: Remove each major component and show degradation. The full system must meaningfully outperform every ablated variant
- **Encoding fidelity (primary experiment)**: Run the full encoding ablation ladder (raw table → narrated table → type-collapsed → full encoding) on identical synthetic scenarios. This is the paper's most critical experiment — allocate the most scenarios and the most careful analysis here. The full encoding must statistically significantly outperform the raw table dump on at least precision, recall, and hallucination rate.
- **Cross-source reasoning**: Show that the system discovers effects that require synthesizing multiple knowledge types — and that siloed analysis misses them
- **Space reduction**: Quantify compression at each pipeline stage
- **Generalization** *(secondary, brief)*: Sketch applicability to 1–2 additional domains to show the architecture is not RGM-specific, but keep this concise — a short qualitative discussion is sufficient. Do not invest significant experimental effort here.

For all experiments: report effect sizes, confidence intervals, and statistical tests. Negative or weak results must be reported honestly.

### Synthetic Data
You must generate your own synthetic data with *planted ground truth* so you can rigorously measure discovery performance. Design the data to be:
- **Realistic**: Reflect actual characteristics of the domain (correlations, noise, missing data, confounders)
- **Challenging**: Include effects that require cross-lever and cross-source reasoning to discover
- **Measurable**: Every planted effect has a known ground-truth magnitude so you can compute precision/recall
- **Non-trivial**: A naive approach (analyzing each lever independently) must fail to discover at least some effects. This is how you prove coupling matters.

Keep the ground-truth specification completely separate from the reasoning system. The system must never see the answer key.

### Paper Writing
- Full LaTeX paper: Introduction, Related Work, Problem Characterization, Method, Experimental Setup, Results, Discussion, Limitations, Conclusion
- All figures generated from real experimental output — no hand-drawn mockups
- Bibliography: 30–40 references covering combinatorial optimization, multi-agent systems, knowledge representation, the application domain, and LLM-based reasoning
- Honest limitations section — what the system cannot do, where validation was weak, what assumptions might not hold
- Compile to PDF if pdflatex is available

---

## Technical Constraints

- Python 3.11+
- Only stdlib + matplotlib + numpy + scipy (no ML frameworks, no pip install openai/anthropic)
- **Copilot CLI is mandatory** for all LLM reasoning: `copilot -p "<prompt>" -s --no-color --allow-all`. The system MUST use Copilot — there is no heuristic fallback. If `copilot` is not in PATH, the pipeline should fail immediately with a clear error message rather than silently degrading.
- All LLM calls cached in `.llm_cache/` by prompt hash for reproducibility. First run hits the LLM; subsequent runs replay from cache.
- Full pipeline should complete in <30 minutes first run, <5 minutes from cache
- Paper compiles with standard pdflatex + bibtex

---

## Deliverables

All output MUST be written under `demos/coupled-decisions/`, NOT the repository root.

```
demos/coupled-decisions/
  output/
    results.json            # All experimental results
    validation_report.json  # Validation gate verdicts and audit trail
    paper/
      paper.tex
      paper.pdf             
      figures/
      tables/
    index.html              # Interactive webapp (single HTML, Chart.js + D3.js via CDN)
    data/                   # Generated synthetic data
  src/                      # All source code
```

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
2. **The encoding layer matters** — reasoning with encoded representations significantly outperforms reasoning with raw data
3. **Cross-source reasoning works** — the system discovers effects that require synthesizing multiple knowledge types, and siloed analysis misses them
4. **The pipeline compresses effectively** — a combinatorial space is reduced by orders of magnitude to a tractable set of interventions with zero hard-constraint violations
5. **Ablation is convincing** — removing any major component produces measurable degradation
6. **Generalization is plausible** — a brief discussion argues the architecture applies beyond RGM, but deep multi-domain experiments are not required
7. **Results are validated** — all claims pass statistical audit, methodology critique, and adversarial review before appearing in the paper
8. **Limitations are honest** — the paper reports what didn't work, what was weak, and what assumptions might not hold

---

## Cleanup Requirements

When the demo run completes (whether successfully or not):
- Delete ALL local and remote agent branches (`agent-*` pattern)
- Remove ALL git worktrees created during the run; run `git worktree prune`
- Kill any tmux sessions/windows created for agents
- `.llm_cache/` MAY be preserved for reproducibility
- Verify: `git branch -a | grep agent` returns nothing, `git worktree list` shows only main worktree
