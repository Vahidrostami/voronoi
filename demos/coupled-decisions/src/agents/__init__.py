"""Diagnostic agents for the coupled-decisions framework.

Each agent implements the DiagnosticAgent interface:
  * ``__init__(config, encoded_knowledge)``
  * ``diagnose() -> list[EvidencePacket]``
  * ``get_pruned_space() -> dict``

Agents:
  * ElasticityAgent — own/cross-price elasticity analysis
  * InteractionAgent — lever-pair interaction detection
  * ConstraintAgent — feasible region mapping
  * TemporalAgent — trend, seasonality, structural-break analysis
  * PortfolioAgent — SKU-level portfolio effects
"""

from .elasticity_agent import ElasticityAgent
from .interaction_agent import InteractionAgent
from .constraint_agent import ConstraintAgent
from .temporal_agent import TemporalAgent
from .portfolio_agent import PortfolioAgent

__all__ = [
    "ElasticityAgent",
    "InteractionAgent",
    "ConstraintAgent",
    "TemporalAgent",
    "PortfolioAgent",
]
