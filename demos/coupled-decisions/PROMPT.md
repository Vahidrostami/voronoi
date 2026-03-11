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

## Core Hypothesis

**Structured encoding of heterogeneous knowledge (statistical profiles, typed constraints, temporal belief objects, process graphs) enables an LLM to discover cross-lever effects that it misses when the same information is presented as plain text.**

---

## Experimental Design (The Only Thing You Cannot Get Wrong)

### The Four-Level Encoding Ablation

All levels receive the **same N=500 row sample** and **all four knowledge sources** (data, policies, expert beliefs, playbook). Only encoding quality varies:

| Level | Data | Knowledge | Playbook |
|-------|------|-----------|----------|
| 1. Naive RAG | Markdown table of raw rows (NO pre-computation) | Bullets + prose | Prose |
| 2. +Stats | Statistical profiles (numpy/scipy) | Bullets + prose | Prose |
| 3. +Typed | Statistical profiles | Constraint vectors + temporal belief objects | Prose |
| 4. Full | Statistical profiles | Typed constraints + beliefs | Process graphs + rule catalog + technique registry |

This is the paper's primary experiment — allocate the most effort here. Run on enough scenarios for ≥0.80 statistical power to detect d=1.0 effects.

### Planted Effects Must Be Encoding-Sensitive

Effects must be designed to **mislead at L1 but resolve at L4**. Categories that achieve this:
- **Simpson's paradox**: Aggregate tells one story; segment-level tells the opposite
- **Confounded coupling**: Spurious correlation from shared temporal confound; detrending resolves it
- **Constraint-boundary effects**: Data says go, a hard constraint says stop
- **Decayed beliefs**: Expert was right historically, data has shifted
- **Nonlinear segment interactions**: Effect exists only in a sub-population

**Calibration**: ~50-70% discoverable at L4, ~20-40% at L1. If L1 finds everything or L4 finds nothing, redesign. You decide how many scenarios, how many effects per scenario, and the exact magnitudes — but the planted effects must produce measurable differentiation between encoding levels.

### Secondary Experiments

- **Cross-source reasoning**: At L4, vary which sources are included (data-only → all). If data-only matches all-sources on recall, the planted effects are too easy — redesign.
- **Playbook reasoning**: Process selection accuracy across question types. Target ≥80%.
- **Pipeline compression**: Quantify space reduction at each stage.
- **Generalization**: Brief qualitative discussion of 1-2 other domains. No deep experiments.

---

## Critical Constraints (These Caused Previous Failures — Do Not Violate)

### 1. DO NOT TRUNCATE CONTEXT

**NEVER truncate or cap the encoded context sent to the LLM.** If you truncate all levels to the same character limit, you destroy the experimental variable. If context is too long, reduce N — but keep N identical across all levels for a given scenario.

### 2. DO NOT LEAD THE DISCOVERY PROMPT

**NEVER list the effect categories you want the LLM to find.** The discovery prompt must be open-ended: "Analyze this context and identify all noteworthy findings about cross-lever effects, anomalies, contradictions, and risks." If you say "look for Simpson's paradox, confounders, constraint violations..." it will list all of them regardless of evidence.

### 3. MATCH FINDINGS TO GROUND TRUTH INDIVIDUALLY

**NEVER evaluate by checking if returned effect-type strings overlap ground-truth type strings.** That metric cannot differentiate encoding levels. Instead:
- LLM judge call for each (finding, ground-truth-effect) pair → binary match verdict with justification
- "There might be a Simpson's paradox somewhere" does NOT match the specific planted effect in Scenario 1
- Precision = (findings matching a GT effect) / (total findings)
- Recall = (GT effects matched by ≥1 finding) / (total GT effects)
- Aggregate per-scenario, then report means and CIs across scenarios

### 4. SINGLE EXPERIMENT RUNNER

One entry point: `run_experiments.py`. No duplicates.

### 5. LLM ROUTING

All reasoning through `copilot -p "<prompt>" -s --no-color --allow-all`. Cache by prompt hash in `.llm_cache/`. No heuristic fallbacks — any judgment call without an LLM invocation is a bug. Identify the model at startup and record in `results.json` under `"model"`.

---

## What Agents Decide (Do Not Over-Specify)

The orchestrator and worker agents own all implementation decisions. The PROMPT.md specifies **what to prove**, not **how to build it**. Specifically, agents decide:

- Number of scenarios, rows per scenario, stores, SKUs, levers, rules, beliefs, queries — sized for adequate statistical power
- Exact encoding representations (what goes into a "statistical profile" or "constraint vector")
- Number and specialization of diagnostic agents in the pipeline
- The causal synthesis mechanism
- Quality gate scoring dimensions (the abstract names five: evidence density, constraint alignment, actionability, testability, novelty)
- Paper narrative arc, related work selection, figure design
- Webapp layout and visualization choices

---

## Technical Stack

- Python 3.11+, numpy, scipy, matplotlib (no ML frameworks, no pip install openai/anthropic)
- Copilot CLI mandatory for all LLM calls
- Complete in <60 min first run, <5 min from cache

---

## Deliverables

```
demos/coupled-decisions/
  output/
    results.json          # "model" key + per-scenario per-level metrics + aggregate stats
    index.html            # Interactive single-file webapp
    data/                 # Synthetic data + ground_truth.json (NEVER loaded by reasoning system)
    paper/
      paper.tex + paper.pdf + figures/ + references.bib
  src/                    # Pipeline source
  run_experiments.py      # Single entry point
  .llm_cache/             # Prompt-hash cache
```

---

## Success Criteria

1. **Encoding layer matters** — L4 statistically significantly outperforms L1 on precision and recall of planted effect discovery
2. **Cross-source reasoning works** — more knowledge sources → more discovered effects; data-only misses planted cross-source effects
3. **Pipeline compresses effectively** — combinatorial space reduced by ≥10x
4. **Problem characterization is rigorous** — three invariants formally defined, partial approaches shown incomplete
5. **Paper is complete** — compiles, figures from actual results, all abstract claims substantiated, honest limitations section
6. **All claims backed** by effect sizes and confidence intervals

---

## Cleanup Requirements

When the demo run completes:
- Delete ALL agent branches (local and remote), remove all worktrees, prune, kill tmux sessions
- `.llm_cache/` MAY be preserved for reproducibility
- Verify: `git branch -a | grep agent` returns nothing, `git worktree list` shows only main worktree
