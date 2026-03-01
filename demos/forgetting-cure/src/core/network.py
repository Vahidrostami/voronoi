"""Base neural network with forward / backprop and the Strategy ABC.

All maths use ``matrix.py`` — no numpy.
Architecture: 784 → hidden_sizes → output  (multi-head: 2 neurons per task).
"""

from __future__ import annotations

import json
import math
import os
import random
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from . import matrix as M
from .config import Config

# Type aliases
Matrix = M.Matrix


# ======================================================================
# Multi-head feed-forward network
# ======================================================================

class Network:
    """Variable-width feed-forward net with multi-head output.

    Layers:  input → hidden[0] → hidden[1] → … → output
    Output has ``neurons_per_head * num_tasks`` neurons.
    Each task uses its own 2-neuron slice of the output.
    """

    def __init__(self, config: Config):
        self.config = config
        self.layer_sizes: List[int] = (
            [config.input_size] + list(config.hidden_sizes) + [config.output_size]
        )
        # Weights[l]: (fan_in, fan_out),  Biases[l]: (1, fan_out)
        self.weights: List[Matrix] = []
        self.biases: List[Matrix] = []
        self._init_params()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_params(self):
        self.weights = []
        self.biases = []
        for i in range(len(self.layer_sizes) - 1):
            fan_in = self.layer_sizes[i]
            fan_out = self.layer_sizes[i + 1]
            self.weights.append(M.he_init(fan_in, fan_out))
            self.biases.append(M.zeros(1, fan_out))

    @property
    def num_layers(self) -> int:
        return len(self.weights)

    # ------------------------------------------------------------------
    # Forward pass
    # ------------------------------------------------------------------

    def forward(self, X: Matrix, task_idx: Optional[int] = None) -> Tuple[Matrix, List[Matrix]]:
        """Forward pass.  Returns (output, cache) where cache holds pre-activations
        and activations needed by backprop.

        If *task_idx* is given, only the 2-neuron head slice is returned via
        softmax; otherwise the raw logits for all heads are returned.
        """
        cache: List[Matrix] = [X]  # cache[0] = input
        A = X
        for l in range(self.num_layers):
            Z = M.add(M.matmul(A, self.weights[l]), self.biases[l])  # broadcast bias
            cache.append(Z)   # pre-activation
            if l < self.num_layers - 1:
                # Hidden layer: ReLU
                A = M.relu(Z)
            else:
                # Output layer: keep raw logits for now
                A = Z
            cache.append(A)   # post-activation
        logits = A  # (batch, output_size)

        if task_idx is not None:
            start = task_idx * self.config.neurons_per_head
            end = start + self.config.neurons_per_head
            head_logits = M.col_slice(logits, start, end)
            probs = M.softmax(head_logits)
            return probs, cache
        return logits, cache

    def predict(self, X: Matrix, task_idx: int) -> List[int]:
        """Return predicted class labels (0 or 1) for *task_idx*."""
        probs, _ = self.forward(X, task_idx=task_idx)
        return M.argmax_row(probs)

    # ------------------------------------------------------------------
    # Backpropagation
    # ------------------------------------------------------------------

    def backprop(
        self,
        X: Matrix,
        Y_onehot: Matrix,
        task_idx: int,
        learning_rate: float,
    ) -> float:
        """One-step back-propagation with cross-entropy loss on the task head.

        Returns the mean loss over the batch.
        """
        batch_size = len(X)
        if batch_size == 0:
            return 0.0
        inv_batch = 1.0 / batch_size

        # --- Forward ---
        probs, cache = self.forward(X, task_idx=task_idx)

        # --- Cross-entropy loss ---
        probs_clipped = M.clip(probs)
        loss = 0.0
        for i in range(batch_size):
            for j in range(len(probs_clipped[0])):
                loss -= Y_onehot[i][j] * math.log(probs_clipped[i][j])
        loss *= inv_batch

        # --- Output gradient (softmax + CE simplification: dL/dZ = probs - Y) ---
        # But we need gradient w.r.t. the *full* output logits
        head_start = task_idx * self.config.neurons_per_head
        head_end = head_start + self.config.neurons_per_head
        full_output_size = self.config.output_size

        # dZ for output layer — zero everywhere except the active head
        dZ_out = M.zeros(batch_size, full_output_size)
        for i in range(batch_size):
            for j in range(self.config.neurons_per_head):
                dZ_out[i][head_start + j] = (probs[i][j] - Y_onehot[i][j]) * inv_batch

        # --- Backward through layers ---
        # cache layout: [X, Z0, A0, Z1, A1, …, Z_L, A_L]
        # index of Z_l = 1 + 2*l,  A_l = 2 + 2*l
        dZ = dZ_out
        for l in reversed(range(self.num_layers)):
            A_prev = cache[2 * l]  # activation of previous layer (or input)
            # Gradients for weights and biases
            dW = M.matmul(M.transpose(A_prev), dZ)
            dB = M.sum_cols(dZ)

            # Update parameters
            self.weights[l] = M.subtract(self.weights[l], M.scalar_mul(dW, learning_rate))
            self.biases[l] = M.subtract(self.biases[l], M.scalar_mul(dB, learning_rate))

            # Propagate gradient to previous layer (skip if first layer)
            if l > 0:
                dA_prev = M.matmul(dZ, M.transpose(self.weights[l]))
                # ReLU derivative on pre-activation of layer l-1
                Z_prev = cache[1 + 2 * (l - 1)]
                relu_mask = M.relu_derivative(Z_prev)
                dZ = M.multiply(dA_prev, relu_mask)

        return loss

    # ------------------------------------------------------------------
    # Training loop (mini-batch SGD)
    # ------------------------------------------------------------------

    def train_epoch(
        self,
        images: List[List[float]],
        labels: List[int],
        task_idx: int,
        learning_rate: float,
        batch_size: int,
    ) -> float:
        """Train one full epoch with mini-batch SGD. Returns mean loss."""
        n = len(images)
        indices = list(range(n))
        random.shuffle(indices)
        total_loss = 0.0
        n_batches = 0
        for start in range(0, n, batch_size):
            end = min(start + batch_size, n)
            batch_idx = indices[start:end]
            X = [images[i] for i in batch_idx]
            Y = [labels[i] for i in batch_idx]
            Y_oh = M.to_one_hot(Y, self.config.neurons_per_head)
            loss = self.backprop(X, Y_oh, task_idx, learning_rate)
            total_loss += loss
            n_batches += 1
        return total_loss / max(n_batches, 1)

    # ------------------------------------------------------------------
    # Save / Load weights
    # ------------------------------------------------------------------

    def save(self, path: str):
        """Serialise weights and biases to JSON."""
        data = {
            "layer_sizes": self.layer_sizes,
            "weights": [M.flatten(w) for w in self.weights],
            "biases": [M.flatten(b) for b in self.biases],
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)

    def load(self, path: str):
        """Load weights from a JSON file previously created by ``save``."""
        with open(path, "r") as f:
            data = json.load(f)
        self.layer_sizes = data["layer_sizes"]
        self.weights = []
        self.biases = []
        for i in range(len(self.layer_sizes) - 1):
            fan_in = self.layer_sizes[i]
            fan_out = self.layer_sizes[i + 1]
            self.weights.append(M.from_flat(data["weights"][i], fan_in, fan_out))
            self.biases.append(M.from_flat(data["biases"][i], 1, fan_out))

    def get_flat_params(self) -> List[float]:
        """Return all parameters as a single flat list (for EWC etc.)."""
        params: List[float] = []
        for w in self.weights:
            params.extend(M.flatten(w))
        for b in self.biases:
            params.extend(M.flatten(b))
        return params

    def set_flat_params(self, flat: List[float]):
        """Set parameters from a flat list (inverse of get_flat_params)."""
        idx = 0
        for l in range(self.num_layers):
            fan_in = self.layer_sizes[l]
            fan_out = self.layer_sizes[l + 1]
            size = fan_in * fan_out
            self.weights[l] = M.from_flat(flat[idx:idx + size], fan_in, fan_out)
            idx += size
        for l in range(self.num_layers):
            fan_out = self.layer_sizes[l + 1]
            self.biases[l] = M.from_flat(flat[idx:idx + fan_out], 1, fan_out)
            idx += fan_out

    # ------------------------------------------------------------------
    # Layer resizing (for neurogenesis strategy)
    # ------------------------------------------------------------------

    def grow_layer(self, layer_idx: int, extra_neurons: int):
        """Add *extra_neurons* to a hidden layer.

        Adjusts weights feeding *into* and *out of* this layer.
        New weights are He-initialised; new biases are zero.
        """
        if layer_idx < 0 or layer_idx >= self.num_layers - 1:
            raise ValueError("Can only grow hidden layers")

        old_fan_out = self.layer_sizes[layer_idx + 1]
        new_fan_out = old_fan_out + extra_neurons
        self.layer_sizes[layer_idx + 1] = new_fan_out

        # --- Grow weights INTO this layer (layer_idx) ---
        fan_in = self.layer_sizes[layer_idx]
        extra_w = M.he_init(fan_in, extra_neurons)
        self.weights[layer_idx] = M.hstack(self.weights[layer_idx], extra_w)
        extra_b = M.zeros(1, extra_neurons)
        self.biases[layer_idx] = M.hstack(self.biases[layer_idx], extra_b)

        # --- Grow weights OUT of this layer (layer_idx + 1) ---
        if layer_idx + 1 < self.num_layers:
            next_fan_out = self.layer_sizes[layer_idx + 2]
            extra_w_out = M.he_init(extra_neurons, next_fan_out)
            self.weights[layer_idx + 1] = M.vstack(
                self.weights[layer_idx + 1], extra_w_out
            )


# ======================================================================
# Strategy interface (ABC)
# ======================================================================

class Strategy(ABC):
    """Abstract base class every continual-learning strategy must implement."""

    @abstractmethod
    def train_task(
        self,
        task_idx: int,
        train_images: List[List[float]],
        train_labels: List[int],
        config: Config,
    ) -> None:
        """Train the model on one task (identified by *task_idx*)."""
        ...

    @abstractmethod
    def evaluate(
        self,
        task_idx: int,
        test_images: List[List[float]],
        test_labels: List[int],
    ) -> float:
        """Return accuracy on *task_idx*'s test set."""
        ...

    @abstractmethod
    def on_task_complete(self, task_idx: int) -> None:
        """Hook called after a task finishes training (consolidation, etc.)."""
        ...

    @abstractmethod
    def get_all_accuracies(
        self,
        tasks: Dict[int, Any],
    ) -> Dict[int, float]:
        """Evaluate on ALL tasks seen so far, returning {task_idx: accuracy}.

        *tasks* maps task_idx → (train_imgs, train_lbls, test_imgs, test_lbls).
        """
        ...
