# Demo: Opponent Routing in a Society of Small Language Models

**Does learned sparse support/challenge routing between frozen SLMs improve collective inference per unit of compute — and does opponent structure recur across independent searches?**

A neuroscience-motivated but claim-disciplined study of *signed* communication graphs over a single frozen small language model. Agents are homogeneous; only the routing graph is learned. The question is whether a bounded negative channel buys anything real once compute is matched against strong single-agent baselines.

## What It Does

Optimizes a signed adjacency matrix `W` over N frozen SLM instances at inference time — no fine-tuning, no post-training. Positive edges forward a message as support, negative edges as challenge. The objective is task score minus token cost, an L1 influence bound, and a local-balance penalty.

### Two Channels

| Channel | Mechanism | Role |
|---|---|---|
| **L — logit-level** | `w_ij` multiplies the sender's option log-probabilities, aggregated on the answer simplex | Primary mechanism arm. Challenge is genuinely subtractive and `w` has defined gain. |
| **T — text-level** | Support/challenge framing injected into context | Deployability arm. Most likely to fail construct validation. |

The L-vs-T gap is itself a result: it measures whether prompt-level critique carries real signed information.

### Four Arms

| Arm | Purpose | Config |
|---|---|---|
| **A** | Optimization — learns `W` | N=8–12, K=3–4 rounds, many items |
| **B** | Dynamics — volatility, dwell/switch, latency | Frozen `W`, K=25–50 rounds |
| **E** | Clean emergence — unsigned gates, no labels, no balance penalty; signs inferred post hoc by intervention | The only arm allowed to say "emergent" |
| **H** | Hierarchy — evidence-facing vs hypothesis-facing modules, bidirectional routing | Tests top-down/bottom-up, which is orthogonal to sign |

### Gating Hypothesis

**H0 (construct validation)** runs first and gates everything else: does a challenge message actually *lower* the target agent's log-odds on the proposition it names, versus a token-matched neutral control? A channel that fails H0 is dropped from the study and the failure is reported as the finding.

## Claim Discipline

This demo is deliberately conservative about its neuroscience framing. Three claims are forbidden in every artifact:

1. No "spontaneous E/I emergence" in any arm that supplies signed semantics or a balance regularizer — signed structure is objective-induced there by construction.
2. No calling a negative edge "inhibition" before H0 passes for that channel.
3. No use of the names *Fano Factor* or *CV2* — messages are not a point process. System-native metric names only.

The reference model ([Rostami et al. 2024](https://doi.org/10.1038/s41467-024-49889-4)) introduced paired E/I clusters **by construction** with fixed connectivity. What emerged there was metastable winnerless competition, not the topology. The demo uses the paper as a *protocol and statistics* template, not as evidence for emergent connectivity.

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

Three human gates stop the run: after the budget arithmetic, after H0 construct validation, and after compute-matched baselines plus smoke test. The full search does not launch without explicit approval.
