"""Naive Sequential Baseline strategy.

Trains the shared network on each task sequentially with plain SGD.
No anti-forgetting mechanism — demonstrates catastrophic forgetting.
Task 1 accuracy should degrade dramatically after training on later tasks.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List

# Ensure the demo root is importable
sys.path.insert(0, "demos/forgetting-cure")

from src.core.config import Config
from src.core.metrics import MetricsTracker
from src.core.network import Network, Strategy


class NaiveStrategy(Strategy):
    """Train each task sequentially with vanilla SGD — no protection."""

    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.network = Network(self.config)
        self.metrics = MetricsTracker(self.config.num_tasks)
        self._tasks_seen: List[int] = []

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
        """Train on *task_idx* with plain mini-batch SGD."""
        if task_idx not in self._tasks_seen:
            self._tasks_seen.append(task_idx)

        for epoch in range(config.epochs_per_task):
            loss = self.network.train_epoch(
                train_images,
                train_labels,
                task_idx,
                config.learning_rate,
                config.batch_size,
            )
            if (epoch + 1) % 10 == 0 or epoch == 0:
                print(f"  [Naive] Task {task_idx} epoch {epoch + 1}/{config.epochs_per_task}  loss={loss:.4f}")

    def evaluate(
        self,
        task_idx: int,
        test_images: List[List[float]],
        test_labels: List[int],
    ) -> float:
        """Run forward pass on task head, return accuracy."""
        preds = self.network.predict(test_images, task_idx)
        return self.metrics.accuracy(preds, test_labels)

    def on_task_complete(self, task_idx: int) -> None:
        """No-op — naive baseline applies no consolidation or protection."""
        pass

    def get_all_accuracies(
        self,
        tasks: Dict[int, Any],
    ) -> Dict[int, float]:
        """Evaluate on every task seen so far.

        *tasks* maps task_idx → (train_imgs, train_lbls, test_imgs, test_lbls).
        """
        accuracies: Dict[int, float] = {}
        for tidx in self._tasks_seen:
            if tidx in tasks:
                _, _, test_imgs, test_lbls = tasks[tidx]
                accuracies[tidx] = self.evaluate(tidx, test_imgs, test_lbls)
        return accuracies
