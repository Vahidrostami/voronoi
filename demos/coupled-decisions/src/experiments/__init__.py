"""Experiment modules for the coupled-decisions framework.

Experiments
----------
experiment_1_encoding      : Encoding layer validation (fidelity, cross-type queries, conflicts).
experiment_2_ablation      : 4-way ablation study.
experiment_3_pipeline      : Progressive reduction measurement.
experiment_4_generalization: Cross-domain generalization (medicine + supply chain).
run_all                    : Master runner — generates data, runs all 4, writes results.json.
"""

from .experiment_1_encoding import run_experiment_1
from .experiment_2_ablation import run_experiment_2
from .experiment_3_pipeline import run_experiment_3
from .experiment_4_generalization import run_experiment_4
from .run_all import run_all_experiments

__all__ = [
    "run_experiment_1",
    "run_experiment_2",
    "run_experiment_3",
    "run_experiment_4",
    "run_all_experiments",
]
