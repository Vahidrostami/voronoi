# The Forgetting Cure: Can Brain-Inspired Mechanisms Solve Catastrophic Forgetting?

Build a computational neuroscience experiment that pits 4 brain-inspired anti-forgetting strategies against each other, then discovers whether combining them (like real brains do) produces emergent robustness that no single mechanism achieves alone.

## Background

Catastrophic forgetting is the biggest unsolved problem in continual learning: train a neural network on Task B and it forgets Task A. Biological brains don't do this — they use multiple overlapping mechanisms (synaptic consolidation, neurogenesis, memory replay, dual memory systems). No one has systematically tested all 4 mechanisms head-to-head on identical architectures AND then combined them to find the optimal hybrid.

## The Experiment

### Task Sequence (what the networks must learn)

The networks face a sequence of 5 classification tasks, each trained for 50 epochs:

1. **MNIST digits 0-1** (binary classification)
2. **MNIST digits 2-3**
3. **MNIST digits 4-5**
4. **MNIST digits 6-7**
5. **MNIST digits 8-9**

After learning all 5 tasks sequentially, the network is tested on ALL tasks. The key metric: **Backward Transfer** — how much of Task 1 accuracy survives after learning Task 5?

### Neural Network Architecture

All strategies use the same base network (implemented from scratch, no PyTorch/TensorFlow):

```python
# Simple feedforward network
# Input: 784 (28x28 flattened MNIST images)
# Hidden 1: 256 neurons, ReLU
# Hidden 2: 128 neurons, ReLU  
# Output: 2 neurons per task head (10 total), softmax
# Learning rate: 0.01, mini-batch SGD, batch size 32
```

Implement backpropagation from scratch using only Python stdlib + basic matrix operations. No numpy allowed for the core math — build your own matrix multiply, relu, softmax. (numpy IS allowed for loading MNIST data only.)

### The 4 Brain-Inspired Strategies

#### Strategy 1: Synaptic Consolidation (EWC — Elastic Weight Consolidation)
*Inspired by: Long-term potentiation in hippocampus*

After learning each task, compute the Fisher Information Matrix for each weight — this measures how important each weight is for the current task. When learning the next task, add a penalty that prevents important weights from changing much.

```
Loss = Task_Loss + λ * Σ F_i * (θ_i - θ*_i)²
```
Where F_i is Fisher information, θ*_i is the weight value after previous task, λ=1000.

#### Strategy 2: Neurogenesis (Progressive Growing)
*Inspired by: Adult hippocampal neurogenesis*

For each new task, grow new neurons in the hidden layers (add 32 neurons per layer per task). Freeze the weights of existing neurons — they are "mature." Only train the new neurons plus the new task head. Old knowledge is literally preserved in old neurons.

#### Strategy 3: Sleep Replay (Experience Replay with Distortion)
*Inspired by: Hippocampal sharp-wave ripples during sleep*

After each training epoch, "dream" by replaying 100 samples from all previous tasks. But — crucially — replay them with distortion: add Gaussian noise (σ=0.1), randomly shift images by 1-2 pixels, sometimes replay partial images. This mimics the compressed, noisy replay observed in sleeping brains.

Between each task, run a "sleep phase" of 10 epochs of pure replay (no new data).

#### Strategy 4: Complementary Learning Systems (CLS — Dual Memory)
*Inspired by: McClelland et al.'s CLS theory — hippocampus + neocortex*

Maintain TWO networks:
- **Fast learner (hippocampus):** Small network (64-32 neurons), high learning rate (0.05), learns new tasks quickly but forgets fast
- **Slow learner (neocortex):** Large network (256-128 neurons), low learning rate (0.001), receives "interleaved teaching" from the fast learner

Training loop: Fast learner trains on new task → then teaches Slow learner by generating pseudo-examples → Slow learner trains on mix of pseudo-examples from all tasks the Fast learner has seen.

Test only the Slow learner.

### Control: Naive Sequential (No Protection)
Train the same base network on all 5 tasks sequentially with no anti-forgetting mechanism. This is the baseline that shows how bad catastrophic forgetting is.

## Architecture

### Shared Foundation (src/core/) — BUILD FIRST

- `matrix.py`: Matrix operations from scratch — multiply, transpose, element-wise ops, broadcasting. No numpy.
- `network.py`: Base neural network class — forward pass, backprop, weight access, save/load weights, gradient computation.
- `mnist.py`: MNIST data loader (download + parse IDX format). This file alone may use numpy or struct for binary parsing. Provide a function that returns (train_images, train_labels, test_images, test_labels) as plain Python lists.
- `metrics.py`: Accuracy, backward transfer, forward transfer, forgetting measure calculations. Also logs per-task accuracy after each task is learned.
- `config.py`: All hyperparameters (learning rates, layer sizes, epochs, batch sizes, λ for EWC, etc.)

Standard interface all strategies must implement:

```python
class Strategy:
    def __init__(self, config):
        """Initialize network(s) and any strategy-specific state."""
        pass
    
    def train_task(self, task_id, train_data, train_labels, epochs):
        """Train on a new task. Handle anti-forgetting internally."""
        pass
    
    def evaluate(self, test_data, test_labels, task_id):
        """Evaluate accuracy on a specific task."""
        return accuracy
    
    def on_task_complete(self, task_id):
        """Called after each task finishes. Compute Fisher, grow neurons, etc."""
        pass
    
    def get_all_accuracies(self, test_sets):
        """Return dict of {task_id: accuracy} for all tasks seen so far."""
        pass
```

### Strategy Modules (src/strategies/*/) — BUILD IN PARALLEL after core

Each strategy module must:
- Import and use the base network/matrix classes from src/core/
- Implement the Strategy interface from src/core/network.py
- Handle its own anti-forgetting logic internally
- Be fully self-contained (no cross-strategy imports)
- Log training progress to stdout

#### File scope per strategy:
- `src/strategies/naive/naive.py` — Baseline (no protection)
- `src/strategies/ewc/ewc.py` — Elastic Weight Consolidation
- `src/strategies/neurogenesis/neurogenesis.py` — Progressive growing
- `src/strategies/replay/replay.py` — Sleep replay with distortion
- `src/strategies/cls/cls.py` — Complementary Learning Systems

Each directory also has an `__init__.py` that exports the strategy class.

### Hybrid Discovery (src/hybrid/) — BUILD AFTER all strategies tested

- `combiner.py`: Takes the 4 strategy implementations and creates hybrid combinations:
  - EWC + Replay (consolidation + dreaming)
  - Neurogenesis + CLS (growing + dual memory)
  - All 4 combined (the "full brain")
  - Top 2 performers combined
- Test all hybrids on the same task sequence
- Identify which combination achieves the best backward transfer

### Experiment Runner (src/main.py + src/report.py) — BUILD LAST

- `main.py`: Runs the full experiment:
  1. Download/prepare MNIST
  2. Run Naive baseline
  3. Run all 4 strategies (can be sequential — each takes ~2 min)
  4. Run hybrid combinations
  5. Generate report

- `report.py`: Generates output:
  1. **CSV**: `output/results.csv` — columns: strategy, task_1_acc, task_2_acc, ..., task_5_acc, avg_accuracy, backward_transfer, forgetting_measure
  2. **Accuracy matrix heatmap**: `output/accuracy_matrix.png` — rows = strategies, columns = tasks, color = accuracy. Shows at a glance who forgot what.
  3. **Learning curves**: `output/learning_curves.png` — For each strategy, plot Task 1 accuracy over time as Tasks 2-5 are learned. The "forgetting cliff" should be visible for Naive.
  4. **Backward transfer bar chart**: `output/backward_transfer.png` — Single chart comparing all strategies + hybrids.
  5. **Discovery summary**: `output/discovery.md` — Auto-generated markdown summarizing:
     - Which single strategy won?
     - Did any hybrid beat all individuals?
     - What's the optimal "brain recipe"?
     - Specific surprising findings (e.g., "Replay alone preserved 73% of Task 1 accuracy while Naive preserved only 12%")
  6. **JSON data**: `output/results.json` — Machine-readable experiment data for the webapp. Structure:
     ```json
     {
       "strategies": {
         "naive": {
           "name": "Naive (No Protection)",
           "brain_region": "None",
           "description": "Sequential training with no anti-forgetting mechanism",
           "accuracies_after_each_task": [[t1], [t1,t2], [t1,t2,t3], ...],
           "final_accuracies": [t1_acc, t2_acc, t3_acc, t4_acc, t5_acc],
           "backward_transfer": -0.68,
           "forgetting_measure": 0.71,
           "weight_snapshots": [[epoch, layer, values], ...]
         },
         "ewc": { ... },
         "neurogenesis": { ... },
         "replay": { ... },
         "cls": { ... },
         "ewc_replay": { ... },
         "neurogenesis_cls": { ... },
         "full_brain": { ... }
       },
       "tasks": ["digits_0_1", "digits_2_3", "digits_4_5", "digits_6_7", "digits_8_9"],
       "best_single": "replay",
       "best_hybrid": "full_brain",
       "discovery_text": "..."
     }
     ```

### Interactive Webapp (output/index.html) — BUILD IN PARALLEL with runner

A single self-contained HTML file that visualizes the experiment results. Opens in any browser, no server needed. Reads `output/results.json` for data.

**Tech stack**: Vanilla HTML/CSS/JS + Chart.js via CDN (`<script src="https://cdn.jsdelivr.net/npm/chart.js">`). No React, no build step, no npm. Everything in ONE file.

**Design**: Dark theme, neuroscience aesthetic (deep navy background, glowing accent colors). Smooth scroll between sections. Responsive (works on phone too).

#### Section 1: Hero — "The Forgetting Lab"
- Full-viewport intro with animated title
- Subtitle: *"Can artificial neural networks learn like biological brains?"*
- Animated MNIST digits fading in one by one (use base64-encoded tiny PNGs or CSS-drawn digits)
- "Explore Results ↓" button scrolls to next section

#### Section 2: The Problem — "The Forgetting Cliff"
- Interactive line chart (Chart.js) showing Task 1 accuracy over time for ALL strategies
- X-axis: training timeline (Task 1 → Task 2 → ... → Task 5 epochs)
- Y-axis: Task 1 accuracy (0-100%)
- Naive shows a dramatic cliff. Strategies show varying degrees of protection.
- Checkboxes to toggle each strategy on/off
- Hover tooltip shows exact accuracy at each point
- Below the chart: a brief text explanation of catastrophic forgetting

#### Section 3: Strategy Cards — "Four Brains, Four Solutions"
- 4 cards in a grid (2x2 on desktop, stacked on mobile)
- Each card has:
  - Brain-region SVG icon (simple, abstract — a hippocampus shape for EWC, branching neurons for neurogenesis, sleep waves for replay, two connected brains for CLS)
  - Strategy name + neuroscience inspiration
  - Key stat: backward transfer percentage, large and bold
  - Click/tap to expand: shows that strategy's individual learning curve chart + weight heatmap image (load from `output/ewc_weights.png` etc, or render inline if data is in JSON)
- Color-coded: each strategy has a consistent color throughout the page

#### Section 4: Head-to-Head — "The Accuracy Matrix"
- Interactive heatmap grid: rows = strategies (including hybrids), columns = tasks
- Each cell shows accuracy %, colored from red (0%) through yellow (50%) to green (100%)
- Hover: shows full detail ("EWC: Task 3 accuracy = 87.3% after learning all 5 tasks")
- Sort buttons: sort rows by "Best overall", "Best Task 1 retention", "Least forgetting"
- The Naive row should visually scream red for early tasks

#### Section 5: The Discovery — "Build Your Own Brain"
- Interactive toggle panel: 4 switches for ☑ EWC ☑ Replay ☐ Neurogenesis ☐ CLS
- Radar/spider chart (Chart.js radar type) with 5 axes (one per task)
- As you toggle strategies on/off, the radar polygon morphs to show predicted performance
- Pre-computed data from the hybrid experiments — the toggles map to actual tested combinations
- Below: "Your brain recipe preserves X% of memories" — updates live
- Highlight the winning combination with a subtle glow

#### Section 6: Conclusion — "What We Discovered"
- Auto-generated text from `discovery_text` in results.json
- Key findings as numbered bullet points with bold stats
- Final comparison: "Best Single Strategy" card vs "Best Hybrid" card, side by side
- If hybrid beat all singles: celebratory visual (confetti animation or glowing border)
- Call to action: *"Built by [N] AI agents in [M] minutes. Run it yourself: `./scripts/autopilot.sh --prompt demos/forgetting-cure/PROMPT.md`"*

#### Fallback behavior
- If `results.json` is not found (hasn't been generated yet), show a placeholder page explaining how to run the experiment
- All Chart.js charts degrade to static `<img>` tags loading the matplotlib PNGs if JS is disabled

## File Scope per Agent

- **Agent core**: src/core/__init__.py, src/core/matrix.py, src/core/network.py, src/core/mnist.py, src/core/metrics.py, src/core/config.py
- **Agent naive**: src/strategies/naive/__init__.py, src/strategies/naive/naive.py
- **Agent ewc**: src/strategies/ewc/__init__.py, src/strategies/ewc/ewc.py
- **Agent neurogenesis**: src/strategies/neurogenesis/__init__.py, src/strategies/neurogenesis/neurogenesis.py
- **Agent replay**: src/strategies/replay/__init__.py, src/strategies/replay/replay.py
- **Agent cls**: src/strategies/cls/__init__.py, src/strategies/cls/cls.py
- **Agent hybrid**: src/hybrid/__init__.py, src/hybrid/combiner.py
- **Agent runner**: src/main.py, src/report.py, src/__init__.py, output/results.csv, output/results.json, output/*.png, output/discovery.md
- **Agent webapp**: output/index.html (single file, reads results.json)

## Technical Requirements

- Python 3.11+
- Only stdlib + matplotlib for charts (no numpy except MNIST loading, no PyTorch, no TensorFlow, no scikit-learn)
- Matrix math implemented from scratch in matrix.py
- Each strategy file must be fully self-contained (no cross-strategy imports)
- Webapp is a single HTML file using Chart.js via CDN (no npm, no build step)
- Total codebase under 3500 lines (Python) + ~500 lines (HTML/JS)
- Full experiment should complete in under 30 minutes on a modern CPU

## Dependency Graph

```
Wave 1: core (foundation)
Wave 2: naive + ewc + neurogenesis + replay + cls (5 strategies in parallel)
Wave 3: hybrid (needs all strategies)
Wave 4: runner + webapp (parallel — runner generates results.json, webapp reads it)
```

## Success Criteria

The experiment succeeds if:
1. Naive baseline shows clear catastrophic forgetting (Task 1 accuracy < 30% after Task 5)
2. At least 2 strategies significantly outperform Naive (>60% Task 1 accuracy after Task 5)
3. At least 1 hybrid outperforms all individual strategies
4. The discovery.md contains a non-trivial finding about which brain mechanisms complement each other
5. The webapp opens in a browser and displays all interactive sections with real experiment data
6. The "Build Your Own Brain" toggle produces different results for different combinations
