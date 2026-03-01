"""Elastic Weight Consolidation (EWC) strategy.

After each task, compute the Fisher Information Matrix for all weights.
During subsequent training, add a penalty:

    Loss = Task_Loss + λ * Σ F_i * (θ_i - θ*_i)²

This discourages changes to weights that were important for previous tasks.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

from src.core.network import Network, Strategy
from src.core.config import Config
from src.core import matrix as M

Matrix = M.Matrix


class EWCStrategy(Strategy):
    """Elastic Weight Consolidation continual-learning strategy."""

    def __init__(self, network: Network, config: Config):
        self.network = network
        self.config = config
        # Snapshots: (fisher_weights, fisher_biases, optimal_weights, optimal_biases)
        self.snapshots: List[
            Tuple[List[Matrix], List[Matrix], List[Matrix], List[Matrix]]
        ] = []
        # Training data saved for Fisher computation in on_task_complete
        self._train_images: List[List[float]] = []
        self._train_labels: List[int] = []
        self._last_task_idx: int = 0

    # ------------------------------------------------------------------
    # Strategy interface
    # ------------------------------------------------------------------

    def train_task(
        self,
        task_idx: int,
        train_images: List[List[float]],
        train_labels: List[int],
        config: Config,
    ) -> None:
        """Train on one task with EWC penalty from previous tasks."""
        self._train_images = train_images
        self._train_labels = train_labels
        self._last_task_idx = task_idx

        lr = config.learning_rate
        batch_size = config.batch_size
        epochs = config.epochs_per_task
        ewc_lambda = config.ewc_lambda

        n = len(train_images)
        for _epoch in range(epochs):
            indices = list(range(n))
            random.shuffle(indices)
            for start in range(0, n, batch_size):
                end = min(start + batch_size, n)
                batch_idx = indices[start:end]
                X = [train_images[i] for i in batch_idx]
                Y = [train_labels[i] for i in batch_idx]
                Y_oh = M.to_one_hot(Y, config.neurons_per_head)

                # Task gradient step
                self.network.backprop(X, Y_oh, task_idx, lr)

                # EWC penalty gradient step
                if self.snapshots:
                    self._apply_ewc_penalty(lr, ewc_lambda)

    def on_task_complete(self, task_idx: int) -> None:
        """Compute Fisher Information Matrix and store (F, θ*) snapshot."""
        n_samples = min(200, len(self._train_images))
        if n_samples == 0:
            return
        indices = random.sample(range(len(self._train_images)), n_samples)

        # Accumulators (same shapes as weights / biases)
        fisher_w = [M.zeros(*M.shape(w)) for w in self.network.weights]
        fisher_b = [M.zeros(*M.shape(b)) for b in self.network.biases]

        for idx in indices:
            x = [self._train_images[idx]]  # single-sample batch
            y = [self._train_labels[idx]]
            y_oh = M.to_one_hot(y, self.config.neurons_per_head)

            # Save params
            saved_w = [M.deep_copy(w) for w in self.network.weights]
            saved_b = [M.deep_copy(b) for b in self.network.biases]

            # Backprop with lr=1.0 → new_θ = old_θ - grad, so grad = old - new
            self.network.backprop(x, y_oh, task_idx, 1.0)

            for l in range(self.network.num_layers):
                gw = M.subtract(saved_w[l], self.network.weights[l])
                gb = M.subtract(saved_b[l], self.network.biases[l])
                fisher_w[l] = M.add(fisher_w[l], M.multiply(gw, gw))
                fisher_b[l] = M.add(fisher_b[l], M.multiply(gb, gb))

            # Restore params
            self.network.weights = saved_w
            self.network.biases = saved_b

        # Average over samples
        inv_n = 1.0 / n_samples
        fisher_w = [M.scalar_mul(f, inv_n) for f in fisher_w]
        fisher_b = [M.scalar_mul(f, inv_n) for f in fisher_b]

        # Store snapshot of Fisher and current (optimal) parameters
        opt_w = [M.deep_copy(w) for w in self.network.weights]
        opt_b = [M.deep_copy(b) for b in self.network.biases]
        self.snapshots.append((fisher_w, fisher_b, opt_w, opt_b))

    def evaluate(
        self,
        task_idx: int,
        test_images: List[List[float]],
        test_labels: List[int],
    ) -> float:
        """Return accuracy on a task's test set via standard forward pass."""
        if not test_labels:
            return 0.0
        preds = self.network.predict(test_images, task_idx)
        correct = sum(1 for p, t in zip(preds, test_labels) if p == t)
        return correct / len(test_labels)

    def get_all_accuracies(
        self,
        tasks: Dict[int, Any],
    ) -> Dict[int, float]:
        """Evaluate on ALL tasks, returning {task_idx: accuracy}."""
        results: Dict[int, float] = {}
        for task_idx, task_data in tasks.items():
            _, _, test_images, test_labels = task_data
            results[task_idx] = self.evaluate(task_idx, test_images, test_labels)
        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_ewc_penalty(self, lr: float, ewc_lambda: float) -> None:
        """Apply EWC regularization: θ -= lr * 2λ * Σ F_i * (θ_i - θ*_i)."""
        for fisher_w, fisher_b, opt_w, opt_b in self.snapshots:
            for l in range(self.network.num_layers):
                # Weights: penalty_grad = 2 * λ * F * (θ - θ*)
                diff_w = M.subtract(self.network.weights[l], opt_w[l])
                pen_w = M.scalar_mul(M.multiply(fisher_w[l], diff_w), 2.0 * ewc_lambda * lr)
                self.network.weights[l] = M.subtract(self.network.weights[l], pen_w)

                # Biases
                diff_b = M.subtract(self.network.biases[l], opt_b[l])
                pen_b = M.scalar_mul(M.multiply(fisher_b[l], diff_b), 2.0 * ewc_lambda * lr)
                self.network.biases[l] = M.subtract(self.network.biases[l], pen_b)
