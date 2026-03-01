"""Neurogenesis (Progressive Growing) strategy for continual learning.

Grows the network by adding new neurons for each task while freezing
existing neuron weights to prevent catastrophic forgetting.
"""

from __future__ import annotations

import random
import sys
import os
from typing import Any, Dict, List, Set, Tuple

# Allow imports from the forgetting-cure package root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from src.core.config import Config
from src.core.network import Network, Strategy
from src.core import matrix as M


class NeurogenesisStrategy(Strategy):
    """Progressive Growing: adds new neurons per task, freezes old ones.

    For each new task (task_id > 0):
    1. Record current weight shapes as the frozen boundary
    2. Grow hidden layers by ``config.neurogenesis_new_neurons`` neurons each
    3. Freeze old→old connections; only train new connections + new task head
    4. on_task_complete() marks newly trained neurons as 'mature' (frozen)
    """

    def __init__(self, config: Config):
        self.config = config
        self.network = Network(config)
        self.tasks_trained: int = 0
        # Pre-growth weight shapes: [(rows, cols)] per weight matrix
        self._frozen_shapes: List[Tuple[int, int]] = []
        # Completed task indices — their output heads are frozen
        self._frozen_heads: Set[int] = set()

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
        if task_idx > 0:
            # Snapshot current shapes as frozen boundary
            self._freeze_current_params()
            # Grow each hidden layer
            num_hidden = self.network.num_layers - 1
            for l in range(num_hidden):
                self.network.grow_layer(l, config.neurogenesis_new_neurons)

        for _ in range(config.epochs_per_task):
            if self._frozen_shapes:
                self._train_epoch_frozen(
                    train_images, train_labels, task_idx, config,
                )
            else:
                self.network.train_epoch(
                    train_images, train_labels, task_idx,
                    config.learning_rate, config.batch_size,
                )

    def evaluate(
        self,
        task_idx: int,
        test_images: List[List[float]],
        test_labels: List[int],
    ) -> float:
        preds = self.network.predict(test_images, task_idx)
        correct = sum(1 for p, y in zip(preds, test_labels) if p == y)
        return correct / max(len(test_labels), 1)

    def on_task_complete(self, task_idx: int) -> None:
        """Freeze newly trained neurons — they become 'mature'."""
        self._frozen_heads.add(task_idx)
        self.tasks_trained += 1

    def get_all_accuracies(
        self,
        tasks: Dict[int, Any],
    ) -> Dict[int, float]:
        results: Dict[int, float] = {}
        for tid, data in tasks.items():
            _, _, test_imgs, test_lbls = data
            results[tid] = self.evaluate(tid, test_imgs, test_lbls)
        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _freeze_current_params(self) -> None:
        """Record current weight dimensions as the frozen boundary."""
        self._frozen_shapes = []
        for l in range(self.network.num_layers):
            w = self.network.weights[l]
            self._frozen_shapes.append((len(w), len(w[0]) if w else 0))

    def _train_epoch_frozen(
        self,
        images: List[List[float]],
        labels: List[int],
        task_idx: int,
        config: Config,
    ) -> None:
        """Mini-batch SGD with per-batch freeze/restore of old weights."""
        n = len(images)
        indices = list(range(n))
        random.shuffle(indices)

        head_start = task_idx * config.neurons_per_head
        head_end = head_start + config.neurons_per_head

        for start in range(0, n, config.batch_size):
            end = min(start + config.batch_size, n)
            batch_idx = indices[start:end]
            X = [images[i] for i in batch_idx]
            Y = [labels[i] for i in batch_idx]
            Y_oh = M.to_one_hot(Y, config.neurons_per_head)

            # Snapshot all weights before backprop
            saved_w = [M.deep_copy(w) for w in self.network.weights]
            saved_b = [M.deep_copy(b) for b in self.network.biases]

            # Standard backprop (modifies all weights)
            self.network.backprop(X, Y_oh, task_idx, config.learning_rate)

            # Restore frozen positions
            self._restore_frozen(saved_w, saved_b, head_start, head_end)

    def _restore_frozen(
        self,
        saved_w: List[M.Matrix],
        saved_b: List[M.Matrix],
        head_start: int,
        head_end: int,
    ) -> None:
        """Overwrite updated weights with saved values for frozen positions.

        Hidden layers: old→old region (i < frozen_rows, j < frozen_cols) is frozen.
        Output layer: all columns outside current task head are frozen.
        """
        out_layer = self.network.num_layers - 1

        for l in range(self.network.num_layers):
            w = self.network.weights[l]
            sw = saved_w[l]
            b = self.network.biases[l]
            sb = saved_b[l]

            if l == out_layer:
                # Output layer: freeze all columns EXCEPT current task head
                for i in range(len(w)):
                    for j in range(len(w[0])):
                        if j < head_start or j >= head_end:
                            w[i][j] = sw[i][j]
                for j in range(len(b[0])):
                    if j < head_start or j >= head_end:
                        b[0][j] = sb[0][j]
            else:
                # Hidden layers: freeze old→old region
                fr, fc = self._frozen_shapes[l]
                rows = min(fr, len(w))
                cols = min(fc, len(w[0]))
                for i in range(rows):
                    for j in range(cols):
                        w[i][j] = sw[i][j]
                for j in range(min(fc, len(b[0]))):
                    b[0][j] = sb[0][j]
