"""Belief map — hypothesis tracking and information-gain prioritization."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("voronoi.science")


@dataclass
class Hypothesis:
    """A single hypothesis in the belief map."""
    id: str
    name: str
    prior: float
    posterior: float
    status: str = "untested"  # untested, testing, confirmed, refuted, inconclusive
    evidence: list[str] = field(default_factory=list)
    testability: float = 0.5
    impact: float = 0.5

    @property
    def uncertainty(self) -> float:
        """Uncertainty is highest at P=0.5, zero at P=0 or P=1."""
        return 1.0 - abs(self.posterior - 0.5) * 2

    @property
    def information_gain(self) -> float:
        """Priority score: uncertainty * impact * testability."""
        return self.uncertainty * self.impact * self.testability


@dataclass
class BeliefMap:
    """Tracks hypothesis probabilities across an investigation."""
    hypotheses: list[Hypothesis] = field(default_factory=list)
    cycle: int = 0
    last_updated: str = ""

    def add_hypothesis(self, h: Hypothesis) -> None:
        self.hypotheses.append(h)

    def update_hypothesis(self, h_id: str, posterior: float,
                          status: str, evidence_id: str = "") -> bool:
        """Update a hypothesis with new evidence. Returns True if found."""
        for h in self.hypotheses:
            if h.id == h_id:
                h.posterior = max(0.0, min(1.0, posterior))
                h.status = status
                if evidence_id:
                    h.evidence.append(evidence_id)
                return True
        return False

    def get_priority_order(self) -> list[Hypothesis]:
        """Return hypotheses sorted by information gain (highest first)."""
        untested = [h for h in self.hypotheses if h.status in ("untested", "testing")]
        return sorted(untested, key=lambda h: h.information_gain, reverse=True)

    def all_resolved(self) -> bool:
        """True if every hypothesis has been resolved (not untested/testing)."""
        return all(h.status not in ("untested", "testing") for h in self.hypotheses)

    def summary(self) -> dict:
        """Compact summary for logging."""
        by_status: dict[str, int] = {}
        for h in self.hypotheses:
            by_status[h.status] = by_status.get(h.status, 0) + 1
        return {
            "total": len(self.hypotheses),
            "by_status": by_status,
            "cycle": self.cycle,
        }


def load_belief_map(workspace: Path) -> BeliefMap:
    """Load belief map from .swarm/belief-map.json."""
    path = workspace / ".swarm" / "belief-map.json"
    if not path.exists():
        return BeliefMap()
    try:
        data = json.loads(path.read_text())
        bm = BeliefMap(
            cycle=data.get("cycle", 0),
            last_updated=data.get("last_updated", ""),
        )
        for h_data in data.get("hypotheses", []):
            bm.hypotheses.append(Hypothesis(
                id=h_data.get("id", ""),
                name=h_data.get("name", ""),
                prior=h_data.get("prior", 0.5),
                posterior=h_data.get("posterior", h_data.get("prior", 0.5)),
                status=h_data.get("status", "untested"),
                evidence=h_data.get("evidence", []),
                testability=h_data.get("testability", 0.5),
                impact=h_data.get("impact", 0.5),
            ))
        return bm
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load belief map: %s", e)
        return BeliefMap()


def save_belief_map(workspace: Path, bm: BeliefMap) -> None:
    """Save belief map to .swarm/belief-map.json."""
    path = workspace / ".swarm" / "belief-map.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    bm.last_updated = datetime.now(timezone.utc).isoformat()
    data = {
        "cycle": bm.cycle,
        "last_updated": bm.last_updated,
        "hypotheses": [asdict(h) for h in bm.hypotheses],
    }
    path.write_text(json.dumps(data, indent=2))
