"""Shared utilities — data loading, JSON I/O, logging, seed management."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union

import numpy as np


# ---------------------------------------------------------------------------
# Random seed management
# ---------------------------------------------------------------------------

_RNG: Optional[np.random.Generator] = None


def set_seed(seed: int = 42) -> np.random.Generator:
    """Set the global random seed and return a numpy Generator.

    All framework code should use :func:`get_rng` instead of creating
    its own Generator so that experiments are deterministic.
    """
    global _RNG
    _RNG = np.random.default_rng(seed)
    return _RNG


def get_rng() -> np.random.Generator:
    """Return the global numpy Generator, initialising with default seed if needed."""
    global _RNG
    if _RNG is None:
        _RNG = np.random.default_rng(42)
    return _RNG


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOGGERS: Dict[str, logging.Logger] = {}


def get_logger(name: str = "coupled_decisions", level: int = logging.INFO) -> logging.Logger:
    """Return a named logger with a stream handler.

    Re-uses existing loggers to avoid duplicate handlers.
    """
    if name in _LOGGERS:
        return _LOGGERS[name]
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("[%(asctime)s %(name)s %(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(handler)
    logger.setLevel(level)
    _LOGGERS[name] = logger
    return logger


# ---------------------------------------------------------------------------
# JSON I/O
# ---------------------------------------------------------------------------

class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def load_json(path: Union[str, Path]) -> Any:
    """Load and parse a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Any, path: Union[str, Path], *, indent: int = 2) -> Path:
    """Write *data* as JSON to *path*, creating parent dirs if needed.

    Returns the resolved path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, cls=_NumpyEncoder)
    return path


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def load_csv(path: Union[str, Path], **kwargs: Any) -> "np.ndarray":
    """Load a CSV file into a numpy structured array.

    Uses numpy.genfromtxt with sane defaults for the BevCo data format.
    Extra *kwargs* are forwarded to genfromtxt.
    """
    defaults = dict(
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )
    defaults.update(kwargs)
    return np.genfromtxt(str(path), **defaults)


def project_root() -> Path:
    """Return the root of the coupled-decisions demo directory.

    Walks up from this file until it finds the ``demos/coupled-decisions``
    directory.
    """
    p = Path(__file__).resolve()
    while p != p.parent:
        candidate = p / "demos" / "coupled-decisions"
        if candidate.is_dir():
            return candidate
        p = p.parent
    # Fallback: assume we're inside src/core/
    return Path(__file__).resolve().parent.parent.parent


def data_dir() -> Path:
    """Return the data/ directory path."""
    return project_root() / "data"


def output_dir() -> Path:
    """Return the output/ directory path, creating it if needed."""
    d = project_root() / "output"
    d.mkdir(parents=True, exist_ok=True)
    return d
