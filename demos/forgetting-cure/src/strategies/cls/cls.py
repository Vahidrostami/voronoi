"""Complementary Learning Systems (CLS) — dual-memory strategy.

Inspired by the hippocampal-neocortical theory: a *fast learner*
(hippocampus) quickly acquires new tasks, then teaches a *slow learner*
(neocortex) via interleaved pseudo-rehearsal so the slow network
retains all tasks without catastrophic forgetting.
"""

from __future__ import annotations

import random
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, "demos/forgetting-cure")

from src.core.config import Config
from src.core.network import Network, Strategy
from src.core import matrix as M


class CLSStrategy(Strategy):
    """Dual-memory continual learning with knowledge distillation."""

    def __init__(self, config: Config):
        self.config = config

        # Fast learner (hippocampus): small, high learning-rate
        fast_cfg = Config(
            input_size=config.input_size,
            hidden_sizes=list(config.cls_fast_sizes),
            neurons_per_head=config.neurons_per_head,
            num_tasks=config.num_tasks,
            output_size=config.output_size,
            learning_rate=config.cls_fast_lr,
        )
        self.fast_net = Network(fast_cfg)

        # Slow learner (neocortex): large, low learning-rate
        slow_cfg = Config(
            input_size=config.input_size,
            hidden_sizes=list(config.cls_slow_sizes),
            neurons_per_head=config.neurons_per_head,
            num_tasks=config.num_tasks,
            output_size=config.output_size,
            learning_rate=config.cls_slow_lr,
        )
        self.slow_net = Network(slow_cfg)

        # Store training data references for pseudo-example generation
        self._task_data: Dict[int, Tuple[List[List[float]], List[int]]] = {}

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
        # Remember this task's training data
        self._task_data[task_idx] = (train_images, train_labels)

        # Step 1: Train fast learner on new task data
        for _epoch in range(config.epochs_per_task):
            self.fast_net.train_epoch(
                train_images,
                train_labels,
                task_idx,
                config.cls_fast_lr,
                config.batch_size,
            )

        # Step 2: Generate pseudo-examples from fast learner
        pseudo_images: List[List[float]] = []
        pseudo_soft_targets: List[List[float]] = []
        pseudo_task_indices: List[int] = []

        for prev_task in range(task_idx + 1):
            stored_images, stored_labels = self._task_data[prev_task]

            if prev_task == task_idx:
                # Current task: use actual training examples with soft targets
                sample_images = stored_images
            else:
                # Previous tasks: sample up to 200 examples
                n_samples = min(200, len(stored_images))
                indices = random.sample(range(len(stored_images)), n_samples)
                sample_images = [stored_images[i] for i in indices]

            # Get soft targets from fast learner (knowledge distillation)
            probs, _ = self.fast_net.forward(sample_images, task_idx=prev_task)
            for i, img in enumerate(sample_images):
                pseudo_images.append(img)
                pseudo_soft_targets.append(probs[i])
                pseudo_task_indices.append(prev_task)

        # Step 3: Train slow learner on interleaved mix of all pseudo-examples
        n_pseudo = len(pseudo_images)
        for _epoch in range(config.epochs_per_task):
            order = list(range(n_pseudo))
            random.shuffle(order)
            for start in range(0, n_pseudo, config.batch_size):
                end = min(start + config.batch_size, n_pseudo)
                batch_idx = order[start:end]

                # Group by task for backprop (each task uses its own head)
                task_batches: Dict[int, Tuple[List[List[float]], List[List[float]]]] = {}
                for bi in batch_idx:
                    t = pseudo_task_indices[bi]
                    if t not in task_batches:
                        task_batches[t] = ([], [])
                    task_batches[t][0].append(pseudo_images[bi])
                    task_batches[t][1].append(pseudo_soft_targets[bi])

                for t, (imgs, soft_targets) in task_batches.items():
                    # Use soft targets directly as Y_onehot for backprop
                    self.slow_net.backprop(
                        imgs, soft_targets, t, config.cls_slow_lr,
                    )

    def evaluate(
        self,
        task_idx: int,
        test_images: List[List[float]],
        test_labels: List[int],
    ) -> float:
        """Evaluate the slow learner (neocortex) on a task."""
        preds = self.slow_net.predict(test_images, task_idx)
        correct = sum(1 for p, y in zip(preds, test_labels) if p == y)
        return correct / max(len(test_labels), 1)

    def on_task_complete(self, task_idx: int) -> None:
        """No special consolidation needed — pseudo-teaching handles it."""
        pass

    def get_all_accuracies(
        self,
        tasks: Dict[int, Any],
    ) -> Dict[int, float]:
        """Evaluate the slow learner on every task seen so far."""
        results: Dict[int, float] = {}
        for t_idx, (_, _, test_imgs, test_lbls) in tasks.items():
            results[t_idx] = self.evaluate(t_idx, test_imgs, test_lbls)
        return results
