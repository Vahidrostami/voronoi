# Conflict-Surfacing in RGM Decisions: A Mechanism, Not Just an Advantage

## Claim

Large language models routinely make Revenue Growth Management (RGM)
decisions — promotional ROI calls, price-pack architecture choices,
cross-elasticity adjudications — by reading heterogeneous evidence
that *disagrees*: scanner-derived elasticities vs. category-manager
beliefs vs. retailer-policy constraints vs. competitor-move briefs.

We claim that under such evidence conflict, LLM RGM recommendations
are systematically biased toward whichever source appears **last in
the prompt** or is **most verbose**, *independent of the source's
evidential quality*. We call this the **position-and-verbosity
dominance** failure mode. Compiling heterogeneous evidence into a
typed conflict ledger (sources, claims, conflict edges, evidence
weights) eliminates this bias and improves decision profit on a
benchmark with deterministic ground truth.

The headline of this work is the *mechanism* (position-and-verbosity
dominance under evidence conflict in RGM), not the *operational
shortcut* ("structured prompts are better"). The structured-prompt
result is a corollary of the mechanism; do not invert that ordering.

## Falsification target (load-bearing)

The claim is **falsified** if any one of the following holds at
convergence:

1. **Shuffle invariance.** Permuting source order and length-padding
   the shortest source to match the longest, with content held
   constant, does not change the model's recommended decision in
   ≥80% of conflict scenarios at any tested model tier. If LLMs are
   order-and-length-invariant under conflict, the bias does not exist.
2. **Quality dominance.** Recommendations track a credible
   evidence-quality signal (e.g. elasticity confidence interval
   width, sample size, source recency) more strongly than they track
   position/length. If quality signal explains the variance, position
   bias is not the mechanism.
3. **Compilation null.** A same-budget, same-structure null encoder
   that scrambles the conflict edges (typed slots present, conflict
   relationships randomised) recovers the same accuracy as the real
   typed-conflict-ledger encoder. If yes, structure-not-conflict-
   surfacing is the active ingredient and the claim is rejected.

A clean negative result on any of (1)–(3) is a successful run.
Report it.

## Why RGM (not generic decision support)

RGM is the right test bed for this claim for three reasons the swarm
must defend in the introduction:

- **Heterogeneous-by-construction.** Every real RGM decision combines
  quantitative elasticity estimates, qualitative shopper insight,
  hard policy constraints (pricing corridors, JBP commitments), and
  competitor signals. This is not a synthetic property — it is the
  domain.
- **Conflict-by-construction.** Scanner-derived elasticity routinely
  disagrees with category-manager intuition; trade-promo ROI is
  negative for a large fraction of events yet promos persist due to
  retailer mandates. The conflict the claim probes is *endemic*.
- **Forward-simulable ground truth.** Given a known causal demand
  model, we can compute the profit-optimal lever setting and measure
  decision regret deterministically. No LLM-as-judge required for
  the primary metric.

## Methodological commitments (non-negotiable)

These constrain *how* the swarm reasons; everything else is the
swarm's choice.

- **Deterministic ground truth.** Primary outcomes (decision regret,
  direction accuracy, constraint violation) MUST be computed against
  a known causal demand DAG with planted elasticities and
  cross-elasticities. LLM judges are allowed only for secondary
  qualitative metrics.
- **Shuffle-invariance test is mandatory and primary.** The
  Statistician computes a per-cell *position-bias coefficient* — the
  share of decision flips induced by source-order permutation alone,
  with content held constant. This metric is reported alongside
  accuracy in every results table. A paper that omits it fails review.
- **Length-padding control is mandatory.** Length must be controlled
  independently of position. The Methodologist designs a
  length-matched control where the shortest source is padded with
  semantically null filler that preserves the source's epistemic
  type.
- **Encoder isolation.** The typed-conflict-ledger encoder has no
  access to ground truth, generator seeds, or the discovery prompt.
  Hallucination audit required: every conflict edge in the compiled
  output must be derivable from the raw input.
- **Pre-registration before measurement.** The Methodologist writes
  the design — scenario family, conflict taxonomy, encodings, model
  panel, statistical analysis, decision rule — to
  `.swarm/preregistration.json` BEFORE any scenario is run. Post-hoc
  changes require a new pre-registration and are reported as such.
- **Capability proxy frozen before data collection.** Models are
  ranked by an a-priori proxy chosen and recorded in `models.json`
  before Phase 1.
- **No "universal advantage" headline.** The deliverable's abstract
  may NOT lead with "structured/compiled prompts beat raw prompts."
  That finding is a corollary. Lead with the mechanism (position-
  and-verbosity dominance) and the conditions under which it
  appears or vanishes. If the swarm produces a draft whose abstract
  could appear in a generic structured-prompting paper, the Critic
  rejects it and the Scribe rewrites.

## What the swarm decides (not us)

- **The RGM scenario family.** Promotional ROI, price-pack
  architecture, cross-elasticity adjudication, mix-vs-price-vs-promo
  attribution, or another sub-domain. Pick one and defend it. A
  scenario family with no real conflict edges is rejected at plan
  review.
- **The conflict taxonomy.** What does an "evidence conflict" look
  like in RGM? At minimum: data-vs-belief, belief-vs-policy,
  data-vs-policy. The Theorist proposes ≥5 conflict types and the
  Methodologist samples scenarios across them.
- **The difficulty axis.** Number of sources, conflict density,
  asymmetry of source verbosity, hard-vs-soft constraint mix.
  Justify the chosen axis against external validity (must resemble a
  real RGM workflow, not a synthetic toy).
- **The encoding family.** Raw text, typed conflict ledger, and
  structure-only null are required. Additional encodings encouraged.
- **The model panel.** ≥1 sub-frontier and ≥1 frontier model. Beyond
  that, the Methodologist chooses based on capability spread and
  budget.
- **The statistical analysis.** Mixed-effects model, factorial ANOVA,
  Bayesian hierarchical — the Statistician's call. The position-bias
  coefficient and the shuffle-invariance test outcome are
  non-optional regardless of the chosen framework.

## Competing theories (Theorist must address before any experiment)

Before the first experiment runs, the Theorist writes ≥3 alternatives
to `.swarm/competing-theories.md`:

- **T1 (ours):** Position-and-verbosity dominance under evidence
  conflict; typed conflict ledger remediates because it makes
  conflict edges first-class.
- **T2 (null):** Any benefit of compilation is generic noise removal
  / token compression. The structure-only null encoder dissolves it.
- **T3 (quality-weighting):** LLMs *do* weight by evidence quality;
  the apparent position bias is an artifact of source-quality
  correlating with position in the prompts we wrote.
- **T4 (Theorist's choice):** Propose a fourth explanation we haven't
  considered. Examples to avoid (must propose something else):
  surface-form bias, attention dilution, in-context retrieval failure.

Every experiment must be designed to **discriminate** between at
least two of these theories. Experiments that only confirm T1 are
rejected at plan review.

## Surprise budget (this is the breakthrough lever)

At least **30% of the token budget** must be allocated to hunting
regimes where the position-bias claim fails:

- Find a model where position-shuffle does not change decisions.
  If you find one, characterise what makes it shuffle-invariant.
- Find a conflict type (e.g. policy-vs-data) where the bias is
  inverted — the *first* source dominates, not the last. Report it.
- Find a scenario where the structure-only null beats the typed
  conflict ledger. This kills the mechanism cleanly. Run it.

The orchestrator tracks a **surprise ledger** in
`.swarm/surprise-ledger.json` — every observation that contradicts
the claim, even partially. At convergence, the deliverable's
strength is judged in part by how seriously these were pursued.

## Anomaly escalation (overrides default convergence)

Any cell where shuffle invariance is observed (≤20% decision flip
rate under permutation) on any model triggers immediate escalation:

- Statistician verifies against raw simulation.
- Theorist proposes mechanisms.
- Methodologist designs ≥1 follow-up to discriminate.
- The cell is NOT closed until either explained or marked
  ANOMALY_UNRESOLVED in the claim ledger.

ANOMALY_UNRESOLVED **blocks convergence**. We would rather ship a
shorter paper with an honest open question than a complete paper
that hides one.

## Literature grounding (required, not ledger-gated)

The Theorist owns a literature scaffold the manuscript must engage
with. Cite at least 2 anchor papers per cluster; the Theorist may
add clusters but may not omit any:

1. **Position bias and prompt-order sensitivity in long-context LLMs.**
   Lost-in-the-middle and follow-ups; conflict-of-evidence reasoning
   benchmarks. This is the ML mechanism literature the claim sits in.
2. **LLM-as-decision-agent in operations / tabular reasoning.**
   Recent NeurIPS/ICML benchmarks for LLMs making bounded numerical
   decisions over structured inputs.
3. **Knowledge compilation and structured/typed prompting.**
   Darwiche & Marquis (2002) is the classical anchor; recent work on
   schema-constrained generation and typed RAG is the modern lineage.
4. **Revenue management & dynamic pricing under demand uncertainty.**
   The OR-tradition foundation (Talluri & van Ryzin lineage) plus
   recent work on assortment + price decisions.
5. **Causal inference for marketing-mix and uplift estimation.**
   Double-ML / Athey-Wager lineage; current open-source MMM stacks.
6. **RGM industry baseline (grey literature, marked as such).**
   At least one public NielsenIQ / Circana / McKinsey / BCG / Bain
   report on promo-ROI distribution or PPA practice. Cited as
   practitioner context, never as scientific evidence.

Every cited paper must be opened and a two-sentence summary written
to `.swarm/literature-notes.md` (one entry per citation) before it
appears in the manuscript. Citations without a notes entry are
removed by the Critic at the merge gate.

## Budget contract

- **Token budget**: `<inject from --budget at enqueue time; default 50M>`.
- **Wall-clock budget**: `<inject from --timeout; default 36h>`.
- **Burn-rate floor**: if 25% of budget is spent and zero anomalies
  recorded *and* the shuffle-invariance test has not been run on the
  full panel, the orchestrator pauses and requests a `/voronoi pivot`
  from the operator before continuing.

## Deliverable

A scientific manuscript suitable for a top-tier ML venue with:

1. The mechanism claim (position-and-verbosity dominance under
   evidence conflict in RGM), its falsification targets, and the
   falsification result.
2. The shuffle-invariance test as a primary result table — per
   model, per conflict type.
3. The typed-conflict-ledger encoder and its structure-only null
   ablation, with the null verdict in its own section (mandatory,
   even if uninteresting).
4. The pre-registered design and any post-hoc changes called out.
5. The surprise ledger: every anomaly found, pursued or open.
6. Competing-theory adjudication: which of T1–T4 survives.
7. Limitations, with reviewer-2 objections pre-answered: domain
   generality, RGM scenario realism, model-panel coverage, dependence
   on the chosen conflict taxonomy.
8. A plain-language practitioner appendix (≤2 pages): "if you are an
   RGM analyst pasting evidence into an LLM today, here is what
   changes the answer and what doesn't, with a recommended template."

A run that confirms the mechanism with eval ≥ 0.75 is a *pass*. A
run that **kills** the mechanism (any of falsification 1–3) with
eval ≥ 0.75 is a *win*.
