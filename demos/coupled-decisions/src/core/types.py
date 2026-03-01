"""Core type definitions for the coupled-decisions framework.

All types are dataclasses with JSON-serializable representations.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LeverName(str, Enum):
    """The five RGM commercial levers."""
    PRICING = "pricing"
    PROMOTION = "promotion"
    ASSORTMENT = "assortment"
    DISTRIBUTION = "distribution"
    PACK_PRICE = "pack_price"


class KnowledgeType(str, Enum):
    """Categories of knowledge sources."""
    QUANTITATIVE = "quantitative"
    POLICY = "policy"
    EXPERT = "expert"


class ConstraintHardness(str, Enum):
    """Whether a policy constraint is hard (must) or soft (should)."""
    HARD = "hard"
    SOFT = "soft"


class ExpertBasis(str, Enum):
    """Basis quality ranking for expert beliefs."""
    ANALYSIS = "analysis"
    EXPERIENCE = "experience"
    INTUITION = "intuition"


class Direction(str, Enum):
    """Direction of change for a lever."""
    INCREASE = "increase"
    DECREASE = "decrease"
    MAINTAIN = "maintain"


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Lever:
    """A decision lever in the coupled space.

    Attributes:
        name: Canonical lever name.
        variables: Description of variables controlled by this lever.
        range_min: Lower bound of the lever range.
        range_max: Upper bound of the lever range.
        coupled_with: Names of levers this is coupled with.
        metadata: Arbitrary extra info.
    """
    name: LeverName
    variables: str = ""
    range_min: float = 0.0
    range_max: float = 1.0
    coupled_with: List[LeverName] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["name"] = self.name.value
        d["coupled_with"] = [lv.value for lv in self.coupled_with]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Lever":
        d = dict(d)
        d["name"] = LeverName(d["name"])
        d["coupled_with"] = [LeverName(v) for v in d.get("coupled_with", [])]
        return cls(**d)


@dataclass
class KnowledgeSource:
    """A single knowledge source with its type and origin.

    Attributes:
        source_id: Unique identifier.
        kind: The knowledge type (quantitative / policy / expert).
        description: Human-readable description.
        data: Raw payload (dict, list, or path to file).
        metadata: Extra info (e.g., date, origin, quality).
    """
    source_id: str
    kind: KnowledgeType
    description: str = ""
    data: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "KnowledgeSource":
        d = dict(d)
        d["kind"] = KnowledgeType(d["kind"])
        return cls(**d)


@dataclass
class StatisticalProfile:
    """Encoded representation of quantitative data.

    Captures distribution parameters, confidence intervals,
    trend/seasonality decomposition, and structural breaks.
    """
    mean: float = 0.0
    std: float = 0.0
    skew: float = 0.0
    kurtosis: float = 0.0
    ci_lower: float = 0.0
    ci_upper: float = 0.0
    ci_level: float = 0.95
    trend: List[float] = field(default_factory=list)
    seasonality: List[float] = field(default_factory=list)
    residual: List[float] = field(default_factory=list)
    structural_breaks: List[int] = field(default_factory=list)
    n_observations: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StatisticalProfile":
        return cls(**d)


@dataclass
class ConstraintVector:
    """Encoded representation of a policy rule.

    Attributes:
        rule_id: Unique rule identifier.
        lever: Which lever the constraint applies to.
        direction: Constraint direction (e.g., >= threshold).
        bound: Numerical threshold value.
        hardness: Hard or soft constraint.
        scope: Scope of the constraint (category, region, etc.).
        interactions: Other levers affected by this constraint.
        rationale: Why the constraint exists.
        metadata: Extra info.
    """
    rule_id: str = ""
    lever: str = ""
    direction: str = ""
    bound: float = 0.0
    hardness: ConstraintHardness = ConstraintHardness.SOFT
    scope: Dict[str, Any] = field(default_factory=dict)
    interactions: List[str] = field(default_factory=list)
    rationale: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["hardness"] = self.hardness.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConstraintVector":
        d = dict(d)
        d["hardness"] = ConstraintHardness(d.get("hardness", "soft"))
        return cls(**d)


@dataclass
class TemporalBelief:
    """Encoded representation of an expert judgment.

    Includes confidence with temporal decay, basis quality,
    and lever-domain mapping.
    """
    statement: str = ""
    confidence: float = 0.5
    recency: str = ""  # ISO-8601 date string
    domain: List[str] = field(default_factory=list)
    basis: ExpertBasis = ExpertBasis.EXPERIENCE
    decay_rate: float = 0.05  # exponential decay per week
    current_confidence: float = 0.5
    lever_direction: Optional[str] = None
    lever_magnitude: Optional[float] = None
    conflicts_with_data: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["basis"] = self.basis.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TemporalBelief":
        d = dict(d)
        d["basis"] = ExpertBasis(d.get("basis", "experience"))
        return cls(**d)

    def decayed_confidence(self, weeks_elapsed: float) -> float:
        """Return confidence after exponential decay."""
        import math
        return self.confidence * math.exp(-self.decay_rate * weeks_elapsed)


@dataclass
class EvidencePacket:
    """A unit of evidence produced by a diagnostic agent.

    Attributes:
        agent_id: Which agent produced this evidence.
        lever: Primary lever this evidence concerns.
        related_levers: Other levers involved.
        direction: Suggested direction of change.
        magnitude: Estimated effect size.
        confidence: Agent's confidence in this evidence.
        mechanism: Causal mechanism description.
        source_types: Which knowledge types contributed.
        data: Supporting data payload.
        metadata: Extra info.
    """
    agent_id: str = ""
    lever: str = ""
    related_levers: List[str] = field(default_factory=list)
    direction: Direction = Direction.MAINTAIN
    magnitude: float = 0.0
    confidence: float = 0.0
    mechanism: str = ""
    source_types: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["direction"] = self.direction.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvidencePacket":
        d = dict(d)
        d["direction"] = Direction(d.get("direction", "maintain"))
        return cls(**d)


@dataclass
class QualityScore:
    """Multi-dimensional quality assessment of an intervention.

    Dimensions: evidence_density, constraint_alignment,
    actionability, testability, novelty.
    """
    evidence_density: float = 0.0
    constraint_alignment: float = 0.0
    actionability: float = 0.0
    testability: float = 0.0
    novelty: float = 0.0
    composite: float = 0.0
    hard_constraint_violation: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    # Default weights for composite score
    WEIGHTS: Dict[str, float] = field(default_factory=lambda: {
        "evidence_density": 0.25,
        "constraint_alignment": 0.25,
        "actionability": 0.20,
        "testability": 0.15,
        "novelty": 0.15,
    })

    def compute_composite(self, weights: Optional[Dict[str, float]] = None) -> float:
        """Compute weighted composite score. Vetoes on hard constraint violation."""
        if self.hard_constraint_violation:
            self.composite = 0.0
            return 0.0
        w = weights or self.WEIGHTS
        self.composite = (
            w.get("evidence_density", 0.25) * self.evidence_density
            + w.get("constraint_alignment", 0.25) * self.constraint_alignment
            + w.get("actionability", 0.20) * self.actionability
            + w.get("testability", 0.15) * self.testability
            + w.get("novelty", 0.15) * self.novelty
        )
        return self.composite

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "QualityScore":
        return cls(**d)


@dataclass
class Intervention:
    """A structured recommendation: lever + direction + scope + mechanism.

    Attributes:
        intervention_id: Unique identifier.
        lever: Primary lever to act on.
        direction: Direction of change.
        magnitude: Recommended change size.
        scope: Where to apply (categories, regions, SKUs).
        mechanism: Causal mechanism description.
        evidence_trail: List of EvidencePacket ids supporting this.
        confidence: Overall confidence.
        quality: Quality gate score.
        metadata: Extra info.
    """
    intervention_id: str = ""
    lever: str = ""
    direction: Direction = Direction.MAINTAIN
    magnitude: float = 0.0
    scope: Dict[str, Any] = field(default_factory=dict)
    mechanism: str = ""
    evidence_trail: List[str] = field(default_factory=list)
    confidence: float = 0.0
    quality: Optional[QualityScore] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["direction"] = self.direction.value
        if self.quality is not None:
            d["quality"] = self.quality.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Intervention":
        d = dict(d)
        d["direction"] = Direction(d.get("direction", "maintain"))
        if d.get("quality") and isinstance(d["quality"], dict):
            d["quality"] = QualityScore.from_dict(d["quality"])
        return cls(**d)


@dataclass
class ReasoningResult:
    """Result of cross-type reasoning across encoded knowledge sources.

    Attributes:
        query: The original query string.
        answer: Synthesized answer.
        confidence: Confidence in the answer.
        evidence: List of contributing evidence packets.
        conflicts: Detected cross-source conflicts.
        concordances: Detected cross-source agreements.
        metadata: Extra info.
    """
    query: str = ""
    answer: str = ""
    confidence: float = 0.0
    evidence: List[EvidencePacket] = field(default_factory=list)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    concordances: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "query": self.query,
            "answer": self.answer,
            "confidence": self.confidence,
            "evidence": [e.to_dict() for e in self.evidence],
            "conflicts": self.conflicts,
            "concordances": self.concordances,
            "metadata": self.metadata,
        }
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ReasoningResult":
        d = dict(d)
        d["evidence"] = [
            EvidencePacket.from_dict(e) for e in d.get("evidence", [])
        ]
        return cls(**d)
