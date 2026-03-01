"""Forgetting Cure experiment runner.

Runs all continual-learning strategies (naive, EWC, neurogenesis, replay, CLS)
plus hybrid combinations on 5 sequential MNIST digit-pair tasks, then generates
a comprehensive report of results.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Tuple

# Ensure the forgetting-cure root is on the path
_DEMO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DEMO_ROOT)

from src.core.config import Config
from src.core.metrics import MetricsTracker
from src.core.mnist import make_tasks
from src.core.network import Network, Strategy

from src.strategies.naive.naive import NaiveStrategy
from src.strategies.ewc.ewc import EWCStrategy
from src.strategies.neurogenesis.neurogenesis import NeurogenesisStrategy
from src.strategies.replay.replay import ReplayStrategy
from src.strategies.cls.cls import CLSStrategy

from src.hybrid.combiner import (
    EWCReplayStrategy,
    FullBrainStrategy,
    NeurogenesisCLSStrategy,
    TopTwoStrategy,
)

from src.report import generate_all_reports

# Type alias for task data
TaskData = Tuple[List[List[float]], List[int], List[List[float]], List[int]]

# Strategy descriptors for the report
STRATEGY_INFO: Dict[str, Dict[str, str]] = {
    "naive": {
        "name": "Naive",
        "brain_region": "None",
        "description": "Sequential SGD with no protection — demonstrates catastrophic forgetting.",
    },
    "ewc": {
        "name": "EWC",
        "brain_region": "Synaptic consolidation",
        "description": "Elastic Weight Consolidation penalises changes to important weights using Fisher Information.",
    },
    "neurogenesis": {
        "name": "Neurogenesis",
        "brain_region": "Hippocampal neurogenesis",
        "description": "Grows new neurons per task and freezes old connections to protect prior knowledge.",
    },
    "replay": {
        "name": "Replay",
        "brain_region": "Sleep replay",
        "description": "Replays distorted samples from previous tasks during and between training phases.",
    },
    "cls": {
        "name": "CLS",
        "brain_region": "Hippocampal-neocortical",
        "description": "Dual-memory system: fast learner acquires, slow learner consolidates via pseudo-rehearsal.",
    },
    "ewc_replay": {
        "name": "EWC+Replay",
        "brain_region": "Synaptic consolidation + Sleep replay",
        "description": "Combines EWC's Fisher penalty with Sleep Replay's distorted sample buffer.",
    },
    "neurogenesis_cls": {
        "name": "Neurogenesis+CLS",
        "brain_region": "Hippocampal neurogenesis + Dual-memory",
        "description": "CLS dual-memory where the slow learner grows new neurons for each task.",
    },
    "full_brain": {
        "name": "FullBrain",
        "brain_region": "All regions",
        "description": "All four mechanisms combined: CLS + EWC + Neurogenesis + Replay.",
    },
    "top_two": {
        "name": "TopTwo",
        "brain_region": "Best ensemble",
        "description": "Ensemble of the two best single strategies, averaging their predictions.",
    },
}


# ======================================================================
# Strategy runner
# ======================================================================

def _run_strategy(
    strategy: Strategy,
    strategy_key: str,
    tasks: Dict[int, TaskData],
    config: Config,
    needs_buffer: bool = False,
) -> Dict[str, Any]:
    """Train a strategy on all tasks sequentially, tracking accuracy after each.

    Args:
        strategy: strategy instance to train
        strategy_key: identifier string (for logging)
        tasks: {task_idx: (train_imgs, train_lbls, test_imgs, test_lbls)}
        config: experiment config
        needs_buffer: whether to call add_to_buffer after each task (for Replay)

    Returns:
        dict with accuracies_after_each_task, final_accuracies, backward_transfer,
        forgetting_measure, and timing info.
    """
    tracker = MetricsTracker(config.num_tasks)
    task_indices = sorted(tasks.keys())
    accuracies_after_each_task: List[List[float]] = []
    total_start = time.time()

    for task_idx in task_indices:
        train_imgs, train_lbls, test_imgs, test_lbls = tasks[task_idx]
        pair = config.task_pairs[task_idx]
        t_start = time.time()
        print(f"Training [{strategy_key}] on task {task_idx} (digits {pair[0]}-{pair[1]})...")

        strategy.train_task(task_idx, train_imgs, train_lbls, config)
        strategy.on_task_complete(task_idx)

        # Replay strategy needs explicit buffer population
        if needs_buffer and hasattr(strategy, "add_to_buffer"):
            strategy.add_to_buffer(train_imgs, train_lbls, task_idx)

        # Evaluate on all tasks seen so far
        seen_tasks = {t: tasks[t] for t in task_indices[: task_idx + 1]}
        accs = strategy.get_all_accuracies(seen_tasks)
        tracker.record_after_task(task_idx, accs)

        elapsed = time.time() - t_start
        acc_strs = [f"T{t}={accs.get(t, 0.0):.3f}" for t in task_indices[: task_idx + 1]]
        print(f"  Done in {elapsed:.1f}s  {' '.join(acc_strs)}")

        # Build row: accuracy on each of the 5 tasks (None for unseen)
        row = [accs.get(t, None) for t in task_indices]
        accuracies_after_each_task.append(row)

    total_time = time.time() - total_start
    final_accs = tracker.final_accuracies()
    bwt = tracker.backward_transfer()
    fgt = tracker.forgetting()

    print(f"[{strategy_key}] Complete in {total_time:.1f}s  BWT={bwt:+.4f}  Forgetting={fgt:.4f}")
    print(tracker.summary())
    print()

    return {
        "accuracies_after_each_task": accuracies_after_each_task,
        "final_accuracies": final_accs,
        "backward_transfer": bwt,
        "forgetting_measure": fgt,
        "total_time": total_time,
    }


# ======================================================================
# Main experiment
# ======================================================================

def run_experiment() -> Dict[str, Any]:
    """Execute the full Forgetting Cure experiment and generate reports."""
    config = Config()
    print("=" * 60)
    print("  The Forgetting Cure — Experiment Runner")
    print("=" * 60)
    print()

    # 1. Load MNIST and split into 5 tasks
    print("Loading MNIST data...")
    t0 = time.time()
    tasks = make_tasks(task_pairs=config.task_pairs)
    print(f"MNIST loaded in {time.time() - t0:.1f}s")
    for idx, (da, db) in enumerate(config.task_pairs):
        tr, _, te, _ = tasks[idx]
        print(f"  Task {idx}: digits {da}-{db}  train={len(tr)}  test={len(te)}")
    print()

    results: Dict[str, Any] = {}

    # 2. Naive baseline
    print("-" * 50)
    print("Running NAIVE BASELINE")
    print("-" * 50)
    naive = NaiveStrategy(config)
    results["naive"] = _run_strategy(naive, "Naive", tasks, config)

    # 3. Single strategies
    single_strategies: Dict[str, Strategy] = {}

    print("-" * 50)
    print("Running EWC (Elastic Weight Consolidation)")
    print("-" * 50)
    ewc_net = Network(config)
    ewc = EWCStrategy(ewc_net, config)
    results["ewc"] = _run_strategy(ewc, "EWC", tasks, config)
    single_strategies["ewc"] = ewc

    print("-" * 50)
    print("Running NEUROGENESIS (Progressive Growing)")
    print("-" * 50)
    neuro = NeurogenesisStrategy(config)
    results["neurogenesis"] = _run_strategy(neuro, "Neurogenesis", tasks, config)
    single_strategies["neurogenesis"] = neuro

    print("-" * 50)
    print("Running REPLAY (Sleep Replay with Distortion)")
    print("-" * 50)
    replay_net = Network(config)
    replay = ReplayStrategy(replay_net, config)
    results["replay"] = _run_strategy(replay, "Replay", tasks, config, needs_buffer=True)
    single_strategies["replay"] = replay

    print("-" * 50)
    print("Running CLS (Complementary Learning Systems)")
    print("-" * 50)
    cls = CLSStrategy(config)
    results["cls"] = _run_strategy(cls, "CLS", tasks, config)
    single_strategies["cls"] = cls

    # 4. Hybrid combinations
    print("=" * 50)
    print("Running HYBRID COMBINATIONS")
    print("=" * 50)
    print()

    print("-" * 50)
    print("Running EWC+Replay")
    print("-" * 50)
    ewc_replay = EWCReplayStrategy(config)
    results["ewc_replay"] = _run_strategy(ewc_replay, "EWC+Replay", tasks, config)

    print("-" * 50)
    print("Running Neurogenesis+CLS")
    print("-" * 50)
    neuro_cls = NeurogenesisCLSStrategy(config)
    results["neurogenesis_cls"] = _run_strategy(neuro_cls, "Neurogenesis+CLS", tasks, config)

    print("-" * 50)
    print("Running FullBrain (all 4 combined)")
    print("-" * 50)
    full_brain = FullBrainStrategy(config)
    results["full_brain"] = _run_strategy(full_brain, "FullBrain", tasks, config)

    # 5. TopTwo: find the best 2 single strategies and ensemble them
    print("-" * 50)
    print("Finding best two single strategies for TopTwo ensemble...")
    single_avg = {}
    for key in ("ewc", "neurogenesis", "replay", "cls"):
        finals = results[key]["final_accuracies"]
        valid = [a for a in finals if a is not None]
        single_avg[key] = sum(valid) / len(valid) if valid else 0.0
        print(f"  {key}: avg final accuracy = {single_avg[key]:.4f}")

    ranked = sorted(single_avg.items(), key=lambda x: x[1], reverse=True)
    best1_key, best2_key = ranked[0][0], ranked[1][0]
    print(f"  TopTwo ensemble: {best1_key} + {best2_key}")
    print("-" * 50)

    strategy_cls_map = {
        "ewc": EWCStrategy,
        "neurogenesis": NeurogenesisStrategy,
        "replay": ReplayStrategy,
        "cls": CLSStrategy,
    }
    top_two = TopTwoStrategy(
        strategy_cls_map[best1_key],
        strategy_cls_map[best2_key],
        config,
    )
    results["top_two"] = _run_strategy(top_two, "TopTwo", tasks, config)
    results["top_two"]["components"] = [best1_key, best2_key]

    # 6. Add strategy metadata to results
    for key, info in STRATEGY_INFO.items():
        if key in results:
            results[key].update(info)

    # 7. Generate reports
    print("=" * 50)
    print("Generating reports...")
    print("=" * 50)
    output_dir = os.path.join(_DEMO_ROOT, "output")
    generate_all_reports(
        results=results,
        config=config,
        output_dir=output_dir,
    )
    print(f"\nAll reports saved to {output_dir}/")
    print("Done!")

    return results


if __name__ == "__main__":
    run_experiment()
