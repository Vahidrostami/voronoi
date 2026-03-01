"""Hyperparameters for the Forgetting Cure experiment."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    # General training
    learning_rate: float = 0.01
    batch_size: int = 32
    epochs_per_task: int = 50

    # Network architecture (input 784 -> hidden -> output heads)
    input_size: int = 784
    hidden_sizes: List[int] = field(default_factory=lambda: [256, 128])
    neurons_per_head: int = 2   # 2 output neurons per task
    num_tasks: int = 5          # 5 digit-pair tasks
    output_size: int = 10       # total output neurons (2 * 5)

    # EWC (Elastic Weight Consolidation)
    ewc_lambda: float = 1000.0

    # Neurogenesis (Progressive Growing)
    neurogenesis_new_neurons: int = 32

    # Sleep Replay
    replay_samples: int = 100
    replay_noise_std: float = 0.1
    replay_sleep_epochs: int = 10

    # CLS (Complementary Learning Systems — dual memory)
    cls_fast_lr: float = 0.05
    cls_slow_lr: float = 0.001
    cls_fast_sizes: List[int] = field(default_factory=lambda: [64, 32])
    cls_slow_sizes: List[int] = field(default_factory=lambda: [256, 128])

    # MNIST task pairs: each pair is (digit_a, digit_b)
    task_pairs: List[tuple] = field(
        default_factory=lambda: [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9)]
    )
