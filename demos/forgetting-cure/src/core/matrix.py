"""Pure-Python 2-D matrix operations — NO numpy allowed.

Every matrix is represented as ``list[list[float]]`` (rows × cols).
"""

from __future__ import annotations

import math
import random
from typing import Callable, List, Optional, Tuple, Union

# Type alias
Matrix = List[List[float]]

# ------------------------------------------------------------------
# Construction helpers
# ------------------------------------------------------------------


def shape(m: Matrix) -> Tuple[int, int]:
    """Return (rows, cols)."""
    rows = len(m)
    cols = len(m[0]) if rows > 0 else 0
    return rows, cols


def zeros(rows: int, cols: int) -> Matrix:
    return [[0.0] * cols for _ in range(rows)]


def ones(rows: int, cols: int) -> Matrix:
    return [[1.0] * cols for _ in range(rows)]


def random_matrix(rows: int, cols: int, low: float = -1.0, high: float = 1.0,
                  seed: Optional[int] = None) -> Matrix:
    """Uniform random in [low, high)."""
    if seed is not None:
        random.seed(seed)
    return [[random.uniform(low, high) for _ in range(cols)] for _ in range(rows)]


def random_normal(rows: int, cols: int, mean: float = 0.0, std: float = 1.0,
                  seed: Optional[int] = None) -> Matrix:
    """Gaussian random with given mean/std."""
    if seed is not None:
        random.seed(seed)
    return [[random.gauss(mean, std) for _ in range(cols)] for _ in range(rows)]


def he_init(rows: int, cols: int) -> Matrix:
    """He (Kaiming) initialisation for ReLU layers.

    std = sqrt(2 / fan_in), where fan_in = cols (input dimension).
    """
    std = math.sqrt(2.0 / cols) if cols > 0 else 0.01
    return random_normal(rows, cols, mean=0.0, std=std)


def from_flat(data: List[float], rows: int, cols: int) -> Matrix:
    """Reshape a flat list into a matrix."""
    assert len(data) == rows * cols
    return [data[i * cols:(i + 1) * cols] for i in range(rows)]


def flatten(m: Matrix) -> List[float]:
    """Flatten a matrix to a single list."""
    return [v for row in m for v in row]


def deep_copy(m: Matrix) -> Matrix:
    """Return an independent copy."""
    return [row[:] for row in m]


# ------------------------------------------------------------------
# Transpose
# ------------------------------------------------------------------


def transpose(m: Matrix) -> Matrix:
    rows, cols = shape(m)
    return [[m[r][c] for r in range(rows)] for c in range(cols)]


# ------------------------------------------------------------------
# Element-wise operations
# ------------------------------------------------------------------


def _broadcast(a: Matrix, b: Matrix) -> Tuple[Matrix, Matrix, int, int]:
    """Minimal broadcasting: allow (R,C) op (1,C) or (R,1) or (1,1)."""
    ra, ca = shape(a)
    rb, cb = shape(b)
    out_r = max(ra, rb)
    out_c = max(ca, cb)

    def _expand(m: Matrix, mr: int, mc: int, tr: int, tc: int) -> Matrix:
        result = zeros(tr, tc)
        for r in range(tr):
            for c in range(tc):
                result[r][c] = m[r % mr][c % mc]
        return result

    if ra != out_r or ca != out_c:
        a = _expand(a, ra, ca, out_r, out_c)
    if rb != out_r or cb != out_c:
        b = _expand(b, rb, cb, out_r, out_c)
    return a, b, out_r, out_c


def _elementwise(a: Matrix, b: Matrix, op: Callable[[float, float], float]) -> Matrix:
    a, b, rows, cols = _broadcast(a, b)
    return [[op(a[r][c], b[r][c]) for c in range(cols)] for r in range(rows)]


def add(a: Matrix, b: Matrix) -> Matrix:
    """Element-wise addition with broadcasting."""
    return _elementwise(a, b, lambda x, y: x + y)


def subtract(a: Matrix, b: Matrix) -> Matrix:
    """Element-wise subtraction with broadcasting."""
    return _elementwise(a, b, lambda x, y: x - y)


def multiply(a: Matrix, b: Matrix) -> Matrix:
    """Element-wise (Hadamard) multiplication with broadcasting."""
    return _elementwise(a, b, lambda x, y: x * y)


# ------------------------------------------------------------------
# Scalar operations
# ------------------------------------------------------------------


def scalar_mul(m: Matrix, s: float) -> Matrix:
    return [[v * s for v in row] for row in m]


def scalar_add(m: Matrix, s: float) -> Matrix:
    return [[v + s for v in row] for row in m]


# ------------------------------------------------------------------
# Matrix multiplication
# ------------------------------------------------------------------


def matmul(a: Matrix, b: Matrix) -> Matrix:
    """Standard matrix multiply: (R1, K) @ (K, C2) -> (R1, C2)."""
    ra, ka = shape(a)
    kb, cb = shape(b)
    assert ka == kb, f"matmul dimension mismatch: ({ra},{ka}) @ ({kb},{cb})"
    result = zeros(ra, cb)
    for i in range(ra):
        for j in range(cb):
            s = 0.0
            for k in range(ka):
                s += a[i][k] * b[k][j]
            result[i][j] = s
    return result


# ------------------------------------------------------------------
# Activation functions (operate row-wise on matrices)
# ------------------------------------------------------------------


def apply(m: Matrix, fn: Callable[[float], float]) -> Matrix:
    """Apply a scalar function element-wise."""
    return [[fn(v) for v in row] for row in m]


def relu(m: Matrix) -> Matrix:
    return apply(m, lambda x: max(0.0, x))


def relu_derivative(m: Matrix) -> Matrix:
    """Derivative of ReLU: 1 if x > 0 else 0."""
    return apply(m, lambda x: 1.0 if x > 0 else 0.0)


def _stable_softmax_row(row: List[float]) -> List[float]:
    """Numerically stable softmax for a single row."""
    max_val = max(row)
    exps = [math.exp(v - max_val) for v in row]
    total = sum(exps)
    if total == 0.0:
        n = len(row)
        return [1.0 / n] * n
    return [e / total for e in exps]


def softmax(m: Matrix) -> Matrix:
    """Row-wise softmax, numerically stable."""
    return [_stable_softmax_row(row) for row in m]


def clip(m: Matrix, lo: float = 1e-12, hi: float = 1.0 - 1e-12) -> Matrix:
    """Clip values to [lo, hi] for numerical stability in log."""
    return [[max(lo, min(hi, v)) for v in row] for row in m]


# ------------------------------------------------------------------
# Reduction helpers
# ------------------------------------------------------------------


def sum_rows(m: Matrix) -> Matrix:
    """Sum across columns → (R, 1)."""
    return [[sum(row)] for row in m]


def sum_cols(m: Matrix) -> Matrix:
    """Sum across rows → (1, C)."""
    rows, cols = shape(m)
    result = [0.0] * cols
    for r in range(rows):
        for c in range(cols):
            result[c] += m[r][c]
    return [result]


def mean_cols(m: Matrix) -> Matrix:
    """Mean across rows → (1, C)."""
    rows, cols = shape(m)
    s = sum_cols(m)
    return [[v / rows for v in s[0]]]


def argmax_row(m: Matrix) -> List[int]:
    """Argmax per row."""
    result = []
    for row in m:
        best_idx = 0
        best_val = row[0]
        for i in range(1, len(row)):
            if row[i] > best_val:
                best_val = row[i]
                best_idx = i
        result.append(best_idx)
    return result


# ------------------------------------------------------------------
# Row / column slicing
# ------------------------------------------------------------------


def col_slice(m: Matrix, start: int, end: int) -> Matrix:
    """Slice columns [start, end) from each row."""
    return [row[start:end] for row in m]


def row_slice(m: Matrix, start: int, end: int) -> Matrix:
    """Slice rows [start, end)."""
    return [row[:] for row in m[start:end]]


def hstack(a: Matrix, b: Matrix) -> Matrix:
    """Horizontal concatenation."""
    assert len(a) == len(b)
    return [ra + rb for ra, rb in zip(a, b)]


def vstack(a: Matrix, b: Matrix) -> Matrix:
    """Vertical concatenation."""
    ra, ca = shape(a)
    rb, cb = shape(b)
    assert ca == cb, f"vstack width mismatch {ca} vs {cb}"
    return [row[:] for row in a] + [row[:] for row in b]


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------


def to_one_hot(labels: List[int], num_classes: int) -> Matrix:
    """Convert integer labels to one-hot rows."""
    m = zeros(len(labels), num_classes)
    for i, lbl in enumerate(labels):
        m[i][lbl] = 1.0
    return m


def max_abs(m: Matrix) -> float:
    """Largest absolute value in the matrix (for debugging)."""
    return max(abs(v) for row in m for v in row) if m and m[0] else 0.0


# ======================================================================
# Basic unit tests
# ======================================================================
if __name__ == "__main__":
    print("Running matrix.py unit tests …")

    # -- shape
    m = zeros(3, 4)
    assert shape(m) == (3, 4), "shape failed"

    # -- ones
    m = ones(2, 3)
    assert m == [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]]

    # -- transpose
    m = [[1, 2, 3], [4, 5, 6]]
    t = transpose(m)
    assert shape(t) == (3, 2)
    assert t == [[1, 4], [2, 5], [3, 6]]

    # -- matmul
    a = [[1.0, 2.0], [3.0, 4.0]]
    b = [[5.0, 6.0], [7.0, 8.0]]
    c = matmul(a, b)
    assert c == [[19.0, 22.0], [43.0, 50.0]], f"matmul failed: {c}"

    # -- element-wise add
    a = [[1.0, 2.0], [3.0, 4.0]]
    b = [[10.0, 20.0], [30.0, 40.0]]
    assert add(a, b) == [[11.0, 22.0], [33.0, 44.0]]

    # -- subtract
    assert subtract(b, a) == [[9.0, 18.0], [27.0, 36.0]]

    # -- element-wise multiply
    assert multiply(a, b) == [[10.0, 40.0], [90.0, 160.0]]

    # -- scalar ops
    assert scalar_mul([[1, 2], [3, 4]], 3) == [[3, 6], [9, 12]]
    assert scalar_add([[1, 2], [3, 4]], 10) == [[11, 12], [13, 14]]

    # -- broadcasting: (2,2) + (1,2)
    res = add([[1.0, 2.0], [3.0, 4.0]], [[10.0, 20.0]])
    assert res == [[11.0, 22.0], [13.0, 24.0]], f"broadcast add failed: {res}"

    # -- relu
    assert relu([[-1, 0, 1], [-2, 3, -0.5]]) == [[0, 0, 1], [0, 3, 0]]

    # -- softmax numerical stability (large values)
    large = [[1000.0, 1000.0, 1001.0]]
    sm = softmax(large)
    assert abs(sum(sm[0]) - 1.0) < 1e-6, "softmax should sum to 1"
    assert sm[0][2] > sm[0][0], "softmax wrong order"

    # -- argmax
    assert argmax_row([[0.1, 0.9], [0.8, 0.2]]) == [1, 0]

    # -- one-hot
    oh = to_one_hot([0, 2, 1], 3)
    assert oh == [[1, 0, 0], [0, 0, 1], [0, 1, 0]]

    # -- col_slice
    m = [[1, 2, 3, 4], [5, 6, 7, 8]]
    assert col_slice(m, 1, 3) == [[2, 3], [6, 7]]

    # -- hstack / vstack
    a = [[1, 2], [3, 4]]
    b = [[5, 6], [7, 8]]
    assert hstack(a, b) == [[1, 2, 5, 6], [3, 4, 7, 8]]
    assert vstack(a, b) == [[1, 2], [3, 4], [5, 6], [7, 8]]

    # -- flatten / from_flat round-trip
    m = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert from_flat(flatten(m), 2, 3) == m

    # -- deep_copy independence
    orig = [[1.0, 2.0]]
    cp = deep_copy(orig)
    cp[0][0] = 99.0
    assert orig[0][0] == 1.0, "deep_copy not independent"

    print("All matrix.py unit tests passed ✓")
