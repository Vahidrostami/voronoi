"""Sleep Replay with Distortion strategy for continual learning.

Mimics the brain's sleep-replay mechanism: replays distorted versions of
previously seen samples between and during training epochs to consolidate
memory and resist catastrophic forgetting.
"""

from __future__ import annotations

import math
import random
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, "demos/forgetting-cure")

from src.core.network import Network, Strategy
from src.core.config import Config
from src.core import matrix as M


# ======================================================================
# Distortion helpers (pure Python, no numpy)
# ======================================================================

def gaussian_noise(image: List[float], std: float) -> List[float]:
    """Add Gaussian noise to each pixel, clamping result to [0, 1]."""
    noisy = []
    for px in image:
        # Box-Muller transform for Gaussian samples
        u1 = max(random.random(), 1e-10)
        u2 = random.random()
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        val = px + z * std
        noisy.append(max(0.0, min(1.0, val)))
    return noisy


def shift_image(image: List[float], dx: int, dy: int, width: int = 28, height: int = 28) -> List[float]:
    """Shift a flat image by (dx, dy) pixels, zero-filling empty space."""
    shifted = [0.0] * (width * height)
    for y in range(height):
        for x in range(width):
            src_x = x - dx
            src_y = y - dy
            if 0 <= src_x < width and 0 <= src_y < height:
                shifted[y * width + x] = image[src_y * width + src_x]
    return shifted


def mask_patch(image: List[float], size: int, width: int = 28, height: int = 28) -> List[float]:
    """Zero out a random square patch of given size."""
    masked = list(image)
    x0 = random.randint(0, max(0, width - size))
    y0 = random.randint(0, max(0, height - size))
    for y in range(y0, min(y0 + size, height)):
        for x in range(x0, min(x0 + size, width)):
            masked[y * width + x] = 0.0
    return masked


def distort_sample(image: List[float], config: Config) -> List[float]:
    """Apply sleep-like distortions to a single image.

    1. Gaussian noise (always)
    2. Random pixel shift of 1-2px (always)
    3. Random patch masking (30% chance, partial replay)
    """
    result = gaussian_noise(image, config.replay_noise_std)

    dx = random.choice([-2, -1, 1, 2])
    dy = random.choice([-2, -1, 1, 2])
    result = shift_image(result, dx, dy)

    # Occasional masking for partial replay
    if random.random() < 0.3:
        patch_size = random.randint(3, 6)
        result = mask_patch(result, patch_size)

    return result


# ======================================================================
# Replay Strategy
# ======================================================================

class ReplayStrategy(Strategy):
    """Sleep Replay with Distortion.

    Maintains a replay buffer of samples from all previously seen tasks.
    During training:
      - After each epoch, replays distorted samples from the buffer
      - Between tasks, runs a 'sleep phase' of pure-replay epochs
    """

    def __init__(self, network: Network, config: Config):
        self.network = network
        self.config = config
        # Replay buffer: list of (image, label, task_idx) tuples
        self.replay_buffer: List[Tuple[List[float], int, int]] = []

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
        """Train on a task with interleaved distorted replay."""

        # Sleep phase BEFORE this task (if buffer has data from previous tasks)
        if len(self.replay_buffer) > 0:
            self._sleep_phase(config)

        # Regular training with replay after each epoch
        for epoch in range(config.epochs_per_task):
            # 1. Train on current task normally
            self.network.train_epoch(
                train_images,
                train_labels,
                task_idx,
                config.learning_rate,
                config.batch_size,
            )

            # 2. Replay distorted samples from buffer (if any)
            if len(self.replay_buffer) > 0:
                self._replay_step(config)

    def evaluate(
        self,
        task_idx: int,
        test_images: List[List[float]],
        test_labels: List[int],
    ) -> float:
        """Return accuracy on a task's test set."""
        if len(test_images) == 0:
            return 0.0
        predictions = self.network.predict(test_images, task_idx)
        correct = sum(1 for p, t in zip(predictions, test_labels) if p == t)
        return correct / len(test_labels)

    def on_task_complete(self, task_idx: int) -> None:
        """Store ~500 samples from the completed task into the replay buffer.

        Called by the experiment runner after train_task finishes.
        We don't have direct access to data here, so this is a no-op;
        use add_to_buffer() explicitly from the experiment runner,
        OR use the convenience wrapper train_and_store().
        """
        pass

    def add_to_buffer(
        self,
        images: List[List[float]],
        labels: List[int],
        task_idx: int,
        max_samples: int = 500,
    ) -> None:
        """Add samples from a task to the replay buffer."""
        n = len(images)
        if n <= max_samples:
            indices = list(range(n))
        else:
            indices = random.sample(range(n), max_samples)
        for i in indices:
            self.replay_buffer.append((list(images[i]), labels[i], task_idx))

    def get_all_accuracies(
        self,
        tasks: Dict[int, Any],
    ) -> Dict[int, float]:
        """Evaluate on ALL tasks seen so far."""
        results: Dict[int, float] = {}
        for tidx, task_data in tasks.items():
            # task_data expected: (train_imgs, train_lbls, test_imgs, test_lbls)
            test_imgs = task_data[2]
            test_lbls = task_data[3]
            results[tidx] = self.evaluate(tidx, test_imgs, test_lbls)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _replay_step(self, config: Config) -> None:
        """Replay a batch of distorted samples from the buffer."""
        n_replay = min(config.replay_samples, len(self.replay_buffer))
        samples = random.sample(self.replay_buffer, n_replay)

        # Group samples by task for correct head routing
        by_task: Dict[int, Tuple[List[List[float]], List[int]]] = {}
        for img, lbl, tidx in samples:
            distorted = distort_sample(img, config)
            if tidx not in by_task:
                by_task[tidx] = ([], [])
            by_task[tidx][0].append(distorted)
            by_task[tidx][1].append(lbl)

        # Train a mini-batch per task head
        for tidx, (imgs, lbls) in by_task.items():
            Y_oh = M.to_one_hot(lbls, self.network.config.neurons_per_head)
            self.network.backprop(
                imgs, Y_oh, tidx, config.learning_rate
            )

    def _sleep_phase(self, config: Config) -> None:
        """Run pure-replay 'sleep' epochs between tasks."""
        for _ in range(config.replay_sleep_epochs):
            self._replay_step(config)
