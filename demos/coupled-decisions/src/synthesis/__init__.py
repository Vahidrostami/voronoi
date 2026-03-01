"""Causal synthesis layer — assembles diagnostic evidence into interventions.

Takes evidence packets from all 5 diagnostic agents, groups by lever+direction,
identifies causal chains, and produces ranked Intervention objects.
"""

from .assembler import CausalAssembler

__all__ = ["CausalAssembler"]
