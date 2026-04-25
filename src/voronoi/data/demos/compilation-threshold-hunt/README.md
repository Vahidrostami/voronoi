# Demo: Compilation-Threshold Hunt

**Same hypothesis as `epistemic-trajectories`. The swarm designs the experiment.**

Does knowledge compilation provide a benefit that activates only above a
model-dependent capability threshold $K_c(M)$ — and is that benefit
specifically epistemic-structure preservation, not noise removal?

This demo gives the swarm the **claim**, the **falsification target**, and
the **non-negotiable methodological commitments** (deterministic ground
truth, null-encoder control, encoder isolation, pre-registration). The
difficulty axis, encoding family, model panel, scenario domain, and
statistical test are the swarm's job — not pre-specified.

## How this differs from `epistemic-trajectories`

| Dimension | `epistemic-trajectories` | `compilation-threshold-hunt` |
|---|---|---|
| Method specification | ~300 lines of fixed protocol | ~80 lines, claim + falsification only |
| Unit of work | 1,500+ pre-specified cells | claims; cells generated as needed |
| Search direction | Confirm pre-registered design | Confirm **and** hunt failure regimes (≥30% surprise budget) |
| Convergence rule | All phases complete | No unexplained anomaly remains |
| Theorist role | Rubber-stamp | Propose ≥2 competing theories before any experiment |
| Methodologist role | Approve frozen design | Owns the design |
| Expected runtime | ~40h | <20h (no per-cell gate-thrashing) |

## How to run

### CLI

```bash
voronoi demo run compilation-threshold-hunt
```

### Telegram

```
/voronoi demo run compilation-threshold-hunt
```

## Expected deliverable

- A manuscript whose abstract you **cannot predict from the prompt** — if you can, the swarm collapsed back into pre-registered confirmation and the rewrite didn't take.
- `.swarm/competing-theories.md` containing a T3 you didn't think of.
- `.swarm/surprise-ledger.json` with at least one anomaly recorded inside the first 25% of budget.
- A "null-encoder verdict" section in the deliverable that is non-trivial — i.e., the swarm actually probed regimes where the null was hard to rule out.
- A clean **win** condition: a run that **kills** the hypothesis with eval ≥ 0.75 is reported as a successful breakthrough, not a failure.

## System affordances this demo presupposes

The PROMPT references three affordances that are not yet structurally
enforced by the runtime:

- `--budget` flag on enqueue and a budget-aware prompt builder
- `.swarm/surprise-ledger.json` as a first-class sibling of the claim ledger
- `/voronoi pivot <codename>` for mid-run steering at the burn-rate floor

Until those land, the orchestrator interprets these in-prompt. The demo
is still useful — it puts the Theorist/Methodologist/Statistician/Critic
back to work — but the burn-rate-floor pause is advisory, not blocking.
