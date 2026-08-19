# Attractor Regimes in a Society of Small Language Models

MODE
DISCOVER

RIGOR
SCIENTIFIC

## RESEARCH GOAL

A population of frozen small language models (SLMs) exchanging signed messages is
a recurrent dynamical system with a handful of macroscopic control knobs. Map its
regime diagram and test the central prediction borrowed from clustered cortical
attractor models: **collective inference peaks neither at strong consensus nor at
independence, but in the narrow metastable band between them — and that band can
be located from label-free dynamics before any accuracy number is inspected.**

Inference time only. Frozen weights, one endpoint. No training, post-training, or
fine-tuning.

## THE IDEA

Clustered cortical circuits compute by letting groups of cells form attractors
that compete, with local opponent drive setting how deep the wells are. Deep wells
→ the system locks into one state and stops revising. Shallow wells → nothing
coheres. Between them it is *metastable*: it dwells in a hypothesis long enough to
use it, then switches. Prior information adds no mechanism there — it removes
competing attractors, and trial-to-trial variability falls in proportion.

Transfer that principle, not its implementation. Instead of searching an N×N
routing matrix, structure the society into `M` clusters and control it with two
scalars: `J+`, within-cluster coupling (attractor depth), and `J-`, cross-cluster
opponent gain (competition strength). Every deployed multi-agent scheme is then a
corner of one surface:

| Corner | Method it reproduces |
|---|---|
| `J+ = 0, J- = 0` | self-consistency / independent majority vote |
| `M = 1, J+ > 0, J- = 0` | debate, Mixture-of-Agents, dense positive coupling |
| `M > 1, J+ > 0, J- = 0` | parallel non-interacting pools |
| `J-` large | winner-take-all, premature consensus |
| interior | the regime under test |

That framing *is* the contribution: existing methods are not leaderboard rivals,
they are **boundary conditions of one control surface whose interior nobody has
mapped**. If the interior beats no corner at matched compute, that is a clean
reportable negative.

## SCOPE — WHAT VORONOI SUPPLIES, WHAT NOT TO REDISCOVER

The standard pipeline supplies the literature scan and positioning table,
pre-registration, claim ledger, citation coverage, fabrication checks, statistics
and multiple-comparison policy, convergence gate, and the manuscript track. Do not
re-specify any of it. This prompt covers only the mechanism, the gating construct
validation, the regime predictions, and the hard infrastructure limits.

Temporal-difference learning, policy-gradient RL, mixture-of-experts load
balancing, neural architecture search, and test-time-compute scaling laws are
**framing tools, not findings** — use them to sharpen the question and build the
comparators, never spend a run re-deriving them, and do not import RL machinery a
frozen endpoint cannot use. State the delta in dynamical-regime language (*where
on the coupling surface, and why*), not optimizer language. "Tuning a
hyperparameter helped" is not a result here; it becomes one only when the optimum
is predicted in advance by a measure computed without labels.

## CLAIM DISCIPLINE

Neuroscience supplies a computational principle and nothing else. Agents are not
neurons, edges are not synapses, nothing here is biological excitation or
inhibition. Three claims are forbidden in every artifact:

1. **"Emergent E/I structure."** Cluster membership and edge sign are imposed by
   construction. Only the optional unsigned run can speak to emergence, weakly.
2. **"Inhibition."** A negative edge is a *challenge channel* until H0 passes for
   that channel — a negative label can lower a proposition's log-odds, raise them,
   or merely make the proposition more salient.
3. **Spike statistics by name.** No Fano factor, no CV2. Messages are not a point
   process; use the system-native names in MEASUREMENTS.

Prior-work honesty: Rostami et al. (2024) built paired E/I clusters **by
construction** and left learning that topology to future work. What emerged there
was metastable winnerless competition and the variability signature — not the
connectivity. Any sentence implying otherwise must be caught in review.

## SUBSTRATE AND MECHANISM

- N = 8-16 agents (start at 8), all one frozen SLM behind one OpenAI-compatible
  endpoint. One process with bounded async concurrency. No second model, no
  heterogeneous families, no process per agent.
- **Identical, neutral system prompts.** Agents differ by sampling seed only.
  Personas contradict the homogeneous-substrate premise and manufacture the very
  roles under test — personas are an ablation, never the default.
- Cluster membership is **structural only**: it defines who couples to whom. No
  cluster is told which answer it stands for. Cluster-to-hypothesis binding, if it
  appears, is a measured outcome (H3), not an input.

With `c(i)` the cluster of agent `i`:

```
w_ij = +J_plus     if c(i) == c(j), i != j
w_ij = -J_minus    otherwise
```

**Channel L — logit level (primary).** Request `logprobs` over the answer-option
tokens and aggregate signed influence on the option simplex:

```
logit_j[option] <- own_logit_j[option] + sum_i w_ij * logprob_i[option]
p_j = softmax(logit_j)
```

Challenge is genuinely subtractive here, `J` has a defined gain, and the decision
variable does not rest on a 3B model's badly calibrated verbalized confidence.

**Channel T — text level (deployability).** The same routing delivered as
support/challenge framing in context — what a deployed system can do without
logprobs, and the channel most likely to fail H0. Report the L-vs-T gap; it is
itself a result about whether prompt-level critique carries signed information.

**Gain calibration comes first.** Sweep a single edge's `|w|` against the target's
option distribution. If the mapping is not monotone, every downstream claim is
void. Report the dose-response curve.

Read-out is a deterministic leaky accumulator over the population option
distribution across rounds — a read-out, not a judge. No LLM arbiter anywhere.

## HYPOTHESES

**H0 — CONSTRUCT VALIDATION (gating; everything else is void without it).**
Per channel, a support message reliably raises and a challenge message reliably
lowers the target agent's log-odds on the *specific proposition named in the
message*, against both a no-message and a token-matched neutral-message control.
Report signed causal effect size with CIs. **A channel that fails H0 is dropped
and the failure is the finding** — never carried forward with a caveat.

**H1 — INTERIOR OPTIMUM.** At equal model calls and equal total tokens, accuracy
and Brier score are non-monotonic in `J+` and in `J-`, and the interior optimum
beats every corner above.

**H2 — DYNAMICS PREDICTS THE OPTIMUM (load-bearing).** Locate the metastable band
from **unlabeled** items using dynamics only: nonzero switch rate with dwell times
spanning several rounds, heavy-tailed dwell-time distribution, population entropy
that neither collapses nor stays flat. Register that region *before* scoring; the
H1 peak falls inside it. A tuned knob is not a result — a regime predicted from
label-free dynamics is.

**H3 — CLUSTERS BECOME HYPOTHESES.** Mutual information between structural cluster
identity and the answer an agent holds at convergence exceeds a cluster-shuffled
null, and peaks inside the metastable band — low under collapse (every cluster
agrees) and low under incoherence (no cluster agrees with itself).

**H4 — PRIOR INFORMATION REMOVES ATTRACTORS.** With `V` options still viable
(V = 1, 2, 3), across-run answer dispersion at convergence increases with `V`, and
the dispersion drop after disambiguating evidence is larger the larger `V` was.
Optimal `J-` decreases as `V` decreases: fewer competitors need less competition.

**H5 — DISPERSION AS FREE CONFIDENCE.** Across-run dispersion predicts per-item
correctness without ground truth, giving an abstain/escalate signal at no extra
cost. Report AUC against verbalized confidence and mean token log-probability.

**H6 — ROBUST PLURALISM.** At matched compute, the metastable band recovers better
from injected false evidence, agent dropout, and corrupted messages than the
collapsed corner, and shows lower pairwise error correlation.

## TASK DESIGN

Sequential-evidence items over a **constant answer-option set**:

1. Cue the subset of options still viable (V = 1, 2, 3) — graded prior information.
2. Deliver **final disambiguating evidence** that resolves the item. A bare
   "decide now" prompt carries no disambiguating evidence and is not a valid probe.

Two controls are mandatory, not refinements:

- **Item calibration.** Pre-select items whose single-agent accuracy falls in a
  pre-registered band (e.g. 0.35-0.85). A 3B-class model floors on hard MCQ, and
  floor effects manufacture condition differences that look like results.
- **Format-matched V=3.** Three options cued, two trivially eliminable — same
  prompt length and format, less real uncertainty. Any condition effect that also
  appears here is a formatting artifact.

Start with a small constructed benchmark with known ground truth; move to an
MMLU/ARC-style subset if budget allows. Hold out a task family for transfer.

## RUNS

- **Sweep (primary).** Grid over `(M, J+, J-)` at K = 3-4 rounds, many items, many
  reruns per item. Embarrassingly parallel, no outer optimizer loop, sufficient on
  its own for H1-H6. **Cache round-1 outputs** — before any message is exchanged an
  agent's output depends only on (item, seed, prompt) and is identical at every
  grid point. Use common random numbers across grid points.
- **Dynamics.** A few grid points, small N, **K = 25-50 rounds**, few items, many
  repeats. Dwell times, switch rates, volatility, and decision latency are
  estimable only here — a 3-5 round run cannot support a dwell-time distribution.
- **Optional refinement.** Only if the sweep shows an interior optimum: free the
  per-edge weights near it and test whether a learned `W` beats the two-scalar
  parameterization, under both `|w| <= w_max` and an L1 bound (a bare balance
  penalty admits large mutually-cancelling weights that mimic opponent structure
  while doing nothing). Budget the outer-step count honestly and get it approved
  first — an N×N evolutionary search over noisy fitness needs orders of magnitude
  more generations than a 10-hour window allows, which is why it is not primary.
- **Optional emergence run.** Unsigned non-negative gates, no support/challenge
  labels, no balance penalty, objective = task score − communication cost; infer
  each edge's causal sign post hoc by intervention. The only run permitted the word
  "emergent", and only against a signed, strength- and degree-preserving null with
  recurrence across ≥ 5 independent restarts.

## COMPUTE-MATCHED BASELINES — BEFORE ANY SWEEP

No accuracy claim may be reported before these exist. Match model calls **and**
total tokens, and report both.

The corners already supply self-consistency, independent majority vote, dense
debate, and parallel pools — run them as grid points so they share the exact
harness. Add, outside the grid: single direct answer, long single-agent
chain-of-thought, sequential single-agent revision, best-of-N with a validated
verifier, random topology at matched edge density, and a hand-designed
proposer-critic graph.

Independent majority vote is the load-bearing control for whether communication
helps at all; random topology at matched density for whether *cluster structure*
matters or only edge count does.

## MEASUREMENTS — SYSTEM-NATIVE NAMES ONLY

| Measure | Definition | Where |
|---|---|---|
| Accuracy / Brier / ECE | with CIs and effect sizes, per V and overall | all |
| Across-run dispersion | entropy of final answers over R reruns of one item | all |
| Population entropy trajectory | entropy of the population option distribution per round; narrowing latency after disambiguation | all |
| Belief volatility | mean absolute per-round change in an agent's option log-odds | dynamics |
| Dwell / switch statistics | time in a consensus state, switch rate, dwell-time distribution | dynamics |
| Pairwise error correlation | across agents — the direct measure of contagion | all |
| Cluster-answer MI | against a cluster-shuffled null | all |
| Decision latency | under adaptive stopping only | dynamics |

Because the V conditions differ in output length, report dispersion length- or
rate-matched alongside the raw number.

**Context-window confound.** N agents broadcasting per round overruns a 4096-token
window, so any truncation rule *is* a sparsity prior. Impose one explicit top-k
incoming-message cap, use the identical cap at every grid point and in every
baseline, pre-register it, and report it as a limitation.

## PERTURBATIONS AND ABLATIONS

Run the battery at three grid points — collapsed, metastable, incoherent — and
report how the response differs **by regime**. That regime-dependence is the
result; a battery run at one point is not informative.

- Misinformation injection (one confidently-wrong agent) — measure contagion
- Agent dropout; edge deletion
- Degree- and strength-preserving rewiring
- Support ↔ challenge label swap; sign flip on the strongest edges
- Global gain rescale in [0.5, 2.0] — **Channel L only**, where `w` multiplies
  log-odds. If routing depends only on signs, ranks, or top-k selection, rescaling
  proves nothing.
- Cluster count `M` swept independently of `N` — does the optimum track the number
  of viable options?
- `J- = 0` (non-negative coupling) — isolates the contribution of sign
- Personas on/off — do roles come from the structure or from the prompt?

Pre-register, in addition to Voronoi's standard fields: the item-calibration band,
the top-k context cap, the metastable band boundaries from H2, and the grid.

## INFRASTRUCTURE — HARD CONSTRAINTS

- Read the endpoint from environment variables — **never hardcode a hostname**;
  this demo ships with `pip install voronoi`. `VORONOI_LLM_BASE_URL` (original run
  used an internal vLLM host at `http://<host>:8000/v1`), `VORONOI_LLM_API_KEY`
  (`EMPTY` for local vLLM), `VORONOI_LLM_MODEL` (original run used
  `Qwen/Qwen2.5-3B-Instruct`, 4096 ctx).
- Verify reachability before any experiment: `curl "$VORONOI_LLM_BASE_URL/models"`.
  If the endpoint becomes unreachable, stop and report.
- Confirm the endpoint returns `logprobs`. If it does not, Channel L is
  unavailable — stop and report; do not silently fall back to Channel T only.
- Do NOT submit scheduler jobs (`sbatch`, `srun`, `qsub`), and do NOT start, stop,
  restart, or replace the inference server.
- Do NOT download or load another model without explicit human approval.
- asyncio with bounded parallelism; client-side concurrency <= 48.
- Wall-clock budget: 10 hours. All artifacts under `runs/<timestamp>/`.

## DELIVERABLES

- `experiment.py` — entry point; `--smoke` and full modes. Smoke must finish in
  ≤ 10 minutes: N=4, a 3-point grid, ≤ 5 items per condition.
- `analysis.py` — regenerates every figure and table from `runs/<timestamp>/`.
- `runs/<timestamp>/` — config, seeds, grid point per run, raw messages, logprobs,
  metrics, figures. Headline figure is the `(J+, J-)` regime diagram with the
  label-free metastable band and the accuracy peak overlaid.
- Manuscript-style report with the positioning table, **limitations**, and an
  explicit statement of which claims the design cannot support.

## GATES — STOP AND REQUEST HUMAN REVIEW

1. After pre-registration and the budget arithmetic for the grid.
2. After H0. A channel that fails is dropped — do not sweep a channel that carries
   no signed causal information.
3. After baselines plus smoke test, before spending the remaining wall clock.
4. Before any optional learned-`W` run.

## EXPECTED FAILURE MODES

- Challenge messages *raise* target log-odds — the salience trap (H0 detects it).
- The same 3B model is an unreliable verifier of itself, so the challenge channel
  carries no usable signal.
- Performance varies smoothly with `J+` and no interior optimum exists.
- An optimum exists but falls outside the label-free metastable band — that
  falsifies the attractor framing and leaves a mere tuning result. Say so plainly.
- Condition effects are floor or format artifacts (format-matched V=3 detects).
- Clusters never bind to hypotheses, so H3 collapses to the shuffled null.
- Nothing beats compute-matched self-consistency — a real, publishable negative.
- A condition ordering that fails to replicate is not automatically a failure: in
  the reference, one monkey showed the RT ordering across prior-information
  conditions and the other adopted a different strategy.

## NON-GOALS

- No benchmark SOTA chasing, no task-conditioned meta-controller, no heterogeneous
  model families, no infrastructure project.
- No biological implementation detail: no spikes, no millisecond timing, no
  membrane time constants, no fixed 80/20 ratio, no cortical layers, no
  STDP-as-optimizer, no "cortical column".
- Do not infer biological realism from one matched signature — many models
  reproduce a graded uncertainty ordering.

## PROMOTION PATH

If H0 passes and H1 plus H2 hold — an interior optimum inside a band predicted
from label-free dynamics — re-run the locked claim as a separate `PROVE`
investigation with `RIGOR EXPERIMENTAL` (adds replication). Do not attempt to lock
the question in this pass.

## REFERENCE

Rostami V., Rost T., Schmitt F. J., van Albada S. J., Riehle A., Nawrot M. P.
Spiking attractor model of motor cortex explains modulation of neural and
behavioral variability by prior target information.
Nature Communications 15:6304 (2024). doi:10.1038/s41467-024-49889-4

Take the *computational principle*: clustered attractors, local opponent balance
setting well depth, metastable winnerless competition, prior information removing
competitors rather than adding a mechanism, and a leaky-accumulator read-out. Do
not import its connectivity as a claim — it was built in by design — and do not
import its spike statistics as metrics.
