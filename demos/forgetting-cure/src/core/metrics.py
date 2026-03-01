"""Continual-learning metrics: accuracy, BWT, forward transfer, forgetting."""

from typing import Dict, List, Optional


class MetricsTracker:
    """Track per-task accuracy after each training phase.

    accuracy_matrix[i][j] = accuracy on task j after training on task i.
    Rows: training phase index.  Columns: task index.
    """

    def __init__(self, num_tasks: int = 5):
        self.num_tasks = num_tasks
        # accuracy_matrix[i][j] — filled as tasks are learned
        self.accuracy_matrix: List[List[Optional[float]]] = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_after_task(self, task_idx: int, accuracies: Dict[int, float]):
        """Record evaluation results after finishing *task_idx*.

        Args:
            task_idx: zero-based index of the task just learned.
            accuracies: {task_j: accuracy} for every task evaluated.
        """
        row: List[Optional[float]] = [None] * self.num_tasks
        for j, acc in accuracies.items():
            row[j] = acc
        # Pad / extend the matrix to the right row
        while len(self.accuracy_matrix) <= task_idx:
            self.accuracy_matrix.append([None] * self.num_tasks)
        self.accuracy_matrix[task_idx] = row

    # ------------------------------------------------------------------
    # Scalar metrics
    # ------------------------------------------------------------------

    def accuracy(self, predictions: List[int], labels: List[int]) -> float:
        """Simple classification accuracy."""
        if len(predictions) == 0:
            return 0.0
        correct = sum(1 for p, l in zip(predictions, labels) if p == l)
        return correct / len(predictions)

    def final_accuracies(self) -> List[Optional[float]]:
        """Accuracy on each task after ALL tasks have been trained."""
        if not self.accuracy_matrix:
            return []
        return list(self.accuracy_matrix[-1])

    def backward_transfer(self) -> float:
        """BWT = (1/(T-1)) * sum_{j<T} (R_{T,j} - R_{j,j})

        Measures how much learning later tasks helped/hurt earlier ones.
        Negative BWT → catastrophic forgetting.
        """
        T = len(self.accuracy_matrix)
        if T < 2:
            return 0.0
        total = 0.0
        count = 0
        for j in range(T - 1):
            r_Tj = self.accuracy_matrix[T - 1][j]
            r_jj = self.accuracy_matrix[j][j]
            if r_Tj is not None and r_jj is not None:
                total += r_Tj - r_jj
                count += 1
        return total / count if count > 0 else 0.0

    def forward_transfer(self) -> float:
        """FWT = (1/(T-1)) * sum_{j>0} (R_{j-1,j} - b_j)

        b_j is the baseline (random-chance) accuracy for task j.
        For 2-class tasks, random baseline = 0.5.
        """
        T = len(self.accuracy_matrix)
        if T < 2:
            return 0.0
        baseline = 0.5  # 2-class per task
        total = 0.0
        count = 0
        for j in range(1, T):
            r_prev_j = self.accuracy_matrix[j - 1][j]
            if r_prev_j is not None:
                total += r_prev_j - baseline
                count += 1
        return total / count if count > 0 else 0.0

    def forgetting(self) -> float:
        """Average forgetting across tasks.

        f_j = max_{l in [0..T-2]} R_{l,j} - R_{T-1,j}
        Forgetting = (1/(T-1)) * sum f_j  for j < T-1
        """
        T = len(self.accuracy_matrix)
        if T < 2:
            return 0.0
        total = 0.0
        count = 0
        for j in range(T - 1):
            best = None
            for l in range(T - 1):
                val = self.accuracy_matrix[l][j]
                if val is not None:
                    if best is None or val > best:
                        best = val
            last = self.accuracy_matrix[T - 1][j]
            if best is not None and last is not None:
                total += best - last
                count += 1
        return total / count if count > 0 else 0.0

    # ------------------------------------------------------------------
    # Pretty-print
    # ------------------------------------------------------------------

    def summary(self) -> str:
        lines = ["=== Continual-Learning Metrics ==="]
        lines.append(f"  BWT (backward transfer) : {self.backward_transfer():+.4f}")
        lines.append(f"  FWT (forward transfer)  : {self.forward_transfer():+.4f}")
        lines.append(f"  Forgetting              : {self.forgetting():.4f}")
        finals = self.final_accuracies()
        for j, acc in enumerate(finals):
            acc_str = f"{acc:.4f}" if acc is not None else "N/A"
            lines.append(f"  Task {j} final accuracy  : {acc_str}")
        return "\n".join(lines)

    def log_after_task(self, task_idx: int):
        """Print a one-line log after each task."""
        if task_idx >= len(self.accuracy_matrix):
            return
        row = self.accuracy_matrix[task_idx]
        parts = []
        for j, v in enumerate(row):
            if v is not None:
                parts.append(f"T{j}={v:.3f}")
        print(f"[After task {task_idx}] " + "  ".join(parts))
