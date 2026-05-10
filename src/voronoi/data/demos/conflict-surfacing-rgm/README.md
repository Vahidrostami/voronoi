# Demo: Conflict-Surfacing in RGM Decisions

**A mechanism study, not a structured-prompting study.**

When LLMs are asked to make Revenue Growth Management decisions over
conflicting heterogeneous evidence (scanner data vs. expert belief vs.
retailer policy vs. competitor signal), are they biased by *which
source appears last* and *which source is longest* — independent of
evidence quality? If so, a typed conflict ledger should fix it. The
swarm's job is to confirm, refute, or sharpen this claim, then write
it up for a top-tier ML venue.

## How this differs from `compilation-threshold-hunt`

| Dimension | `compilation-threshold-hunt` | `conflict-surfacing-rgm` |
|---|---|---|
| Headline question | Does compilation help, and where is the threshold? | What is the *mechanism* by which compilation helps in RGM? |
| Domain | Swarm picks | Fixed: RGM (scenario family is the swarm's call) |
| Primary metric | Direction accuracy by complexity | Position-bias coefficient + decision regret under conflict |
| Falsification | Compilation provides no benefit on any model | Shuffle-invariance, quality-weighting, or structure-only null all kill it |
| Forbidden headline | None | "Universal advantage of compilation" — must be a corollary, not the lead |
| Venue framing | Generic | Top-tier ML (NeurIPS/ICLR-shaped contribution) |

## What is *not* prescribed

- The RGM scenario family (promo-ROI, PPA, cross-elasticity, mix-attribution, ...)
- The conflict taxonomy (≥5 types proposed by Theorist)
- The difficulty axis (sources, conflict density, verbosity asymmetry, ...)
- The model panel (≥1 sub-frontier, ≥1 frontier; spread is the Methodologist's call)
- The statistical framework (mixed-effects, factorial ANOVA, Bayesian hierarchical, ...)

## What is non-negotiable

- Deterministic ground truth from a known causal demand DAG
- Mandatory primary report: shuffle-invariance test + position-bias coefficient
- Mandatory length-padding control (length confounds position; both must be isolated)
- Encoder isolation + hallucination audit on the typed conflict ledger
- Pre-registration before any data collection
- A literature-notes entry per citation (the Theorist owns the scaffold)
- Surprise budget ≥30% of tokens, anomaly escalation blocks convergence
- "Universal advantage" framing is forbidden as the headline

## How to run

### CLI

```bash
voronoi demo run conflict-surfacing-rgm
```

### Telegram

```
/voronoi demo run conflict-surfacing-rgm
```

## Expected deliverable

- A manuscript whose abstract leads with the *mechanism* (position-and-verbosity
  dominance under evidence conflict in RGM), not with a structured-prompting result.
- A primary results table reporting the **position-bias coefficient** per model
  and per conflict type, alongside decision regret.
- `.swarm/competing-theories.md` containing T4 — a theory we did not seed.
- `.swarm/surprise-ledger.json` with at least one anomaly recorded inside the
  first 25% of budget, or an explicit "no anomaly found within budget X" entry.
- A null-encoder verdict section that probes regimes where the structure-only
  null was hard to rule out.
- A practitioner appendix (≤2 pages) usable by a CPG analyst tomorrow.
- A clean **win** condition: a run that **kills** the mechanism (shuffle-
  invariance, quality-dominance, or structure-only-null parity) with
  eval ≥ 0.75 is reported as a successful breakthrough, not a failure.

## System affordances this demo presupposes

The PROMPT references three affordances not yet structurally enforced
by the runtime:

- `--budget` flag on enqueue and a budget-aware prompt builder
- `.swarm/surprise-ledger.json` and `.swarm/literature-notes.md` as
  first-class siblings of the claim ledger
- `/voronoi pivot <codename>` for mid-run steering at the burn-rate floor

Until those land, the orchestrator interprets these in-prompt. The
demo is still useful — it puts the Theorist/Methodologist/Statistician/
Critic to work on a sharper claim than `compilation-threshold-hunt` —
but the burn-rate-floor pause is advisory, not blocking.
