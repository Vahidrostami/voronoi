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

## File Scope per Agent

- **Agent core**: src/core/__init__.py, src/core/matrix.py, src/core/network.py, src/core/mnist.py, src/core/metrics.py, src/core/config.py
- **Agent naive**: src/strategies/naive/__init__.py, src/strategies/naive/naive.py
- **Agent ewc**: src/strategies/ewc/__init__.py, src/strategies/ewc/ewc.py
- **Agent neurogenesis**: src/strategies/neurogenesis/__init__.py, src/strategies/neurogenesis/neurogenesis.py
- **Agent replay**: src/strategies/replay/__init__.py, src/strategies/replay/replay.py
- **Agent cls**: src/strategies/cls/__init__.py, src/strategies/cls/cls.py
- **Agent hybrid**: src/hybrid/__init__.py, src/hybrid/combiner.py
- **Agent runner**: src/main.py, src/report.py, src/__init__.py, output/

## Technical Requirements

- Python 3.11+
- Only stdlib + matplotlib for charts (no numpy except MNIST loading, no PyTorch, no TensorFlow, no scikit-learn)
- Matrix math implemented from scratch in matrix.py
- Each strategy file must be fully self-contained (no cross-strategy imports)
- Total codebase under 3000 lines
- Full experiment should complete in under 30 minutes on a modern CPU

## Dependency Graph

```
Wave 1: core (foundation)
Wave 2: naive + ewc + neurogenesis + replay + cls (5 strategies in parallel)
Wave 3: hybrid (needs all strategies)
Wave 4: runner (needs everything)
```

## Success Criteria

The experiment succeeds if:
1. Naive baseline shows clear catastrophic forgetting (Task 1 accuracy < 30% after Task 5)
2. At least 2 strategies significantly outperform Naive (>60% Task 1 accuracy after Task 5)
3. At least 1 hybrid outperforms all individual strategies
4. The discovery.md contains a non-trivial finding about which brain mechanisms complement each other
