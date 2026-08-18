# Opponent Routing: Does Locally Balanced Support/Challenge Structure Improve Collective Inference in a Society of Small Language Models?

MODE
DISCOVER

RIGOR
SCIENTIFIC

## RESEARCH GOAL

Test whether learned, sparse, signed routing of support and challenge messages
between frozen small language models (SLMs) improves held-out collective
accuracy, calibration, and robustness **per unit of inference compute**, and
whether the learned routing develops reproducible opponent structure.

This is an inference-time architecture search over a communication graph around
a frozen endpoint. It is not model training, post-training, or fine-tuning.

## SCOPE AND CLAIM DISCIPLINE — READ FIRST

This investigation transfers four *computational principles* from systems
neuroscience: opponent regulation, hierarchical recurrence, uncertainty-dependent
gain, and metastable hypothesis competition. It does **not** claim that language
model instances are neurons, that edges are synapses, or that anything here is
biological excitation/inhibition.

Three claims are explicitly forbidden in every artifact this investigation
produces:

1. **Do not claim E/I connectivity "emerged spontaneously" in any arm that
   supplies signed semantics or a balance regularizer.** Signed structure is
   objective-induced there by construction. Only Arm E (below) can speak to
   emergence, and only weakly.
2. **Do not call a negative edge "inhibition" until H0 passes for that channel.**
   Until then the term is *challenge channel*. A negative text label adds tokens;
   it can lower, raise, or merely increase the salience of a proposition.
3. **Do not use the names Fano Factor or CV2.** Those are spike-count dispersion
   and adjacent-interval irregularity statistics for point processes. Messages are
   not a point process. Use the system-native metric names defined in MEASUREMENTS.

Prior-work honesty requirement: Rostami et al. (2024) introduced paired E/I
clusters **by construction** with fixed connectivity, and explicitly left learning
that topology to future work. What emerged in that model was metastable winnerless
competition and the task-dependent variability signature — not the connectivity.
Any statement implying the paper showed E/I structure emerging is a
misrepresentation and must be caught in review.

## BACKGROUND

Multi-agent LLM systems overwhelmingly use non-negative coupling: proposer pools,
broadcast debate, majority vote, or one global judge. This has two known failure
modes — premature consensus and error contagion — and multi-agent debate frequently
loses to a strong single-agent baseline at matched token budget.

Two independent literatures suggest the missing ingredient is a *bounded,
targeted, negative* channel:

- **Systems neuroscience.** Opponent (E/I) regulation keeps a recurrent system at
  an operating point where the residual carries information, prevents runaway
  positive feedback, and supports metastable competition among hypotheses rather
  than winner-take-all collapse.
- **Machine learning.** The generator-verifier gap says checking is easier than
  producing, and mixture-of-experts routing already relies on an auxiliary
  load-balancing loss — a balance regularizer over routing, in ML-native terms.

The question is whether a learned signed graph over a *fixed* policy ensemble buys
anything real once compute is properly matched.

## PRIOR WORK — THE LITERATURE SCAN MUST POSITION AGAINST ALL SIX CLUSTERS

Produce an explicit positioning table. For each cluster state: what it does, what
this study does differently, and which baseline it contributes.

1. **Agent-graph optimization.** GPTSwarm (agents as optimizable graphs), DyLAN,
   ADAS, AFlow, Mixture-of-Agents. These already optimize topology with
   **non-negative** edges. The delta claimed here is signed edges + bounded
   opponent influence + causal validation of the negative channel. If the write-up
   cannot articulate that delta, there is no contribution.
2. **Inference-time reasoning (the real comparators).** Chain-of-thought,
   self-consistency, best-of-N, Tree of Thoughts, adaptive test-time compute
   scaling.
3. **Generator-verifier gap.** Verifier training, process supervision, generative
   verifiers, repeated-sampling coverage-vs-precision results. A prompted copy of
   the same 3B model is **not** automatically a reliable verifier — this is the
   single most likely reason the challenge channel fails.
4. **Debate and its negative results.** Multiagent debate, debate for truthfulness,
   persuasive-debater results, and the negative findings that debate often
   underperforms compute-matched single-agent reasoning.
5. **Parameter post-training (why it is out of scope).** STaR, RLHF, RLVR, GRPO,
   RL-trained reasoning models. The frozen endpoint cannot do any of these. State
   explicitly that this study manipulates interaction structure, not weights, and
   that results may not transfer to reasoning-post-trained models.
6. **ReAct and tool use.** ReAct interleaves reasoning with external actions and
   observations; it is *not* ordinary multi-round peer discussion. It is a
   comparator only for Arm H (below), which has evidence acquisition. Do not list
   it as a baseline for peer MCQ deliberation.

## HYPOTHESES

**H0 — CONSTRUCT VALIDATION (gating; everything else is void without it).**
For each channel independently, a support message reliably increases, and a
challenge message reliably decreases, the *target agent's log-odds on the specific
proposition named in the message*, relative to both a no-message control and a
token-matched neutral-message control.
- Measure per-channel signed causal effect size with confidence intervals.
- A channel that fails H0 is **dropped from the study**, not carried forward with
  a caveat. Report the failure as a finding.

**H1 — PRIMARY.** At equal model calls and equal total tokens, learned sparse
support/challenge routing improves held-out accuracy and proper score (Brier)
over the strongest compute-matched baseline.

**H2 — ROBUST PLURALISM.** Bounded opponent feedback preserves alternative
hypotheses before decisive evidence arrives, then converges after it — and
recovers better from injected false evidence, agent dropout, and corrupted
messages than dense non-negative coupling at matched compute.

**H3 — DISPERSION AS FREE CONFIDENCE.** Across-run answer dispersion predicts
per-item correctness without ground truth, giving a usable abstain/escalate
signal. Report AUC against the model's own verbalized confidence and against
mean token log-probability as baselines.

**H4 — ADAPTIVE CONTROL.** Uncertainty-gated routing (more rounds and more
challenge edges on ambiguous items) improves the accuracy-calibration-token
Pareto frontier over fixed-depth deliberation.

**H5 — HIERARCHICAL RECURRENCE (Arm H only).** Bidirectional
evidence-to-hypothesis and hypothesis-to-evidence routing beats one-way,
direction-shuffled, and all-to-all routing on tasks requiring information
acquisition.
- Note: top-down/bottom-up is **orthogonal** to opponent sign. Feedforward and
  feedback pathways both contain excitation and inhibition. A peer-only MCQ graph
  has no hierarchy to discover; H5 requires evidence-facing and hypothesis-facing
  modules by construction.

**H6 — EXPLORATORY STRUCTURE.** Task-selective opponent motifs recur across
independent optimizer restarts and transfer to held-out task families, beyond a
signed, strength- and degree-preserving null model.
- Recurrence across restarts is the evidential bar. Finding structure once is not
  a result; the same structure appearing from independent random inits is.

## SUBSTRATE

- N = 8-16 logical agents (start at 8; justify any increase with the budget model).
- All agents share **one frozen SLM** behind a single OpenAI-compatible endpoint.
- Do not load additional models. Do not spawn one process per agent. Do not use
  heterogeneous model families.
- **Primary condition uses identical, neutral system prompts.** Agents differ only
  by sampling seed. Personas contradict the homogeneous-substrate premise and can
  themselves manufacture roles — personas are an **ablation**, never the default.

## THE TWO CHANNELS

Learn one scalar gate `w_ij` per ordered pair. Positive = support, negative =
challenge, near-zero = no edge. Initialize random signed sparse. **Do not
initialize E/I blocks.**

**Channel L — logit-level (primary mechanism arm).**
Request `logprobs` from the endpoint over the answer-option tokens. Aggregate
signed influence directly on the option simplex:

```
logit_j[option] <- own_logit_j[option] + sum_i w_ij * logprob_i[option]
p_j = softmax(logit_j)
```

This makes challenge genuinely subtractive, gives `w_ij` a defined gain, yields a
principled decision variable, and replaces badly-calibrated verbalized confidence
from a 3B model. Channel L is the arm where H0 can actually be satisfied.

**Channel T — text-level (deployability arm).**
Forward the message with a support or challenge framing in context. This is what
a real deployed system can do when logprobs are unavailable. It is the arm most
likely to fail H0.

Run H0 on both. Report the L-vs-T gap — that gap *is* a publishable result about
whether prompt-level critique carries real signed information.

**Mandatory gain calibration (before any optimization).** Sweep a single edge's
`|w|` and measure influence on the target's option distribution. If the mapping
is not monotone, the learned W is uninterpretable and every downstream claim is
void. Report the dose-response curve.

## TASK DESIGN

**Protocol correction.** In Rostami et al., PS presents one, two, or three
*possible targets* and RS **resolves the ambiguity by identifying the final
target**. RS is not a bare "decide now" signal. Replicate that structure:

- Use a sequential-evidence task with a **constant answer-option set**.
- PS analog: cue the subset of options still viable (1, 2, or 3) → conditions
  C1/C2/C3 with graded prior information.
- RS analog: deliver **final disambiguating evidence** that resolves the item.
- A "decide now" prompt with no disambiguating evidence is not a valid RS analog.

**Item calibration (mandatory).** Qwen2.5-3B-class models will floor on hard MCQ
items, and floor effects manufacture spurious condition differences. Pre-select
items whose single-agent accuracy falls in a pre-registered band (e.g. 0.35-0.85)
so all three conditions have headroom. Report the band and the screening run.

**Format-matched control condition (mandatory).** Add C3-matched: three options
cued, but two trivially eliminable. This holds prompt length and format constant
while varying real uncertainty — the analog of matched visual stimulation. Any
condition effect that also appears in C3-matched is a formatting artifact.

Start with a small constructed benchmark with known ground truth, then move to an
MMLU/ARC-style subset if budget allows. Hold out a task family for H6 transfer.

## ARMS

- **Arm A — optimization.** N=8-12, K=3-4 rounds, many items. Learns W. Latency and
  metastability are *not* measurable here.
- **Arm B — dynamics.** Frozen learned W, small N, **K=25-50 rounds**, few items,
  many repeats. This is the only arm where volatility, dwell/switch statistics,
  and decision latency are estimable. Cheap: no outer loop.
- **Arm E — clean emergence.** Neutral identical prompts, **unsigned** non-negative
  gates controlling only whether i's message reaches j, **no** support/challenge
  labels, **no** balance regularizer. Objective = task score − communication cost
  only. Then infer each edge's causal influence sign *post hoc* by intervention.
  Emergence evidence = agent-consistent bimodal inferred signs + clustering +
  recurrence across restarts, against a signed strength-preserving null. This is
  the only arm permitted to use the word "emergent".
- **Arm H — hierarchy (H5).** Evidence-facing modules (retrieval/tool/compute) and
  hypothesis-facing modules, with routing learned in both directions.

## OBJECTIVE

```
maximize   task_score
         - c_tok * total_tokens
         - c_L1  * sum_ij |w_ij|          # bounds total absolute influence
         - lambda * sum_i (sum_j w_ji)^2  # local balance (Arm A only)
subject to |w_ij| <= w_max
```

The L1 term and the `w_max` bound are **required**. A bare squared-net-input
penalty permits arbitrarily large mutually-cancelling weights, which is a
degenerate solution that will look like strong opponent structure while doing
nothing.

No explicit E/I role labels. No structural block prior. No additional LLM judge.

**A deterministic read-out is required and is not a "global judge."** Rostami et
al. used an explicit leaky accumulator read-out; do the same here (accumulate the
population option distribution over rounds, threshold to decide). "No global
judge" means no extra LLM arbiter, not no read-out.

## OPTIMIZATION AND BUDGET — HARD GATE

Default: evolutionary search over W (robust, reproducible). GRPO or TextGrad may
be discussed but must not be a dependency.

**Compute the budget before writing the optimizer, and put it in the
pre-registration.** Generations per candidate evaluation:

```
G = conditions x items x N x K
```

Worked example at C=3, T=8, N=12, K=4 → 1,152 generations per candidate. With an
ES population of 16 (antithetic pairs) → ~18,400 per outer step. A 10-hour budget
at 48 concurrency and ~1.2 s/generation, at a realistic 60% utilization, is
~8.6e5 generations total — roughly **50-150 outer steps, not 1,000.** The draft
target of 1,000 steps is infeasible by more than an order of magnitude.

Mandatory budget-recovery measures:
- **Cache round-1 outputs.** At round 1 no messages have been exchanged, so each
  agent's output depends only on (item, seed, prompt) — identical across every
  candidate W and every outer step. Free saving of a factor K/(K−1).
- **Common random numbers** across candidates (same items, same seeds) — large ES
  variance reduction.
- Mirrored/antithetic sampling and rank-based updates.
- Reduce N before reducing items; noisy fitness is worse than a smaller graph.

**Context-window confound.** With N agents broadcasting per round, incoming
context exceeds a 4096-token window quickly, so any truncation rule *is* a
sparsity prior. Impose an explicit top-k incoming-message cap, use the **same cap
in every arm and every baseline**, pre-register it, and report it as a limitation.
Sparsity claims are only valid within the cap.

## COMPUTE-MATCHED BASELINES — MANDATORY, RUN BEFORE OPTIMIZATION

No accuracy claim may be reported before these exist. Match model calls *and*
total tokens, and report both.

1. Direct answer (single call)
2. Long single-agent chain-of-thought
3. Self-consistency (majority over N samples)
4. Independent majority vote across N agents, no communication
5. Sequential single-agent revision
6. Best-of-N with a validated verifier
7. Dense all-to-all debate (the current multi-agent default)
8. Random sparse routing (topology control)
9. Learned **unsigned** routing (this isolates the contribution of sign)
10. Fixed hand-designed proposer-critic routing (structure without search)
11. ReAct — **only** in Arm H, where tools/retrieval exist

Baseline 9 is the load-bearing control for the entire study. Baseline 4 is the
load-bearing control for whether communication helps at all.

## MEASUREMENTS — SYSTEM-NATIVE NAMES ONLY

- **M1 Accuracy and proper score.** Held-out accuracy, Brier, ECE, with CIs and
  effect sizes, per condition and overall.
- **M2 Across-run answer dispersion.** Entropy of final answers over R independent
  reruns of the same item under the same W. Report per condition. Because the
  conditions differ in output length, report a length-matched or
  rate-matched comparison alongside the raw one.
- **M3 Population entropy trajectory.** Entropy over the population option
  distribution across rounds; measure narrowing after RS evidence and its latency.
- **M4 Belief volatility.** Mean absolute change in an agent's option log-odds
  between consecutive rounds (Arm B only — needs K >= 25).
- **M5 Pairwise error correlation.** Across agents; the direct measure of error
  contagion and echo chambers.
- **M6 Dwell and switch statistics.** Time in consensus states, switch rate,
  dwell-time distribution (Arm B only). This is the closest real analog to the
  metastable winnerless competition the reference model actually produced.
- **M7 Decision latency.** Only under **adaptive stopping**. A fixed 3-5 rounds
  cannot support a latency distribution — it takes at most 5 values.
- **M8 Structure.** Signed modularity vs a signed strength- and degree-preserving
  null (not a naive shuffle); sign-consistency index per agent (what fraction of
  agents have sign-consistent out-edges); alignment of challenge edges with
  semantic similarity between agents (do agents challenge their nearest
  competitors?); hierarchy/DAG-ness index for Arm H; **motif recurrence across >= 5
  independent optimizer restarts**; transfer to the held-out task family.

Interpretation caution for condition effects: in the reference paper, the strong
RT condition ordering held for monkey M1, while M2 adopted a different strategy
and showed similar RTs across conditions. A single ordering that fails to replicate
is not automatically a failure of the model.

## ROBUSTNESS — PERTURBATION BATTERY

Global rescaling by alpha is meaningful **only for Channel L**, where `w`
multiplies log-odds. If routing depends only on signs, rankings, normalization, or
top-k selection, alpha does nothing and proves nothing. Run the battery instead:

- Edge deletion (drop the strongest x% of edges)
- Agent dropout
- Misinformation injection (one confidently-wrong agent) — measure contagion
- Degree- and strength-preserving rewiring
- Channel swap (flip support <-> challenge labels)
- Sign flip on top-k edges
- Gain rescale alpha in [0.5, 2.0] — Channel L only

## ABLATIONS

- **A0 (discriminating, required).** Local balance vs **global** balance
  `(sum_ij w_ij)^2`. Global balance also produces negative weights but should not
  produce per-agent paired structure. If both give the same modularity z-score,
  the structural claim is dead. This is the ablation that separates a real result
  from a redescription of the regularizer.
- **A1.** Remove the balance regularizer entirely.
- **A2.** Non-negative weights only.
- **A3.** Personas on vs off (tests whether roles come from the graph or the prompt).
- **A4.** Sweep lambda and K; report the explore-exploit frontier. A single scalar
  shifting the behavioral profile is the closest analog to the reference paper's
  cross-monkey comparison.

## PRE-REGISTRATION REQUIREMENTS

`RIGOR SCIENTIFIC` gates dispatch on the pre-registration. Supply all of:
HYPOTHESIS, METHOD, CONTROLS, EXPECTED_RESULT, CONFOUNDS, STAT_TEST, SAMPLE_SIZE,
POWER_ANALYSIS, SENSITIVITY_PLAN.

- POWER_ANALYSIS: powering for the H1 accuracy delta and the H0 causal effect
  size, given item count and rerun count.
- SENSITIVITY_PLAN: the lambda / K / c_tok sweeps and the perturbation battery.
- Pre-register the item-calibration band, the top-k context cap, the number of
  optimizer restarts, and the multiple-comparison correction across conditions.

## INFRASTRUCTURE — HARD CONSTRAINTS

- Read the endpoint from environment variables. **Do not hardcode a hostname**;
  this demo ships with `pip install voronoi`.
  - `VORONOI_LLM_BASE_URL` (original run used an internal vLLM host at
    `http://<host>:8000/v1`)
  - `VORONOI_LLM_API_KEY` (`EMPTY` for local vLLM)
  - `VORONOI_LLM_MODEL` (original run used `Qwen/Qwen2.5-3B-Instruct`, 4096 ctx)
- Verify reachability before any experiment: `curl "$VORONOI_LLM_BASE_URL/models"`.
- Confirm the endpoint returns `logprobs`. If it does not, Channel L is
  unavailable — stop and report; do not silently fall back to Channel T only.
- Do NOT submit SLURM jobs. No `sbatch`, `srun`, `qsub`, or any scheduler command.
- Do NOT start, stop, restart, or replace the inference server.
- Do NOT download or load another model without explicit human approval.
- If the endpoint becomes unreachable, stop and report.
- Use asyncio with bounded parallelism; client-side concurrency <= 48.
- Wall-clock budget: 10 hours. All artifacts under `runs/<timestamp>/`.

## DELIVERABLES

- `experiment.py` — entry point; `--smoke` and full modes.
- `analysis.py` — regenerates every figure and table from `runs/<timestamp>/`.
- `pyproject.toml` or `requirements.txt` — minimal dependencies.
- `runs/<timestamp>/` — config, seeds, learned W per restart, raw messages,
  logprobs, metrics, figures.
- Manuscript-style report: intro, methods, results, **limitations**, next
  experiments — including the positioning table and the explicit statement of
  which claims the design cannot support.
- Smoke mode must finish in <= 10 minutes: N=4, <= 5 outer steps, <= 5 items per
  condition.

## GATES — STOP AND REQUEST HUMAN REVIEW

1. **After literature scan + pre-registration + budget arithmetic.** Do not write
   the optimizer until the projected outer-step count is approved.
2. **After H0 construct validation.** If a channel fails H0, stop; do not optimize
   a channel that carries no signed causal information. Report it as the finding.
3. **After baselines + smoke test.** Do not spend the remaining wall-clock on the
   full search until baselines exist and a human approves.

## EXPECTED FAILURE MODES TO WATCH

- The optimizer learns superficial prompt conventions rather than signed
  interaction structure (A3 and H0 are the detectors).
- Challenge messages raise rather than lower target log-odds — the salience trap.
- The same 3B model is an unreliable verifier of itself, so the negative channel
  carries no usable signal.
- Condition effects are floor/format artifacts (C3-matched is the detector).
- Structure appears once but does not recur across restarts.
- Degenerate large mutually-cancelling weights satisfy the balance penalty while
  doing nothing (the L1 bound is the detector).
- No arm beats compute-matched self-consistency, which would be a real and
  reportable negative result.

## NON-GOALS

- Do not chase benchmark SOTA.
- Do not build a task-conditioned meta-controller in this PoC.
- Do not use heterogeneous model families.
- Do not turn this into an infrastructure project.
- Do not copy biological implementation detail: no spikes, no millisecond timing,
  no membrane time constants, no fixed 80/20 E/I ratio, no cortical layers, no
  STDP-as-optimizer, no "cortical column".
- Do not infer biological realism from a single matched signature — many models
  reproduce graded uncertainty orderings.

## PROMOTION PATH

If H0 passes for a channel and H1 shows a compute-matched improvement with
recurring structure across restarts, re-run the locked claim as a separate
`PROVE` investigation with `RIGOR EXPERIMENTAL` (adds replication). Do not attempt
to lock the question in this pass.

## REFERENCE

Rostami V., Rost T., Schmitt F. J., van Albada S. J., Riehle A., Nawrot M. P.
Spiking attractor model of motor cortex explains modulation of neural and
behavioral variability by prior target information.
Nature Communications 15:6304 (2024). doi:10.1038/s41467-024-49889-4

Use the paper as the *protocol and statistics* template — graded prior
information, disambiguation at RS, condition-wise comparison, leaky-accumulator
read-out. Do not import its connectivity as a claim; it was built in by design.
