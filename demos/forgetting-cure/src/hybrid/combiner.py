"""Hybrid Discovery combiner for the Forgetting Cure experiment.

Combines multiple continual-learning strategies to find optimal
'brain recipes' that resist catastrophic forgetting better than
any single strategy alone.
"""

from __future__ import annotations

import random
import sys
from typing import Any, Dict, List, Tuple, Type

from src.core.network import Network, Strategy
from src.core.config import Config
from src.core import matrix as M

from src.strategies.ewc.ewc import EWCStrategy
from src.strategies.neurogenesis.neurogenesis import NeurogenesisStrategy
from src.strategies.replay.replay import ReplayStrategy, distort_sample
from src.strategies.cls.cls import CLSStrategy


# ======================================================================
# Helpers
# ======================================================================

def _get_eval_network(strategy: Strategy) -> Network:
    """Return the network used for evaluation by a given strategy."""
    if hasattr(strategy, "slow_net"):
        return strategy.slow_net
    return strategy.network


def _create_strategy(strategy_cls: Type[Strategy], config: Config) -> Strategy:
    """Instantiate a strategy, providing a Network if its constructor needs one."""
    try:
        return strategy_cls(config)
    except TypeError:
        network = Network(config)
        return strategy_cls(network, config)


# ======================================================================
# 1. EWC + Replay
# ======================================================================

class EWCReplayStrategy(Strategy):
    """Combines EWC's Fisher penalty with Sleep Replay buffer.

    During training: EWC penalty prevents important weight changes while
    replay buffer reinforces previous tasks with distorted samples.
    """

    def __init__(self, config: Config):
        self.config = config
        self.network = Network(config)
        self._ewc = EWCStrategy(self.network, config)
        self._replay = ReplayStrategy(self.network, config)

    def train_task(
        self,
        task_idx: int,
        train_images: List[List[float]],
        train_labels: List[int],
        config: Config,
    ) -> None:
        # Sleep phase before this task (replay previous memories)
        if len(self._replay.replay_buffer) > 0:
            self._replay._sleep_phase(config)

        # Store data for Fisher computation later
        self._ewc._train_images = train_images
        self._ewc._train_labels = train_labels
        self._ewc._last_task_idx = task_idx

        lr = config.learning_rate
        n = len(train_images)
        for _epoch in range(config.epochs_per_task):
            indices = list(range(n))
            random.shuffle(indices)
            for start in range(0, n, config.batch_size):
                end = min(start + config.batch_size, n)
                batch_idx = indices[start:end]
                X = [train_images[i] for i in batch_idx]
                Y = [train_labels[i] for i in batch_idx]
                Y_oh = M.to_one_hot(Y, config.neurons_per_head)

                # Standard gradient step
                self.network.backprop(X, Y_oh, task_idx, lr)

                # EWC penalty step (synaptic consolidation)
                if self._ewc.snapshots:
                    self._ewc._apply_ewc_penalty(lr, config.ewc_lambda)

            # Replay distorted samples after each epoch
            if len(self._replay.replay_buffer) > 0:
                self._replay._replay_step(config)

    def on_task_complete(self, task_idx: int) -> None:
        # Compute Fisher Information Matrix (EWC)
        self._ewc.on_task_complete(task_idx)
        # Store samples in replay buffer
        self._replay.add_to_buffer(
            self._ewc._train_images,
            self._ewc._train_labels,
            task_idx,
        )

    def evaluate(
        self,
        task_idx: int,
        test_images: List[List[float]],
        test_labels: List[int],
    ) -> float:
        if not test_labels:
            return 0.0
        preds = self.network.predict(test_images, task_idx)
        correct = sum(1 for p, t in zip(preds, test_labels) if p == t)
        return correct / len(test_labels)

    def get_all_accuracies(
        self,
        tasks: Dict[int, Any],
    ) -> Dict[int, float]:
        results: Dict[int, float] = {}
        for task_idx, task_data in tasks.items():
            _, _, test_images, test_labels = task_data
            results[task_idx] = self.evaluate(task_idx, test_images, test_labels)
        return results


# ======================================================================
# 2. Neurogenesis + CLS
# ======================================================================

class NeurogenesisCLSStrategy(Strategy):
    """CLS dual-memory where the slow learner grows new neurons per task.

    Fast learner acquires new tasks quickly, teaches the slow learner via
    knowledge distillation, and the slow learner also grows its hidden
    layers (neurogenesis) for each new task to provide dedicated capacity.
    """

    def __init__(self, config: Config):
        self.config = config

        # Fast learner (hippocampus)
        fast_cfg = Config(
            input_size=config.input_size,
            hidden_sizes=list(config.cls_fast_sizes),
            neurons_per_head=config.neurons_per_head,
            num_tasks=config.num_tasks,
            output_size=config.output_size,
            learning_rate=config.cls_fast_lr,
        )
        self.fast_net = Network(fast_cfg)

        # Slow learner (neocortex) — also grows via neurogenesis
        slow_cfg = Config(
            input_size=config.input_size,
            hidden_sizes=list(config.cls_slow_sizes),
            neurons_per_head=config.neurons_per_head,
            num_tasks=config.num_tasks,
            output_size=config.output_size,
            learning_rate=config.cls_slow_lr,
        )
        self.slow_net = Network(slow_cfg)

        self._task_data: Dict[int, Tuple[List[List[float]], List[int]]] = {}
        self.tasks_trained: int = 0

    def train_task(
        self,
        task_idx: int,
        train_images: List[List[float]],
        train_labels: List[int],
        config: Config,
    ) -> None:
        self._task_data[task_idx] = (train_images, train_labels)

        # Step 1: Train fast learner on new task
        for _epoch in range(config.epochs_per_task):
            self.fast_net.train_epoch(
                train_images, train_labels, task_idx,
                config.cls_fast_lr, config.batch_size,
            )

        # Step 2: Grow slow learner's hidden layers (neurogenesis)
        if task_idx > 0:
            num_hidden = self.slow_net.num_layers - 1
            for l in range(num_hidden):
                self.slow_net.grow_layer(l, config.neurogenesis_new_neurons)

        # Step 3: Generate pseudo-examples from fast learner
        pseudo_images: List[List[float]] = []
        pseudo_soft_targets: List[List[float]] = []
        pseudo_task_indices: List[int] = []

        for prev_task in range(task_idx + 1):
            stored_images, _ = self._task_data[prev_task]
            if prev_task == task_idx:
                sample_images = stored_images
            else:
                n_samples = min(200, len(stored_images))
                indices = random.sample(range(len(stored_images)), n_samples)
                sample_images = [stored_images[i] for i in indices]

            probs, _ = self.fast_net.forward(sample_images, task_idx=prev_task)
            for i, img in enumerate(sample_images):
                pseudo_images.append(img)
                pseudo_soft_targets.append(probs[i])
                pseudo_task_indices.append(prev_task)

        # Step 4: Train slow learner on pseudo-examples
        n_pseudo = len(pseudo_images)
        for _epoch in range(config.epochs_per_task):
            order = list(range(n_pseudo))
            random.shuffle(order)
            for start in range(0, n_pseudo, config.batch_size):
                end = min(start + config.batch_size, n_pseudo)
                batch_idx = order[start:end]

                task_batches: Dict[int, Tuple[List[List[float]], List[List[float]]]] = {}
                for bi in batch_idx:
                    t = pseudo_task_indices[bi]
                    if t not in task_batches:
                        task_batches[t] = ([], [])
                    task_batches[t][0].append(pseudo_images[bi])
                    task_batches[t][1].append(pseudo_soft_targets[bi])

                for t, (imgs, soft_targets) in task_batches.items():
                    self.slow_net.backprop(
                        imgs, soft_targets, t, config.cls_slow_lr,
                    )

    def on_task_complete(self, task_idx: int) -> None:
        self.tasks_trained += 1

    def evaluate(
        self,
        task_idx: int,
        test_images: List[List[float]],
        test_labels: List[int],
    ) -> float:
        preds = self.slow_net.predict(test_images, task_idx)
        correct = sum(1 for p, y in zip(preds, test_labels) if p == y)
        return correct / max(len(test_labels), 1)

    def get_all_accuracies(
        self,
        tasks: Dict[int, Any],
    ) -> Dict[int, float]:
        results: Dict[int, float] = {}
        for t_idx, (_, _, test_imgs, test_lbls) in tasks.items():
            results[t_idx] = self.evaluate(t_idx, test_imgs, test_lbls)
        return results


# ======================================================================
# 3. Full Brain (All 4 combined)
# ======================================================================

class FullBrainStrategy(Strategy):
    """All four anti-forgetting mechanisms combined:

    - CLS dual memory (fast learner teaches slow learner)
    - EWC penalties on the slow learner
    - Neurogenesis (slow learner grows neurons per task)
    - Replay buffer feeds distorted samples during slow training
    """

    def __init__(self, config: Config):
        self.config = config

        # Fast learner (hippocampus)
        fast_cfg = Config(
            input_size=config.input_size,
            hidden_sizes=list(config.cls_fast_sizes),
            neurons_per_head=config.neurons_per_head,
            num_tasks=config.num_tasks,
            output_size=config.output_size,
            learning_rate=config.cls_fast_lr,
        )
        self.fast_net = Network(fast_cfg)

        # Slow learner (neocortex) — uses EWC + neurogenesis
        slow_cfg = Config(
            input_size=config.input_size,
            hidden_sizes=list(config.cls_slow_sizes),
            neurons_per_head=config.neurons_per_head,
            num_tasks=config.num_tasks,
            output_size=config.output_size,
            learning_rate=config.cls_slow_lr,
        )
        self.slow_net = Network(slow_cfg)

        # EWC on the slow learner
        self._ewc = EWCStrategy(self.slow_net, config)

        # Replay buffer: (image, label, task_idx) tuples
        self.replay_buffer: List[Tuple[List[float], int, int]] = []

        self._task_data: Dict[int, Tuple[List[List[float]], List[int]]] = {}
        self.tasks_trained: int = 0

    def train_task(
        self,
        task_idx: int,
        train_images: List[List[float]],
        train_labels: List[int],
        config: Config,
    ) -> None:
        self._task_data[task_idx] = (train_images, train_labels)

        # Step 1: Train fast learner on new task
        for _epoch in range(config.epochs_per_task):
            self.fast_net.train_epoch(
                train_images, train_labels, task_idx,
                config.cls_fast_lr, config.batch_size,
            )

        # Step 2: Grow slow learner (neurogenesis)
        if task_idx > 0:
            num_hidden = self.slow_net.num_layers - 1
            for l in range(num_hidden):
                self.slow_net.grow_layer(l, config.neurogenesis_new_neurons)

        # Step 3: Generate pseudo-examples from fast learner
        pseudo_images: List[List[float]] = []
        pseudo_soft_targets: List[List[float]] = []
        pseudo_task_indices: List[int] = []

        for prev_task in range(task_idx + 1):
            stored_images, _ = self._task_data[prev_task]
            if prev_task == task_idx:
                sample_images = stored_images
            else:
                n_samples = min(200, len(stored_images))
                indices = random.sample(range(len(stored_images)), n_samples)
                sample_images = [stored_images[i] for i in indices]

            probs, _ = self.fast_net.forward(sample_images, task_idx=prev_task)
            for i, img in enumerate(sample_images):
                pseudo_images.append(img)
                pseudo_soft_targets.append(probs[i])
                pseudo_task_indices.append(prev_task)

        # Step 4: Mix in distorted replay samples
        if self.replay_buffer:
            n_replay = min(config.replay_samples, len(self.replay_buffer))
            replay_samples = random.sample(self.replay_buffer, n_replay)
            for img, lbl, tidx in replay_samples:
                distorted = distort_sample(img, config)
                probs, _ = self.fast_net.forward([distorted], task_idx=tidx)
                pseudo_images.append(distorted)
                pseudo_soft_targets.append(probs[0])
                pseudo_task_indices.append(tidx)

        # Step 5: Train slow learner with EWC penalty
        self._ewc._train_images = train_images
        self._ewc._train_labels = train_labels
        self._ewc._last_task_idx = task_idx

        n_pseudo = len(pseudo_images)
        for _epoch in range(config.epochs_per_task):
            order = list(range(n_pseudo))
            random.shuffle(order)
            for start in range(0, n_pseudo, config.batch_size):
                end = min(start + config.batch_size, n_pseudo)
                batch_idx = order[start:end]

                task_batches: Dict[int, Tuple[List[List[float]], List[List[float]]]] = {}
                for bi in batch_idx:
                    t = pseudo_task_indices[bi]
                    if t not in task_batches:
                        task_batches[t] = ([], [])
                    task_batches[t][0].append(pseudo_images[bi])
                    task_batches[t][1].append(pseudo_soft_targets[bi])

                for t, (imgs, soft_targets) in task_batches.items():
                    self.slow_net.backprop(
                        imgs, soft_targets, t, config.cls_slow_lr,
                    )
                    # Apply EWC penalty after each mini-batch
                    if self._ewc.snapshots:
                        self._ewc._apply_ewc_penalty(
                            config.cls_slow_lr, config.ewc_lambda,
                        )

    def on_task_complete(self, task_idx: int) -> None:
        # Compute Fisher Information Matrix (EWC on slow learner)
        self._ewc.on_task_complete(task_idx)
        # Store samples in replay buffer
        if task_idx in self._task_data:
            imgs, lbls = self._task_data[task_idx]
            n = len(imgs)
            max_samples = 500
            indices = list(range(n)) if n <= max_samples else random.sample(range(n), max_samples)
            for i in indices:
                self.replay_buffer.append((list(imgs[i]), lbls[i], task_idx))
        self.tasks_trained += 1

    def evaluate(
        self,
        task_idx: int,
        test_images: List[List[float]],
        test_labels: List[int],
    ) -> float:
        preds = self.slow_net.predict(test_images, task_idx)
        correct = sum(1 for p, y in zip(preds, test_labels) if p == y)
        return correct / max(len(test_labels), 1)

    def get_all_accuracies(
        self,
        tasks: Dict[int, Any],
    ) -> Dict[int, float]:
        results: Dict[int, float] = {}
        for t_idx, (_, _, test_imgs, test_lbls) in tasks.items():
            results[t_idx] = self.evaluate(t_idx, test_imgs, test_lbls)
        return results


# ======================================================================
# 4. Top Two Strategy (Ensemble)
# ======================================================================

class TopTwoStrategy(Strategy):
    """Ensemble wrapper: runs two strategies, averages their predictions.

    Takes two strategy classes as constructor arguments. At evaluation
    time, averages the output probabilities from both and picks argmax.
    """

    def __init__(
        self,
        strategy_cls_1: Type[Strategy],
        strategy_cls_2: Type[Strategy],
        config: Config,
    ):
        self.config = config
        self.strategy_1 = _create_strategy(strategy_cls_1, config)
        self.strategy_2 = _create_strategy(strategy_cls_2, config)
        self._last_train_data: Dict[int, Tuple[List[List[float]], List[int]]] = {}

    def train_task(
        self,
        task_idx: int,
        train_images: List[List[float]],
        train_labels: List[int],
        config: Config,
    ) -> None:
        self._last_train_data[task_idx] = (train_images, train_labels)
        self.strategy_1.train_task(task_idx, train_images, train_labels, config)
        self.strategy_2.train_task(task_idx, train_images, train_labels, config)

    def on_task_complete(self, task_idx: int) -> None:
        # Populate replay buffers for ReplayStrategy instances
        if task_idx in self._last_train_data:
            imgs, lbls = self._last_train_data[task_idx]
            for s in (self.strategy_1, self.strategy_2):
                if isinstance(s, ReplayStrategy):
                    s.add_to_buffer(imgs, lbls, task_idx)

        self.strategy_1.on_task_complete(task_idx)
        self.strategy_2.on_task_complete(task_idx)

    def evaluate(
        self,
        task_idx: int,
        test_images: List[List[float]],
        test_labels: List[int],
    ) -> float:
        if not test_labels:
            return 0.0
        net1 = _get_eval_network(self.strategy_1)
        net2 = _get_eval_network(self.strategy_2)

        probs1, _ = net1.forward(test_images, task_idx=task_idx)
        probs2, _ = net2.forward(test_images, task_idx=task_idx)

        # Average probabilities and argmax
        correct = 0
        for i in range(len(test_labels)):
            avg_probs = [
                (probs1[i][j] + probs2[i][j]) / 2.0
                for j in range(len(probs1[i]))
            ]
            pred = max(range(len(avg_probs)), key=lambda j: avg_probs[j])
            if pred == test_labels[i]:
                correct += 1
        return correct / len(test_labels)

    def get_all_accuracies(
        self,
        tasks: Dict[int, Any],
    ) -> Dict[int, float]:
        results: Dict[int, float] = {}
        for task_idx, task_data in tasks.items():
            _, _, test_images, test_labels = task_data
            results[task_idx] = self.evaluate(task_idx, test_images, test_labels)
        return results


# ======================================================================
# HybridCombiner: orchestrates all hybrid experiments
# ======================================================================

class HybridCombiner:
    """Orchestrates running and comparing all hybrid strategy combinations."""

    def __init__(self) -> None:
        self.results: Dict[str, Dict[int, float]] = {}

    def run_all_hybrids(
        self,
        config: Config,
        task_data: Dict[int, Tuple[List[List[float]], List[int], List[List[float]], List[int]]],
    ) -> Dict[str, Dict[int, float]]:
        """Run all hybrid combinations on the task sequence.

        Args:
            config: experiment configuration
            task_data: {task_idx: (train_imgs, train_labels, test_imgs, test_labels)}

        Returns:
            {strategy_name: {task_idx: final_accuracy}}
        """
        strategies: Dict[str, Strategy] = {
            "EWC+Replay": EWCReplayStrategy(config),
            "Neurogenesis+CLS": NeurogenesisCLSStrategy(config),
            "FullBrain": FullBrainStrategy(config),
        }

        task_indices = sorted(task_data.keys())

        for name, strategy in strategies.items():
            for task_idx in task_indices:
                train_imgs, train_lbls, test_imgs, test_lbls = task_data[task_idx]
                strategy.train_task(task_idx, train_imgs, train_lbls, config)
                strategy.on_task_complete(task_idx)

            # Final evaluation on all tasks
            self.results[name] = strategy.get_all_accuracies(task_data)

        return self.results

    def find_best_hybrid(self) -> Tuple[str, float]:
        """Compare all hybrids and return (name, avg_accuracy) of the best.

        Must call run_all_hybrids() first.
        """
        if not self.results:
            raise RuntimeError("No results yet — call run_all_hybrids() first")

        best_name = ""
        best_avg = -1.0
        for name, accs in self.results.items():
            if not accs:
                continue
            avg = sum(accs.values()) / len(accs)
            if avg > best_avg:
                best_avg = avg
                best_name = name

        return best_name, best_avg
