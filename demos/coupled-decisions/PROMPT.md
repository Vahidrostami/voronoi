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

### Abstract Claim Coverage — How Each Claim Is Substantiated

The abstract makes three contribution claims. Each must map to a specific paper section:

1. **Three structural invariants + single-invariant insufficiency.** The paper's Problem Characterization section must formally define lever coupling, knowledge heterogeneity, and the cognitive assembly bottleneck. It must then show — via **one constructive example per invariant** — that addressing any single invariant alone fails. E.g.: "Solving only coupling (ignoring heterogeneity) means a joint optimizer that can't parse constraint conflicts; solving only heterogeneity (ignoring coupling) means well-encoded but independently-optimized levers that miss interaction effects." This is a logical argument with illustrative examples, not an experiment.

2. **Multimodal encoding layer.** Substantiated by the L1→L4 ablation experiment (SC1) and cross-source experiment (SC2).

3. **Progressive space-reduction pipeline.** Substantiated by the pipeline compression experiment (SC3), plus architecture validation (SC7).

---

## Core Hypothesis

**Structured encoding of heterogeneous knowledge (statistical profiles, typed constraints, temporal belief objects, process graphs) enables an LLM to discover cross-lever effects that it misses when the same information is presented as plain text.**

**Scope:** This experiment tests **context encoding quality**, not retrieval. All encoding levels receive the same complete information — retrieval is held constant. The independent variable is how that information is represented in the agent's context window. L1 is "everything retrieved, nothing structured"; L4 is "everything retrieved, fully structured."

---

## Experimental Design (The Only Thing You Cannot Get Wrong)

### Mandatory Execution Phases (SEQUENTIAL — no skipping)

**Phase 1 MUST complete before Phase 2. Phase 2 MUST complete before Phase 3.**

#### Phase 1: Data Generation + Pilot Calibration

Generate data for **2 pilot scenarios** only. Run L1 and L4 only. Compute recall and F1.

**PRODUCES (artifact contracts — merge blocked without these):**
- `output/data/pilot_ground_truth.json`
- `output/pilot_results.json` — must contain `pilot_recall_l1`, `pilot_recall_l4`, `pilot_f1_l1`, `pilot_f1_l4`
- `output/encoding_hashes.json` — SHA-256 of the full LLM input at each encoding level, all 4 must differ

**Phase 1 HARD GATE — ALL must pass before Phase 2 begins:**
1. `recall_l4 > recall_l1` by ≥10 percentage points
2. `recall_l1 ≤ 0.40`
3. `recall_l4 ≥ 0.50`
4. All 4 encoding-level input hashes are distinct (no collapsed conditions)
5. Character count of L4 input > character count of L1 input

If ANY criterion fails: **STOP. Diagnose. Create a REVISE task.** Common fixes:
- If L1 ≈ L4 recall → planted effects are not encoding-sensitive. Add more Simpson's paradoxes, increase noise, make confounders subtler
- If L4 recall < 0.50 → effects are too hard. Increase signal magnitude
- If encoding hashes collide → encoding implementation is broken. Fix the encoder
- If L1 > L4 → the structured encoding is confusing the LLM or raw text accidentally leaks structure. Verify L1 truly sends raw CSV text with NO pre-computation

Report calibration results:
```bash
bd update <id> --notes "CALIBRATION_TARGET:recall_l4=[0.50, 0.70]"
bd update <id> --notes "CALIBRATION_TARGET:recall_l1=[0.20, 0.40]"
bd update <id> --notes "CALIBRATION_ACTUAL:recall_l4=<value>"
bd update <id> --notes "CALIBRATION_ACTUAL:recall_l1=<value>"
```

#### Phase 2: Full Experiment

Generate all scenarios (you decide how many — sized for ≥0.80 power to detect d=1.0). Run all 4 encoding levels across all scenarios.

**PRODUCES:**
- `output/results.json` — per-scenario per-level metrics + aggregate stats + `"model"` key
- `output/calibration_check.json` — pass/fail for each success criterion with evidence

**Phase 2 HARD GATE:**
1. L4 F1 > L1 F1 with p < 0.05 (primary success criterion)
2. If NOT met: flag `DESIGN_INVALID`, file `RESULT_CONTRADICTS_HYPOTHESIS`, do NOT proceed to Phase 3

If the primary criterion fails after a valid experiment (EVA passes, manipulation verified), you MAY proceed to Phase 3 but MUST:
- Report the negative result honestly with full statistics
- Include detailed diagnosis in the limitations section
- Mark success criterion SC1 as `met: false`

#### Phase 3: Paper + Webapp (ONLY after Phase 2)

Write paper, generate figures from actual results, compile LaTeX, build webapp.

**PRODUCES:**
- `output/paper/paper.tex` + `output/paper/paper.pdf`
- `output/index.html`

---

### The Four-Level Encoding Ablation

All levels receive the **same N=500 row sample** and **all four knowledge sources** (data, policies, expert beliefs, playbook). Only encoding quality varies:

| Level | Data | Knowledge | Playbook |
|-------|------|-----------|----------|
| **L1: Raw text (post-retrieval baseline)** | `str(dataframe)` — raw CSV text dumped verbatim. NO column header repetition, NO summary statistics, NO aggregation. Just the raw rows as a text blob. This represents: "you retrieved the right data, now what?" | Policy sentences as plain prose paragraphs. NO structure, NO bullet hierarchy. | Playbook as one flat paragraph of prose. |
| **L2: +Stats** | Statistical profiles computed via numpy/scipy (means, medians, correlations, distributions by segment) | Bullets + prose (same as L1 for knowledge) | Prose (same as L1 for playbook) |
| **L3: +Typed** | Statistical profiles (same as L2) | Constraint vectors with explicit tiers + temporal belief objects with confidence and decay | Prose (same as L1 for playbook) |
| **L4: Full** | Statistical profiles (same as L2) | Typed constraints + beliefs (same as L3) | Process graphs + rule catalog + technique registry |

**Encoding Level Separation Verification (MANDATORY before any experiment run):**
1. Compute character count of the full LLM input at each level
2. Compute SHA-256 hash of the full LLM input at each level
3. All 4 hashes MUST be different
4. L4 character count MUST be > L1 character count (structured encoding adds information)
5. Record these in `output/encoding_hashes.json`
6. If L1 and L4 produce identical or near-identical inputs (>90% overlap by longest-common-subsequence): the encoding is BROKEN — fix it

This is the paper's primary experiment — allocate the most effort here. Run on enough scenarios for ≥0.80 statistical power to detect d=1.0 effects.

### Planted Effects Must Be Encoding-Sensitive

Effects must be designed to **mislead at L1 but resolve at L4**. Categories that achieve this:
- **Simpson's paradox**: Aggregate tells one story; segment-level tells the opposite. L1 (raw text) sees only aggregates; L2+ computes segment-level stats that reveal the reversal.
- **Confounded coupling**: Spurious correlation from shared temporal confound; L2+ detrends, L1 cannot.
- **Constraint-boundary effects**: Data says go, a hard constraint says stop. L1 has constraints as prose (easy to miss); L3+ has typed constraint vectors that explicitly block.
- **Decayed beliefs**: Expert was right historically, data has shifted. L1 has both as prose (ambiguous); L3+ has temporal belief objects with decay functions that flag the conflict.
- **Nonlinear segment interactions**: Effect exists only in a sub-population. L1 sees flat averages; L2+ computes segment-level breakdowns.

**Why these mislead L1 specifically:** L1 receives raw CSV text and prose. It cannot compute segment-level statistics (Simpson's), cannot detrend temporal confounds (confounded coupling), cannot parse constraint hierarchy from prose (constraint-boundary), cannot detect belief decay from flat prose (decayed beliefs), and cannot segment-aggregate (nonlinear interactions). L4 has all of these pre-computed.

**Calibration targets:** ~50-70% discoverable at L4, ~20-40% at L1. These are checked in the Phase 1 pilot gate.

**If calibration fails (L1 ≥ L4 or L4 < 50%):**
1. Check encoding separation (are LLM inputs actually different?)
2. Check if raw text accidentally contains structure (column headers, summaries)
3. Increase noise magnitude in confounded coupling effects
4. Add more Simpson's paradox cases (these are strongest L1/L4 discriminators)
5. Reduce signal-to-noise ratio in aggregate statistics
6. Create a REVISE task with diagnosis and repeat Phase 1

### Secondary Experiments

- **Cross-source reasoning**: At L4, vary which sources are included (data-only → all). If data-only matches all-sources on recall, the planted effects are too easy — redesign.
- **Playbook reasoning**: Process selection accuracy across question types. Target ≥80%.
- **Pipeline compression**: Quantify space reduction at each stage.
- **Generalization**: Brief qualitative discussion of 1-2 other domains. No deep experiments.

---

## Critical Constraints (These Caused Previous Failures — Do Not Violate)

### 1. DO NOT TRUNCATE CONTEXT

**NEVER truncate or cap the encoded context sent to the LLM.** If you truncate all levels to the same character limit, you destroy the experimental variable. If context is too long, reduce N — but keep N identical across all levels for a given scenario.

**If violated:** All encoding levels produce identical output → all metrics are identical → experiment is invalid. EVA Check 1 (manipulation varied) will catch this if encoding hashes collide. Fix: remove the truncation, reduce N to fit in context.

### 2. DO NOT LEAD THE DISCOVERY PROMPT

**NEVER list the effect categories you want the LLM to find.** The discovery prompt must be open-ended: "Analyze this context and identify all noteworthy findings about cross-lever effects, anomalies, contradictions, and risks." If you say "look for Simpson's paradox, confounders, constraint violations..." it will list all of them regardless of evidence.

**If violated:** L1 recall jumps to match L4 → no encoding differentiation → experiment is invalid. Fix: rewrite the discovery prompt to be category-blind.

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
- Number and specialization of diagnostic agents in the pipeline — but the pipeline MUST have ≥2 parallel diagnostic agents operating on complementary dimensions (as the abstract claims)
- The causal synthesis mechanism — but it MUST produce structured interventions with fields: lever, direction, scope, mechanism (as the abstract claims)
- Quality gate scoring — MUST implement all five dimensions named in the abstract: evidence density, constraint alignment, actionability, testability, novelty. Each dimension must produce a numeric score. Log all five scores per candidate in `output/pipeline_scores.json`
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

## Success Criteria (These Are Exit Gates, NOT Aspirations)

Write these to `.swarm/success-criteria.json` at investigation start. Convergence is blocked while any criterion has `met: false`.

1. **SC1: Encoding layer matters** — L4 statistically significantly outperforms L1 on F1 of planted effect discovery (p < 0.05). **If L1 ≥ L4: this is a DESIGN failure, not a finding. Flag DESIGN_INVALID, diagnose, redesign, re-run.**
2. **SC2: Cross-source reasoning works** — more knowledge sources → more discovered effects; data-only misses planted cross-source effects
3. **SC3: Pipeline compresses effectively** — combinatorial space reduced by ≥10×
4. **SC4: Problem characterization is rigorous** — three invariants formally defined; for EACH invariant, one constructive example showing that addressing only the other two invariants (ignoring this one) yields an incomplete solution
5. **SC5: Paper is complete** — compiles, figures from actual data, all abstract claims substantiated, honest limitations section
6. **SC6: All claims backed** by effect sizes and confidence intervals
7. **SC7: Pipeline architecture matches abstract** — implementation has ≥2 parallel diagnostic agents, causal synthesis produces (lever, direction, scope, mechanism) tuples, quality gate scores on all 5 dimensions (evidence density, constraint alignment, actionability, testability, novelty). Verified by `output/pipeline_scores.json` containing all 5 dimension scores per candidate

**On SC1 failure after valid experiment:** If the experiment ran correctly (EVA passes, encoding inputs are verified different, manipulation check passes) and L1 still ≥ L4, you have two options:
- **Option A (preferred):** Diagnose why, redesign planted effects, re-run. Most likely cause: effects are discoverable from raw text alone.
- **Option B (last resort):** Report the negative result honestly with full analysis of why structured encoding didn't help. The paper becomes "we tried this, it didn't work, here's why." This is a valid paper but a different paper than the abstract promises. Mark SC1 as `met: false` with detailed rationale.

---

## Cleanup Requirements

When the demo run completes:
- Delete ALL agent branches (local and remote), remove all worktrees, prune, kill tmux sessions
- `.llm_cache/` MAY be preserved for reproducibility
- Verify: `git branch -a | grep agent` returns nothing, `git worktree list` shows only main worktree
