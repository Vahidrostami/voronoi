"""MNIST IDX format loader — uses struct/gzip, returns plain Python lists.

Downloads from http://yann.lecun.com/exdb/mnist/ on first call,
caches under ``data/`` next to this file.
Splits the 10 digits into 5 binary tasks: (0,1), (2,3), (4,5), (6,7), (8,9).
Pixel values are normalised to [0, 1].
"""

from __future__ import annotations

import gzip
import os
import struct
import urllib.request
from typing import Dict, List, Tuple

_BASE_URL = "http://yann.lecun.com/exdb/mnist/"
_FILES = {
    "train_images": "train-images-idx3-ubyte.gz",
    "train_labels": "train-labels-idx1-ubyte.gz",
    "test_images": "t10k-images-idx3-ubyte.gz",
    "test_labels": "t10k-labels-idx1-ubyte.gz",
}

# Default cache dir lives alongside the source tree
_DEFAULT_CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "mnist")


# ------------------------------------------------------------------
# Low-level IDX parsing
# ------------------------------------------------------------------

def _download(filename: str, cache_dir: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, filename)
    if not os.path.exists(path):
        url = _BASE_URL + filename
        print(f"Downloading {url} …")
        urllib.request.urlretrieve(url, path)
    return path


def _parse_idx_images(path: str) -> List[List[float]]:
    """Parse IDX3 image file → list of flattened 784-float vectors in [0,1]."""
    with gzip.open(path, "rb") as f:
        magic, num, rows, cols = struct.unpack(">IIII", f.read(16))
        assert magic == 2051, f"Bad magic {magic}"
        pixels = rows * cols  # 784
        images: List[List[float]] = []
        for _ in range(num):
            raw = struct.unpack(f">{pixels}B", f.read(pixels))
            images.append([p / 255.0 for p in raw])
    return images


def _parse_idx_labels(path: str) -> List[int]:
    """Parse IDX1 label file → list of ints."""
    with gzip.open(path, "rb") as f:
        magic, num = struct.unpack(">II", f.read(8))
        assert magic == 2049, f"Bad magic {magic}"
        labels = list(struct.unpack(f">{num}B", f.read(num)))
    return labels


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def load_mnist(cache_dir: str = _DEFAULT_CACHE) -> Tuple[
    List[List[float]], List[int], List[List[float]], List[int]
]:
    """Load full MNIST and return (train_images, train_labels, test_images, test_labels).

    Each image is a 784-element list of floats in [0, 1].
    Labels are plain ints 0-9.
    """
    paths = {key: _download(fname, cache_dir) for key, fname in _FILES.items()}
    train_images = _parse_idx_images(paths["train_images"])
    train_labels = _parse_idx_labels(paths["train_labels"])
    test_images = _parse_idx_images(paths["test_images"])
    test_labels = _parse_idx_labels(paths["test_labels"])
    return train_images, train_labels, test_images, test_labels


def split_by_task(
    images: List[List[float]],
    labels: List[int],
    digit_a: int,
    digit_b: int,
) -> Tuple[List[List[float]], List[int]]:
    """Filter images/labels to only *digit_a* and *digit_b*.

    Re-maps labels to 0 / 1 (digit_a → 0, digit_b → 1).
    """
    out_images: List[List[float]] = []
    out_labels: List[int] = []
    for img, lbl in zip(images, labels):
        if lbl == digit_a:
            out_images.append(img)
            out_labels.append(0)
        elif lbl == digit_b:
            out_images.append(img)
            out_labels.append(1)
    return out_images, out_labels


TaskData = Tuple[List[List[float]], List[int], List[List[float]], List[int]]


def make_tasks(
    cache_dir: str = _DEFAULT_CACHE,
    task_pairs: List[Tuple[int, int]] | None = None,
) -> Dict[int, TaskData]:
    """Build the 5 continual-learning tasks.

    Returns:
        {task_idx: (train_images, train_labels, test_images, test_labels)}
        Labels are 0 or 1 (binary per task).
    """
    if task_pairs is None:
        task_pairs = [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9)]

    train_imgs, train_lbls, test_imgs, test_lbls = load_mnist(cache_dir)

    tasks: Dict[int, TaskData] = {}
    for idx, (da, db) in enumerate(task_pairs):
        tr_i, tr_l = split_by_task(train_imgs, train_lbls, da, db)
        te_i, te_l = split_by_task(test_imgs, test_lbls, da, db)
        tasks[idx] = (tr_i, tr_l, te_i, te_l)
    return tasks
