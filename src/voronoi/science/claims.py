"""Claim Ledger — durable cross-run scientific state.

The Claim Ledger is the spine of iterative science in Voronoi.  It tracks
assertions (claims) with provenance tags across multiple runs of the same
investigation lineage, enabling human-in-the-loop iteration: lock what's
solid, challenge what's doubtful, carry results forward.

Storage: ``~/.voronoi/ledgers/<lineage_id>/claim-ledger.json``

Key concepts:
  - **Claim**: A paper-level assertion with provenance and artifact chain.
  - **Objection**: A structured doubt targeting a specific claim.
  - **ClaimArtifact**: A file in the workspace that supports a claim.
  - **Lineage**: A chain of investigations linked by ``parent_id``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("voronoi.science.claims")


# ---------------------------------------------------------------------------
# Provenance & status constants
# ---------------------------------------------------------------------------

PROVENANCE_MODEL_PRIOR = "model_prior"
PROVENANCE_RETRIEVED_PRIOR = "retrieved_prior"
PROVENANCE_RUN_EVIDENCE = "run_evidence"
VALID_PROVENANCES = {PROVENANCE_MODEL_PRIOR, PROVENANCE_RETRIEVED_PRIOR, PROVENANCE_RUN_EVIDENCE}

STATUS_PROVISIONAL = "provisional"
STATUS_ASSERTED = "asserted"
STATUS_LOCKED = "locked"
STATUS_CHALLENGED = "challenged"
STATUS_REPLICATED = "replicated"
STATUS_RETIRED = "retired"
VALID_STATUSES = {
    STATUS_PROVISIONAL, STATUS_ASSERTED, STATUS_LOCKED,
    STATUS_CHALLENGED, STATUS_REPLICATED, STATUS_RETIRED,
}

# Valid status transitions (from → set of allowed targets)
_TRANSITIONS: dict[str, set[str]] = {
    STATUS_PROVISIONAL: {STATUS_ASSERTED, STATUS_CHALLENGED, STATUS_RETIRED},
    STATUS_ASSERTED:    {STATUS_LOCKED, STATUS_CHALLENGED, STATUS_RETIRED},
    STATUS_LOCKED:      {STATUS_CHALLENGED, STATUS_REPLICATED, STATUS_RETIRED},
    STATUS_CHALLENGED:  {STATUS_ASSERTED, STATUS_LOCKED, STATUS_RETIRED},
    STATUS_REPLICATED:  {STATUS_RETIRED},
    STATUS_RETIRED:     set(),  # terminal
}

OBJECTION_TYPES = {"confound", "power", "methodology", "interpretation", "scope", "other"}
OBJECTION_STATUSES = {"pending", "investigating", "resolved", "dismissed", "surfaced"}
ARTIFACT_TYPES = {"data", "code", "result", "figure", "model"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ClaimArtifact:
    """A workspace file that supports a claim."""
    path: str                         # Relative path in workspace
    artifact_type: str                # data | code | result | figure | model
    sha256: Optional[str] = None      # Hash at time of assertion
    git_tag: Optional[str] = None     # Git ref where committed
    description: str = ""

    def __post_init__(self) -> None:
        if self.artifact_type not in ARTIFACT_TYPES:
            raise ValueError(f"Invalid artifact_type: {self.artifact_type!r}")


@dataclass
class Objection:
    """A structured doubt targeting a specific claim."""
    id: str
    target_claim: str
    concern: str
    objection_type: str = "other"     # confound | power | methodology | ...
    raised_by: str = "PI"             # PI | self_critique | critic_agent
    status: str = "pending"           # pending | investigating | resolved | dismissed | surfaced
    resolution: Optional[str] = None
    resolution_cycle: Optional[int] = None
    timestamp: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if self.objection_type not in OBJECTION_TYPES:
            raise ValueError(f"Invalid objection_type: {self.objection_type!r}")
        if self.status not in OBJECTION_STATUSES:
            raise ValueError(f"Invalid objection status: {self.status!r}")


@dataclass
class Claim:
    """A paper-level assertion with provenance and evidence chain."""
    id: str
    statement: str
    provenance: str                   # model_prior | retrieved_prior | run_evidence
    status: str = STATUS_PROVISIONAL

    # Evidence chain
    supporting_findings: list[str] = field(default_factory=list)
    source_cycle: int = 1

    # Quantitative summary
    effect_summary: Optional[str] = None
    sample_summary: Optional[str] = None

    # Provenance detail
    literature_refs: list[str] = field(default_factory=list)
    model_basis: Optional[str] = None

    # Artifact chain
    artifacts: list[ClaimArtifact] = field(default_factory=list)

    # Challenges
    challenges: list[Objection] = field(default_factory=list)

    # Timestamps
    first_asserted: str = field(default_factory=_now_iso)
    last_updated: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if self.provenance not in VALID_PROVENANCES:
            raise ValueError(f"Invalid provenance: {self.provenance!r}")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {self.status!r}")


# ---------------------------------------------------------------------------
# ClaimLedger — the cross-run scientific state
# ---------------------------------------------------------------------------

class ClaimLedger:
    """In-memory claim ledger with CRUD operations.

    Use ``load_ledger`` / ``save_ledger`` for persistence.
    """

    def __init__(self) -> None:
        self.claims: list[Claim] = []
        self.objections: list[Objection] = []
        self._next_claim_id: int = 1
        self._next_objection_id: int = 1

    # -- Claim CRUD --------------------------------------------------------

    def add_claim(
        self,
        statement: str,
        provenance: str,
        *,
        source_cycle: int = 1,
        supporting_findings: list[str] | None = None,
        effect_summary: str | None = None,
        sample_summary: str | None = None,
        literature_refs: list[str] | None = None,
        model_basis: str | None = None,
        artifacts: list[ClaimArtifact] | None = None,
    ) -> Claim:
        """Add a new claim to the ledger. Returns the created Claim."""
        claim = Claim(
            id=f"C{self._next_claim_id}",
            statement=statement,
            provenance=provenance,
            source_cycle=source_cycle,
            supporting_findings=supporting_findings or [],
            effect_summary=effect_summary,
            sample_summary=sample_summary,
            literature_refs=literature_refs or [],
            model_basis=model_basis,
            artifacts=artifacts or [],
        )
        self._next_claim_id += 1
        self.claims.append(claim)
        return claim

    def get_claim(self, claim_id: str) -> Claim | None:
        """Get a claim by ID."""
        for c in self.claims:
            if c.id == claim_id:
                return c
        return None

    def _transition_claim(self, claim_id: str, new_status: str) -> Claim:
        """Transition a claim to a new status, enforcing valid transitions."""
        claim = self.get_claim(claim_id)
        if claim is None:
            raise KeyError(f"Claim {claim_id} not found")
        allowed = _TRANSITIONS.get(claim.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition {claim_id} from {claim.status!r} to {new_status!r}. "
                f"Allowed: {allowed}"
            )
        claim.status = new_status
        claim.last_updated = _now_iso()
        return claim

    def lock_claim(self, claim_id: str) -> Claim:
        """Lock a claim — marks it as established, won't be re-tested."""
        return self._transition_claim(claim_id, STATUS_LOCKED)

    def challenge_claim(self, claim_id: str, concern: str,
                        objection_type: str = "other",
                        raised_by: str = "PI") -> tuple[Claim, Objection]:
        """Challenge a claim — creates an objection and transitions status."""
        claim = self._transition_claim(claim_id, STATUS_CHALLENGED)
        objection = self.add_objection(
            target_claim=claim_id,
            concern=concern,
            objection_type=objection_type,
            raised_by=raised_by,
        )
        claim.challenges.append(objection)
        return claim, objection

    def retire_claim(self, claim_id: str) -> Claim:
        """Retire a claim — superseded or refuted."""
        return self._transition_claim(claim_id, STATUS_RETIRED)

    def assert_claim(self, claim_id: str) -> Claim:
        """Promote a provisional or challenged claim to asserted."""
        return self._transition_claim(claim_id, STATUS_ASSERTED)

    def replicate_claim(self, claim_id: str) -> Claim:
        """Mark a locked claim as replicated by independent evidence."""
        return self._transition_claim(claim_id, STATUS_REPLICATED)

    # -- Objection CRUD ----------------------------------------------------

    def add_objection(
        self,
        target_claim: str,
        concern: str,
        objection_type: str = "other",
        raised_by: str = "PI",
    ) -> Objection:
        """Add a new objection targeting a claim."""
        obj = Objection(
            id=f"O{self._next_objection_id}",
            target_claim=target_claim,
            concern=concern,
            objection_type=objection_type,
            raised_by=raised_by,
        )
        self._next_objection_id += 1
        self.objections.append(obj)
        return obj

    def resolve_objection(self, objection_id: str, resolution: str,
                          resolution_cycle: int | None = None) -> Objection:
        """Resolve an objection."""
        for obj in self.objections:
            if obj.id == objection_id:
                obj.status = "resolved"
                obj.resolution = resolution
                obj.resolution_cycle = resolution_cycle
                return obj
        raise KeyError(f"Objection {objection_id} not found")

    def dismiss_objection(self, objection_id: str, reason: str) -> Objection:
        """Dismiss an objection as not applicable."""
        for obj in self.objections:
            if obj.id == objection_id:
                obj.status = "dismissed"
                obj.resolution = reason
                return obj
        raise KeyError(f"Objection {objection_id} not found")

    # -- Queries -----------------------------------------------------------

    def get_locked(self) -> list[Claim]:
        """Get all locked claims."""
        return [c for c in self.claims if c.status == STATUS_LOCKED]

    def get_challenged(self) -> list[Claim]:
        """Get all challenged claims."""
        return [c for c in self.claims if c.status == STATUS_CHALLENGED]

    def get_pending_objections(self) -> list[Objection]:
        """Get all unresolved objections."""
        return [o for o in self.objections
                if o.status in ("pending", "investigating", "surfaced")]

    def get_by_provenance(self, provenance: str) -> list[Claim]:
        """Get claims by provenance type."""
        return [c for c in self.claims if c.provenance == provenance]

    def get_immutable_paths(self) -> list[str]:
        """Get all artifact paths from locked/replicated claims."""
        paths: list[str] = []
        for claim in self.claims:
            if claim.status in (STATUS_LOCKED, STATUS_REPLICATED):
                for artifact in claim.artifacts:
                    if artifact.path not in paths:
                        paths.append(artifact.path)
        return paths

    # -- Summary -----------------------------------------------------------

    def summary(self) -> str:
        """Human-readable summary of the ledger state."""
        if not self.claims:
            return "No claims yet."

        lines: list[str] = []
        status_counts: dict[str, int] = {}
        for c in self.claims:
            status_counts[c.status] = status_counts.get(c.status, 0) + 1

        lines.append(f"Claims: {len(self.claims)} total — " +
                      ", ".join(f"{v} {k}" for k, v in sorted(status_counts.items())))

        pending = self.get_pending_objections()
        if pending:
            lines.append(f"Objections: {len(pending)} pending")

        return "\n".join(lines)

    def format_for_prompt(self) -> str:
        """Format the ledger for inclusion in an orchestrator prompt (~500-1000 tokens)."""
        if not self.claims:
            return ""

        sections: list[str] = []

        locked = [c for c in self.claims if c.status in (STATUS_LOCKED, STATUS_REPLICATED)]
        if locked:
            sections.append("### Established (locked by PI — do NOT re-test)")
            for c in locked:
                badge = "✓✓" if c.status == STATUS_REPLICATED else "✓"
                ev = f" ({c.effect_summary})" if c.effect_summary else ""
                sections.append(f"- [{badge}] {c.id}: {c.statement}{ev} [{c.provenance}]")

        challenged = self.get_challenged()
        if challenged:
            sections.append("\n### Under Challenge (MUST address)")
            for c in challenged:
                concerns = "; ".join(o.concern for o in c.challenges if o.status in ("pending", "investigating"))
                sections.append(f"- {c.id}: {c.statement} — Concerns: {concerns}")

        provisional = [c for c in self.claims if c.status in (STATUS_PROVISIONAL, STATUS_ASSERTED)]
        if provisional:
            sections.append("\n### Active (may be re-examined)")
            for c in provisional:
                ev = f" ({c.effect_summary})" if c.effect_summary else ""
                sections.append(f"- {c.id}: {c.statement}{ev} [{c.provenance}]")

        model_priors = [c for c in self.claims
                        if c.provenance == PROVENANCE_MODEL_PRIOR
                        and c.status not in (STATUS_RETIRED,)]
        if model_priors:
            sections.append("\n### Model Priors (NOT verified — flag if conclusions depend on these)")
            for c in model_priors:
                sections.append(f"- ⚠️ {c.id}: {c.statement}")

        pending_obj = self.get_pending_objections()
        if pending_obj:
            sections.append("\n### Pending Objections")
            for o in pending_obj:
                sections.append(f"- {o.id} → {o.target_claim}: {o.concern} [{o.objection_type}]")

        retired = [c for c in self.claims if c.status == STATUS_RETIRED]
        if retired:
            sections.append(f"\n### Retired: {len(retired)} claims (superseded/refuted)")

        return "\n".join(sections)

    def format_for_review(self) -> str:
        """Format the ledger for Telegram review display."""
        if not self.claims:
            return "No claims to review."

        lines: list[str] = []
        for i, c in enumerate(self.claims, 1):
            if c.status == STATUS_RETIRED:
                continue  # skip retired in review
            badge = {
                STATUS_LOCKED: "🔒",
                STATUS_REPLICATED: "🔒🔒",
                STATUS_CHALLENGED: "⚡",
                STATUS_PROVISIONAL: "❓",
                STATUS_ASSERTED: "✅",
            }.get(c.status, "•")
            ev = f" ({c.effect_summary})" if c.effect_summary else ""
            prov_badge = {"model_prior": "⚠️ model", "retrieved_prior": "📚 lit",
                          "run_evidence": "🔬 evidence"}.get(c.provenance, c.provenance)
            lines.append(f"{badge} *{c.id}*: {c.statement}{ev}")
            lines.append(f"   Source: {prov_badge} | Cycle {c.source_cycle}")
            if c.supporting_findings:
                lines.append(f"   Evidence: {', '.join(c.supporting_findings[:5])}")
            if c.challenges:
                active = [ch for ch in c.challenges if ch.status in ("pending", "investigating")]
                if active:
                    lines.append(f"   ⚠️ {len(active)} active concern(s)")
            lines.append("")

        pending = self.get_pending_objections()
        if pending:
            lines.append("*Pending objections:*")
            for o in pending:
                lines.append(f"  {o.id} → {o.target_claim}: {o.concern}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Self-critique generation
# ---------------------------------------------------------------------------

def generate_self_critique(ledger: ClaimLedger) -> list[Objection]:
    """Generate self-critique objections for weak claims.

    Checks for common weaknesses: low sample size, single-trial evidence,
    unverified model priors, missing sensitivity analysis.
    Returns objections with raised_by='self_critique' and status='surfaced'.
    """
    objections: list[Objection] = []

    for claim in ledger.claims:
        if claim.status == STATUS_RETIRED:
            continue

        # Skip already-challenged claims
        active_challenges = [ch for ch in claim.challenges
                             if ch.status in ("pending", "investigating", "surfaced")]
        if active_challenges:
            continue

        # Single finding support
        if (claim.provenance == PROVENANCE_RUN_EVIDENCE
                and len(claim.supporting_findings) == 1
                and claim.status != STATUS_REPLICATED):
            obj = Objection(
                id=f"SC{ledger._next_objection_id}",
                target_claim=claim.id,
                concern="Based on single experiment — independent replication recommended",
                objection_type="power",
                raised_by="self_critique",
                status="surfaced",
            )
            ledger._next_objection_id += 1
            objections.append(obj)

        # Model prior never verified
        if claim.provenance == PROVENANCE_MODEL_PRIOR and claim.status != STATUS_RETIRED:
            obj = Objection(
                id=f"SC{ledger._next_objection_id}",
                target_claim=claim.id,
                concern="Based on model training data — not independently verified in this investigation",
                objection_type="methodology",
                raised_by="self_critique",
                status="surfaced",
            )
            ledger._next_objection_id += 1
            objections.append(obj)

        # Low sample indication in summary
        if claim.sample_summary:
            try:
                # Try to extract N from summary like "N=50" or "N=50 across 3 experiments"
                import re
                match = re.search(r"N\s*=\s*(\d+)", claim.sample_summary)
                if match and int(match.group(1)) < 100:
                    obj = Objection(
                        id=f"SC{ledger._next_objection_id}",
                        target_claim=claim.id,
                        concern=f"Sample size ({claim.sample_summary}) may be underpowered",
                        objection_type="power",
                        raised_by="self_critique",
                        status="surfaced",
                    )
                    ledger._next_objection_id += 1
                    objections.append(obj)
            except (ValueError, AttributeError):
                pass

    return objections


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _claim_to_dict(claim: Claim) -> dict:
    """Convert a Claim to a JSON-safe dict."""
    d = asdict(claim)
    # asdict handles nested dataclasses
    return d


def _known_fields(cls: type) -> set[str]:
    """Return the set of field names for a dataclass (for forward-compat filtering)."""
    from dataclasses import fields as _fields
    return {f.name for f in _fields(cls)}


def _filter_keys(d: dict, cls: type) -> dict:
    """Return *d* with only the keys that *cls* accepts."""
    allowed = _known_fields(cls)
    return {k: v for k, v in d.items() if k in allowed}


def _dict_to_claim(d: dict) -> Claim:
    """Reconstruct a Claim from a dict.

    Unknown keys (from future schema versions) are silently dropped so that
    older code can still load newer ledger files without crashing.
    """
    # Reconstruct nested dataclasses (filter unknown keys there too)
    d["artifacts"] = [ClaimArtifact(**_filter_keys(a, ClaimArtifact)) if isinstance(a, dict) else a
                      for a in d.get("artifacts", [])]
    d["challenges"] = [Objection(**_filter_keys(o, Objection)) if isinstance(o, dict) else o
                       for o in d.get("challenges", [])]
    return Claim(**_filter_keys(d, Claim))


def _dict_to_objection(d: dict) -> Objection:
    """Reconstruct an Objection from a dict.

    Unknown keys are silently dropped for forward-compatibility.
    """
    return Objection(**_filter_keys(d, Objection))


def _ledger_to_dict(ledger: ClaimLedger) -> dict:
    """Serialize the ledger to a JSON-safe dict."""
    return {
        "claims": [_claim_to_dict(c) for c in ledger.claims],
        "objections": [asdict(o) for o in ledger.objections],
        "_next_claim_id": ledger._next_claim_id,
        "_next_objection_id": ledger._next_objection_id,
    }


def _dict_to_ledger(d: dict) -> ClaimLedger:
    """Reconstruct a ClaimLedger from a dict."""
    ledger = ClaimLedger()
    ledger.claims = [_dict_to_claim(c) for c in d.get("claims", [])]
    ledger.objections = [_dict_to_objection(o) for o in d.get("objections", [])]
    ledger._next_claim_id = d.get("_next_claim_id", len(ledger.claims) + 1)
    ledger._next_objection_id = d.get("_next_objection_id", len(ledger.objections) + 1)
    return ledger


# ---------------------------------------------------------------------------
# Persistence — JSON file at ~/.voronoi/ledgers/<lineage_id>/
# ---------------------------------------------------------------------------

def _ledger_dir(lineage_id: int, base_dir: Path | None = None) -> Path:
    """Return the directory for a lineage's claim ledger."""
    base = base_dir or (Path.home() / ".voronoi")
    return base / "ledgers" / str(lineage_id)


def _ledger_path(lineage_id: int, base_dir: Path | None = None) -> Path:
    return _ledger_dir(lineage_id, base_dir) / "claim-ledger.json"


def load_ledger(lineage_id: int, base_dir: Path | None = None) -> ClaimLedger:
    """Load the claim ledger for a lineage. Returns empty if not found."""
    path = _ledger_path(lineage_id, base_dir)
    if not path.exists():
        return ClaimLedger()
    try:
        data = json.loads(path.read_text())
        return _dict_to_ledger(data)
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        logger.warning("Failed to load claim ledger at %s: %s", path, e)
        return ClaimLedger()


def save_ledger(lineage_id: int, ledger: ClaimLedger,
                base_dir: Path | None = None) -> Path:
    """Save the claim ledger for a lineage. Returns the written path."""
    path = _ledger_path(lineage_id, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _ledger_to_dict(ledger)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def resolve_lineage_id(investigation_id: int, get_fn) -> int:
    """Walk the parent_id chain to find the root investigation.

    ``get_fn`` is a callable that takes an investigation ID and returns
    an object with ``parent_id`` and ``id`` attributes (or None).
    Typically ``queue.get``.
    """
    current_id = investigation_id
    visited: set[int] = set()
    while True:
        if current_id in visited:
            break  # cycle guard
        visited.add(current_id)
        inv = get_fn(current_id)
        if inv is None or inv.parent_id is None:
            return current_id
        current_id = inv.parent_id
    return current_id
