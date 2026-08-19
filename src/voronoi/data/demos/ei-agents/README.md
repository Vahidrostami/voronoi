# Demo: Attractor Regimes in a Society of Small Language Models

**Does collective inference peak in the metastable band between consensus and independence — and can that band be located from label-free dynamics before any accuracy number is inspected?**

A neuroscience-inspired, claim-disciplined study of frozen SLMs coupled into competing clusters. Nothing is trained. The society is controlled by two scalars, and the study maps the regime diagram they span.

## What It Does

Agents are partitioned into `M` structural clusters and coupled by two numbers:

- `J+` — within-cluster coupling (attractor depth)
- `J-` — cross-cluster opponent gain (competition strength)

Every deployed multi-agent scheme is a corner of that surface — self-consistency at `J+ = J- = 0`, dense debate at `M = 1, J- = 0`, winner-take-all at large `J-`. The contribution is that these are **boundary conditions of one control surface whose interior nobody has mapped**, not leaderboard rivals. A grid sweep is the primary run; there is no outer optimizer loop, which is what makes the design fit a 10-hour budget.

### Two Channels

| Channel | Mechanism | Role |
|---|---|---|
| **L — logit-level** | `w_ij` multiplies the sender's option log-probabilities, aggregated on the answer simplex | Primary mechanism. Challenge is genuinely subtractive and `J` has defined gain. |
| **T — text-level** | Support/challenge framing injected into context | Deployability arm. Most likely to fail construct validation. |

The L-vs-T gap is itself a result: it measures whether prompt-level critique carries real signed information.

### The Two Load-Bearing Tests

**H0 (construct validation)** runs first and gates everything else: does a challenge message actually *lower* the target agent's log-odds on the proposition it names, versus a token-matched neutral control? A channel that fails H0 is dropped and the failure is reported as the finding.

**H2 (dynamics predicts the optimum)** is what separates this from hyperparameter tuning. The metastable band — nonzero switch rate, heavy-tailed dwell times, entropy that neither collapses nor stays flat — is registered from **unlabeled** items *before* anything is scored. The accuracy peak is then predicted to fall inside it. If it does not, the attractor framing is falsified and only a tuning result remains.

The rest: clusters binding to hypotheses without being told which answer they carry (H3), prior information removing attractors rather than adding a mechanism (H4), across-run dispersion as free confidence (H5), and regime-dependent robustness to misinformation and dropout (H6).

## Claim Discipline

Neuroscience supplies a computational principle and nothing else. Three claims are forbidden in every artifact:

1. No "emergent E/I structure" — cluster membership and edge sign are imposed by construction. Only the optional unsigned run can speak to emergence.
2. No calling a negative edge "inhibition" before H0 passes for that channel.
3. No use of the names *Fano Factor* or *CV2* — messages are not a point process. System-native metric names only.

The prompt also forbids re-deriving machine learning the field already has: TD learning, policy-gradient RL, MoE load balancing, architecture search, and test-time-compute scaling are framing tools for the question, never findings.

The reference model ([Rostami et al. 2024](https://doi.org/10.1038/s41467-024-49889-4)) built paired E/I clusters **by construction**. What emerged there was metastable winnerless competition, not the topology. This demo borrows the computational principle — clustered attractors, opponent balance setting well depth, prior information removing competitors — and imports neither the connectivity as a claim nor the spike statistics as metrics.

## Why It Runs in DISCOVER

`PROVE` locks the question, and the question is not yet lockable — there is no validated construct for the negative channel. The demo runs `MODE DISCOVER` with `RIGOR SCIENTIFIC`, which keeps full pre-registration and plan-review gates while leaving the question refinable. A promotion path to `PROVE` + `RIGOR EXPERIMENTAL` is written into the prompt.

## Requirements

An OpenAI-compatible endpoint serving a small instruct model, configured by environment variable:

```bash
export VORONOI_LLM_BASE_URL="http://your-host:8000/v1"
export VORONOI_LLM_API_KEY="EMPTY"
export VORONOI_LLM_MODEL="Qwen/Qwen2.5-3B-Instruct"
curl "$VORONOI_LLM_BASE_URL/models"
```

The endpoint **must** return `logprobs` or Channel L is unavailable. The demo never starts, stops, or replaces the inference server, and never submits scheduler jobs.

## Running

```bash
voronoi demo run ei-agents
```

Four human gates stop the run: after the budget arithmetic, after H0 construct validation, after compute-matched baselines plus smoke test, and before any optional learned-`W` run.
