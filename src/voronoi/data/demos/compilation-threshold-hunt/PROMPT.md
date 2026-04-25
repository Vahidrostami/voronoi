# When Does Compilation Stop Mattering? A Capability-Threshold Hypothesis

## Claim

LLMs are increasingly used as reasoning engines over heterogeneous knowledge.
We hypothesize that **knowledge compilation** — transforming raw sources
into epistemic-type-preserving representations before reasoning — provides
a benefit that has a **model-dependent activation threshold $K_c(M)$**:

- Below $K_c$: compiled and raw inputs produce equivalent decisions.
- Above $K_c$: raw-input reasoning degrades; compiled-input reasoning holds.
- $K_c$ scales with model capability; **no model is immune** at sufficient
  problem complexity.

Produce a paper, suitable for a top-tier ML venue, that either confirms,
refutes, or sharpens this claim. We do not assume sharpness of the
transition; we will *report* whether it is sharp or smooth.

## Falsification target (load-bearing)

The claim is **falsified** if any one of the following holds at convergence:

1. There exists a model M where compilation provides no measurable benefit
   at any complexity level the swarm could construct within budget.
2. The benefit of compilation is fully explained by a null-encoder control
   (same token budget, same structure, scrambled epistemic links).
3. The threshold $K_c(M)$ does not correlate with any a-priori capability
   proxy (release date, GPQA, MMLU-Pro, etc.).

Report falsification clearly. A clean negative result is a successful run.

## Methodological commitments (non-negotiable)

These constrain *how* the swarm is allowed to reason; everything else
about the design is the swarm's choice.

- **Deterministic ground truth.** Primary metrics MUST be computed against
  known causal structure (forward-simulable outcomes), not LLM-as-judge.
  LLM judges are allowed only for secondary metrics, with calibration.
- **Adversarial control required.** Every claim that "compilation helps"
  must be tested against a same-budget, same-structure null encoder where
  epistemic links are scrambled. If the swarm cannot rule out
  noise-removal as the explanation, the claim is rejected.
- **Encoder isolation.** The compilation step has no access to ground
  truth, generator seeds, or the discovery prompt. Hallucination audit
  required (no values appear in compiled output that are not derivable
  from raw input).
- **Pre-registration before measurement.** The Methodologist writes the
  full design — difficulty axis, encodings, model panel, statistical
  analysis, decision rule — to `.swarm/preregistration.json` BEFORE any
  scenario is run. Any post-hoc change requires a new pre-registration
  and is reported as such.
- **Capability proxy frozen before data collection.** Models are ranked
  by an a-priori proxy chosen and recorded in `models.json` before
  Phase 1. Never updated mid-run.

## What the swarm decides (not us)

- The difficulty axis: how to parameterize complexity, how many levels,
  what bundles vs. what's orthogonal. Whatever you choose, justify it
  against external validity (must resemble a real reasoning task, not a
  synthetic toy).
- The encoding family: raw, compiled, and the null control are required;
  additional encodings are encouraged if the Theorist proposes them.
- The model panel: ≥1 sub-frontier and ≥1 frontier. Beyond that, the
  Methodologist chooses based on capability spread and budget.
- The scenario domain: pick a domain where ground truth is genuinely
  knowable (causal DAG with known coefficients). RGM, supply chain,
  clinical decision support, and pricing are all candidates. Defend
  the choice in the deliverable.
- The statistical test for "threshold exists": changepoint vs. smooth
  sigmoid is one option; the Statistician may propose better. Report
  model selection criteria.

## Competing theories (Theorist must address before any experiment)

Before the first experiment runs, the Theorist writes ≥2 alternatives
to `.swarm/competing-theories.md`:

- **T1 (ours):** Compilation has a capability threshold; benefit is
  epistemic-structure preservation.
- **T2 (null):** Any benefit is noise-removal / token-compression. The
  null encoder dissolves it.
- **T3 (Theorist's choice):** Propose a third explanation we haven't
  considered. Examples to avoid (must propose something else):
  surface-form bias, attention dilution, in-context-retrieval failure.

Every experiment must be designed to **discriminate** between at least
two of these theories. Experiments that only confirm T1 are rejected
at plan review.

## Surprise budget (this is the breakthrough lever)

At least **30% of the token budget** must be allocated to hunting
regimes where the hypothesis fails:

- Find a model where compilation does NOT help. If you find one,
  promote it to a full investigation; this is the most valuable
  finding the run can produce.
- Find a complexity dimension where compilation specifically does
  NOT neutralize. Report it.
- Find a scenario where the null encoder beats the real encoder.
  This kills the hypothesis cleanly. Run it.

The orchestrator must track a **surprise ledger** in
`.swarm/surprise-ledger.json` — every observation that contradicts
the hypothesis, even partially. At convergence, the deliverable's
strength is judged in part by how seriously these were pursued.

## Anomaly escalation (overrides default convergence)

Any cell where **null-encoder ≥ compiled-encoder** in expected value
(within noise) on any model triggers immediate escalation:

- Statistician verifies the result against raw simulation.
- Theorist proposes mechanisms.
- Methodologist designs ≥1 follow-up to discriminate.
- The cell is NOT closed until either explained or marked
  ANOMALY_UNRESOLVED in the claim ledger.

ANOMALY_UNRESOLVED **blocks convergence**. We would rather ship a
shorter paper with an honest open question than a complete paper
that hides one.

## Budget contract

<!-- TODO: once `--budget` flag and budget-aware prompt builder ship in
     `src/voronoi/server/prompt.py`, replace the placeholders below with
     real values injected from the queue row. Until then, the
     orchestrator must interpret these in-prompt. -->

- **Token budget**: `<inject from --budget at enqueue time; default 50M>`.
- **Wall-clock budget**: `<inject from --timeout; default 36h>`.
- **Burn-rate floor**: if 25% of budget is spent and zero anomalies
  recorded, the orchestrator pauses and requests a `/voronoi pivot`
  from the operator before continuing. We do not burn the second
  half of the budget on confirmation alone.

## Deliverable

A scientific manuscript with:

1. The hypothesis, its falsification target, and the falsification result.
2. The design (pre-registered + post-hoc changes called out).
3. Primary results with deterministic metrics.
4. The null-encoder verdict (mandatory section, even if uninteresting).
5. The surprise ledger: every anomaly found, pursued or open.
6. Competing-theory adjudication: which theory survives, which is killed.
7. Limitations, with specific reviewer-2 objections pre-answered.

A run that confirms our hypothesis with eval ≥ 0.75 is a *pass*.
A run that **kills** our hypothesis with eval ≥ 0.75 is a *win*.
