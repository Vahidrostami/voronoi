# Demo: The Forgetting Cure

**Can brain-inspired mechanisms solve catastrophic forgetting in neural networks?**

A computational neuroscience experiment where 4 parallel agents each implement a different
brain-inspired anti-forgetting strategy, then a 5th agent discovers the optimal hybrid.

## What It Does

Trains neural networks (built from scratch, no PyTorch) on 5 sequential MNIST tasks.
Tests whether neuroscience-inspired mechanisms prevent catastrophic forgetting:

| Strategy | Brain Inspiration | Agent |
|---|---|---|
| Synaptic Consolidation (EWC) | Long-term potentiation | agent-ewc |
| Neurogenesis | Hippocampal neurogenesis | agent-neurogenesis |
| Sleep Replay | Sharp-wave ripples | agent-replay |
| Complementary Learning | Hippocampus + neocortex | agent-cls |

## How to Run

### Option A: Autopilot (fully automated)
```bash
./scripts/swarm-init.sh
./scripts/autopilot.sh --prompt demos/forgetting-cure/PROMPT.md --safe
```

### Option B: Interactive
```bash
./scripts/swarm-init.sh
copilot
> /swarm Build from demos/forgetting-cure/PROMPT.md
```

## Wave Structure

```
Wave 1: core foundation (matrix ops, base network, MNIST loader)
Wave 2: 5 strategies in parallel (naive, ewc, neurogenesis, replay, cls)
Wave 3: hybrid combiner (mixes strategies)
Wave 4: experiment runner + report generator
```

## Output

- `output/results.csv` — accuracy table for all strategies
- `output/accuracy_matrix.png` — heatmap of who forgot what
- `output/learning_curves.png` — forgetting cliffs visualized
- `output/backward_transfer.png` — strategy comparison bar chart
- `output/discovery.md` — auto-generated findings summary

## Why This Demo

- **Novel results**: the specific hybrid recipe the swarm discovers is new
- **Parallelism matters**: 5 strategies built simultaneously, then combined
- **No heavy deps**: pure Python math, matplotlib for charts
- **Real science**: maps directly to active neuroscience research
- **Visual output**: heatmaps and curves tell the story at a glance
