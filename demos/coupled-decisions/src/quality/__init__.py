"""Quality gate — multi-dimensional scoring and filtering of interventions.

Scores each candidate intervention on 5 dimensions and filters to top-K.
"""

from .gate import QualityGate

__all__ = ["QualityGate"]
