"""Report generator for the Forgetting Cure experiment.

Produces:
  - output/results.csv
  - output/accuracy_matrix.png
  - output/learning_curves.png
  - output/backward_transfer.png
  - output/discovery.md
  - output/results.json
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict, List, Optional

from src.core.config import Config

# Attempt matplotlib import — gracefully degrade if unavailable
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


# Strategy display order
STRATEGY_ORDER = [
    "naive", "ewc", "neurogenesis", "replay", "cls",
    "ewc_replay", "neurogenesis_cls", "full_brain", "top_two",
]

TASK_LABELS = ["digits_0_1", "digits_2_3", "digits_4_5", "digits_6_7", "digits_8_9"]
TASK_DISPLAY = ["0-1", "2-3", "4-5", "6-7", "8-9"]


def _ordered_keys(results: Dict[str, Any]) -> List[str]:
    """Return strategy keys in display order, filtering to those present."""
    return [k for k in STRATEGY_ORDER if k in results]


def _avg_accuracy(finals: List[Optional[float]]) -> float:
    valid = [a for a in finals if a is not None]
    return sum(valid) / len(valid) if valid else 0.0


# ======================================================================
# 1. CSV report
# ======================================================================

def _write_csv(results: Dict[str, Any], output_dir: str) -> None:
    path = os.path.join(output_dir, "results.csv")
    keys = _ordered_keys(results)

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "strategy", "task_1_acc", "task_2_acc", "task_3_acc",
            "task_4_acc", "task_5_acc", "avg_accuracy",
            "backward_transfer", "forgetting_measure",
        ])
        for key in keys:
            r = results[key]
            finals = r["final_accuracies"]
            avg = _avg_accuracy(finals)
            row = [
                r.get("name", key),
                *[f"{a:.4f}" if a is not None else "" for a in finals],
                f"{avg:.4f}",
                f"{r['backward_transfer']:.4f}",
                f"{r['forgetting_measure']:.4f}",
            ]
            writer.writerow(row)

    print(f"  CSV → {path}")


# ======================================================================
# 2. Accuracy matrix heatmap
# ======================================================================

def _write_accuracy_matrix(results: Dict[str, Any], output_dir: str) -> None:
    if not HAS_MATPLOTLIB:
        print("  [SKIP] accuracy_matrix.png — matplotlib not available")
        return

    keys = _ordered_keys(results)
    names = [results[k].get("name", k) for k in keys]

    # Build matrix: rows=strategies, cols=tasks
    matrix = []
    for key in keys:
        finals = results[key]["final_accuracies"]
        matrix.append([a if a is not None else 0.0 for a in finals])

    fig, ax = plt.subplots(figsize=(8, max(4, len(keys) * 0.6)))

    # Custom red→yellow→green colormap
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "ryg", ["#d32f2f", "#ffeb3b", "#388e3c"]
    )
    im = ax.imshow(matrix, cmap=cmap, aspect="auto", vmin=0.0, vmax=1.0)

    ax.set_xticks(range(5))
    ax.set_xticklabels(TASK_DISPLAY)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names)
    ax.set_xlabel("Task (digit pair)")
    ax.set_ylabel("Strategy")
    ax.set_title("Final Accuracy Matrix")

    # Annotate cells
    for i in range(len(names)):
        for j in range(5):
            val = matrix[i][j]
            color = "white" if val < 0.5 else "black"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=9, color=color)

    fig.colorbar(im, ax=ax, label="Accuracy")
    plt.tight_layout()
    path = os.path.join(output_dir, "accuracy_matrix.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Heatmap → {path}")


# ======================================================================
# 3. Learning curves (Task 1 accuracy over time)
# ======================================================================

def _write_learning_curves(results: Dict[str, Any], output_dir: str) -> None:
    if not HAS_MATPLOTLIB:
        print("  [SKIP] learning_curves.png — matplotlib not available")
        return

    keys = _ordered_keys(results)
    fig, ax = plt.subplots(figsize=(8, 5))

    for key in keys:
        r = results[key]
        name = r.get("name", key)
        mat = r["accuracies_after_each_task"]
        # Task 0 accuracy after training on task 0, 1, 2, 3, 4
        task0_over_time = []
        for row in mat:
            val = row[0] if row[0] is not None else None
            task0_over_time.append(val)

        x = list(range(1, len(task0_over_time) + 1))
        y = [v if v is not None else 0.0 for v in task0_over_time]
        ax.plot(x, y, marker="o", label=name, linewidth=2, markersize=5)

    ax.set_xlabel("After training on task N")
    ax.set_ylabel("Task 1 (digits 0-1) Accuracy")
    ax.set_title("Forgetting Curve: Task 1 Accuracy Over Time")
    ax.set_xticks(range(1, 6))
    ax.set_xticklabels(["Task 1", "Task 2", "Task 3", "Task 4", "Task 5"])
    ax.set_ylim(-0.05, 1.05)
    ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    path = os.path.join(output_dir, "learning_curves.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Learning curves → {path}")


# ======================================================================
# 4. Backward transfer bar chart
# ======================================================================

def _write_backward_transfer(results: Dict[str, Any], output_dir: str) -> None:
    if not HAS_MATPLOTLIB:
        print("  [SKIP] backward_transfer.png — matplotlib not available")
        return

    keys = _ordered_keys(results)
    names = [results[k].get("name", k) for k in keys]
    bwts = [results[k]["backward_transfer"] for k in keys]

    fig, ax = plt.subplots(figsize=(10, 5))
    colors = ["#d32f2f" if b < -0.1 else "#ff9800" if b < 0 else "#388e3c" for b in bwts]
    bars = ax.bar(names, bwts, color=colors, edgecolor="black", linewidth=0.5)

    # Annotate bars
    for bar, bwt in zip(bars, bwts):
        y = bar.get_height()
        offset = 0.02 if y >= 0 else -0.04
        ax.text(bar.get_x() + bar.get_width() / 2, y + offset,
                f"{bwt:+.3f}", ha="center", va="bottom", fontsize=8)

    ax.axhline(y=0, color="black", linewidth=0.8)
    ax.set_ylabel("Backward Transfer (BWT)")
    ax.set_title("Backward Transfer: Higher is Better (0 = no forgetting)")
    ax.set_xticklabels(names, rotation=30, ha="right")
    ax.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    path = os.path.join(output_dir, "backward_transfer.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  BWT chart → {path}")


# ======================================================================
# 5. Discovery markdown
# ======================================================================

def _write_discovery(results: Dict[str, Any], output_dir: str) -> str:
    """Generate discovery.md and return the discovery text."""
    keys = _ordered_keys(results)

    # Find best single strategy
    single_keys = [k for k in ("ewc", "neurogenesis", "replay", "cls") if k in results]
    single_avgs = {k: _avg_accuracy(results[k]["final_accuracies"]) for k in single_keys}
    best_single = max(single_avgs, key=single_avgs.get) if single_avgs else "unknown"
    best_single_avg = single_avgs.get(best_single, 0.0)

    # Find best hybrid
    hybrid_keys = [k for k in ("ewc_replay", "neurogenesis_cls", "full_brain", "top_two") if k in results]
    hybrid_avgs = {k: _avg_accuracy(results[k]["final_accuracies"]) for k in hybrid_keys}
    best_hybrid = max(hybrid_avgs, key=hybrid_avgs.get) if hybrid_avgs else "unknown"
    best_hybrid_avg = hybrid_avgs.get(best_hybrid, 0.0)

    # Overall best
    all_avgs = {**single_avgs, **hybrid_avgs}
    overall_best = max(all_avgs, key=all_avgs.get) if all_avgs else "unknown"
    overall_best_avg = all_avgs.get(overall_best, 0.0)

    # Naive baseline
    naive_avg = _avg_accuracy(results["naive"]["final_accuracies"]) if "naive" in results else 0.0
    naive_bwt = results["naive"]["backward_transfer"] if "naive" in results else 0.0
    naive_fgt = results["naive"]["forgetting_measure"] if "naive" in results else 0.0

    hybrid_beat_all = best_hybrid_avg > best_single_avg

    lines = [
        "# The Forgetting Cure — Discovery Report",
        "",
        "## Executive Summary",
        "",
        f"The experiment trained neural networks on 5 sequential MNIST digit-pair tasks ",
        f"(0-1, 2-3, 4-5, 6-7, 8-9) and compared {len(keys)} strategies for resisting ",
        "catastrophic forgetting.",
        "",
        "## Key Findings",
        "",
        f"### 1. Naive Baseline Shows Catastrophic Forgetting",
        f"- Average final accuracy: **{naive_avg:.1%}**",
        f"- Backward transfer: **{naive_bwt:+.4f}** (negative = forgetting)",
        f"- Forgetting measure: **{naive_fgt:.4f}**",
        "",
        f"### 2. Best Single Strategy: **{results[best_single].get('name', best_single)}**",
        f"- Average final accuracy: **{best_single_avg:.1%}**",
        f"- BWT: **{results[best_single]['backward_transfer']:+.4f}**",
        f"- Forgetting: **{results[best_single]['forgetting_measure']:.4f}**",
        "",
    ]

    # All single strategies comparison
    lines.extend([
        "### 3. Single Strategy Comparison",
        "",
        "| Strategy | Avg Accuracy | BWT | Forgetting |",
        "|----------|-------------|-----|------------|",
    ])
    for k in single_keys:
        r = results[k]
        avg = _avg_accuracy(r["final_accuracies"])
        lines.append(
            f"| {r.get('name', k)} | {avg:.1%} | {r['backward_transfer']:+.4f} | {r['forgetting_measure']:.4f} |"
        )
    lines.append("")

    # Hybrid results
    if hybrid_keys:
        best_hybrid_name = results[best_hybrid].get("name", best_hybrid)
    else:
        best_hybrid_name = "N/A"
    lines.extend([
        f"### 4. {'Hybrid Beat All Singles!' if hybrid_beat_all else 'Hybrid vs Single Strategies'}",
        "",
        f"Best hybrid: **{best_hybrid_name}** "
        f"({best_hybrid_avg:.1%} avg accuracy)",
        "",
    ])
    if hybrid_beat_all:
        improvement = best_hybrid_avg - best_single_avg
        lines.append(
            f"The best hybrid improved on the best single strategy by "
            f"**{improvement:.1%}** absolute accuracy."
        )
    else:
        lines.append(
            "No hybrid combination outperformed the best single strategy."
        )
    lines.append("")

    lines.extend([
        "| Hybrid | Avg Accuracy | BWT | Forgetting |",
        "|--------|-------------|-----|------------|",
    ])
    for k in hybrid_keys:
        r = results[k]
        avg = _avg_accuracy(r["final_accuracies"])
        lines.append(
            f"| {r.get('name', k)} | {avg:.1%} | {r['backward_transfer']:+.4f} | {r['forgetting_measure']:.4f} |"
        )
    lines.append("")

    # Optimal brain recipe
    lines.extend([
        "### 5. Optimal Brain Recipe",
        "",
        f"The overall best strategy was **{results[overall_best].get('name', overall_best)}** "
        f"with **{overall_best_avg:.1%}** average accuracy across all 5 tasks.",
        "",
        f"- Backward transfer: **{results[overall_best]['backward_transfer']:+.4f}**",
        f"- Forgetting measure: **{results[overall_best]['forgetting_measure']:.4f}**",
        f"- Improvement over naive: **{overall_best_avg - naive_avg:.1%}** absolute",
        "",
    ])

    # Per-task details for overall best
    lines.extend([
        "### 6. Per-Task Final Accuracies (Best Strategy)",
        "",
        "| Task | Digits | Accuracy |",
        "|------|--------|----------|",
    ])
    best_finals = results[overall_best]["final_accuracies"]
    for i, (label, display) in enumerate(zip(TASK_LABELS, TASK_DISPLAY)):
        acc = best_finals[i] if i < len(best_finals) and best_finals[i] is not None else 0.0
        lines.append(f"| {i + 1} | {display} | {acc:.1%} |")
    lines.append("")

    lines.extend([
        "---",
        "",
        "*Generated by The Forgetting Cure experiment runner.*",
    ])

    text = "\n".join(lines)
    path = os.path.join(output_dir, "discovery.md")
    with open(path, "w") as f:
        f.write(text)
    print(f"  Discovery → {path}")
    return text


# ======================================================================
# 6. JSON report
# ======================================================================

def _write_json(results: Dict[str, Any], discovery_text: str, output_dir: str) -> None:
    keys = _ordered_keys(results)

    # Find best single / hybrid
    single_keys = [k for k in ("ewc", "neurogenesis", "replay", "cls") if k in results]
    hybrid_keys = [k for k in ("ewc_replay", "neurogenesis_cls", "full_brain", "top_two") if k in results]
    single_avgs = {k: _avg_accuracy(results[k]["final_accuracies"]) for k in single_keys}
    hybrid_avgs = {k: _avg_accuracy(results[k]["final_accuracies"]) for k in hybrid_keys}
    best_single = max(single_avgs, key=single_avgs.get) if single_avgs else ""
    best_hybrid = max(hybrid_avgs, key=hybrid_avgs.get) if hybrid_avgs else ""

    strategies_json: Dict[str, Any] = {}
    for key in keys:
        r = results[key]
        # Convert None to null-safe floats in accuracy lists
        acc_matrix = []
        for row in r["accuracies_after_each_task"]:
            acc_matrix.append([round(v, 4) if v is not None else None for v in row])

        final_accs = [round(a, 4) if a is not None else None for a in r["final_accuracies"]]

        strategies_json[key] = {
            "name": r.get("name", key),
            "brain_region": r.get("brain_region", ""),
            "description": r.get("description", ""),
            "accuracies_after_each_task": acc_matrix,
            "final_accuracies": final_accs,
            "backward_transfer": round(r["backward_transfer"], 4),
            "forgetting_measure": round(r["forgetting_measure"], 4),
        }

    output = {
        "strategies": strategies_json,
        "tasks": TASK_LABELS,
        "best_single": best_single,
        "best_hybrid": best_hybrid,
        "discovery_text": discovery_text,
    }

    path = os.path.join(output_dir, "results.json")
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"  JSON → {path}")


# ======================================================================
# Public API
# ======================================================================

def generate_all_reports(
    results: Dict[str, Any],
    config: Config,
    output_dir: str,
) -> None:
    """Generate all output files from experiment results."""
    os.makedirs(output_dir, exist_ok=True)

    _write_csv(results, output_dir)
    _write_accuracy_matrix(results, output_dir)
    _write_learning_curves(results, output_dir)
    _write_backward_transfer(results, output_dir)
    discovery_text = _write_discovery(results, output_dir)
    _write_json(results, discovery_text, output_dir)
