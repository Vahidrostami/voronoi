"""Run Manifest — structured, machine-extractable summary of a completed run.

The manifest is a *derived* artifact: it is assembled from other ``.swarm/``
state at completion time and written to ``.swarm/run-manifest.json``.  It does
not duplicate authority — every field is either copied from or referenced to
the canonical source (claim-evidence.json, eval-score.json, belief-map.json,
convergence.json, Beads findings, the Claim Ledger).

Purpose (single-sentence):
    Give the PDF, the Claim Ledger, external graders, and `jq` a single
    canonical answer object for any converged run.

The manifest is additive — no existing ``.swarm/`` file is retired by it.
See ``docs/MANIFEST.md`` for the full schema reference.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from voronoi.science.claims import Claim, ClaimLedger
from voronoi.science.consistency import (
    ClaimEvidenceRegistry,
    load_claim_evidence,
)
from voronoi.science.convergence import (
    BeliefMap,
    load_belief_map,
)

logger = logging.getLogger("voronoi.science.manifest")

SCHEMA_VERSION = "1.0"
MANIFEST_FILENAME = "run-manifest.json"

# Rigor tiers that require increasingly complete manifests.  Tier names align
# with the existing rigor levels in ``science/convergence.py``.  "standard" is
# the lowest-effort build; "experimental" requires the richest manifest.
RIGOR_TIERS: tuple[str, ...] = (
    "standard", "adaptive", "analytical", "scientific", "experimental",
)


# ---------------------------------------------------------------------------
# Sub-structures
# ---------------------------------------------------------------------------

@dataclass
class ManifestArtifact:
    """A file in the workspace referenced by the manifest."""
    path: str                     # Relative to workspace root
    kind: str                     # paper | code | data | figure | model | submission | other
    sha256: Optional[str] = None
    bytes: Optional[int] = None
    description: str = ""


@dataclass
class PrimaryClaim:
    """A single structured assertion.  Mirrors ``Claim`` but richer for graders."""
    id: str = ""
    statement: str = ""
    # {"independent": [...], "dependent": [...], "moderators": [...]}
    variables: dict = field(default_factory=dict)
    relation: str = ""            # "X increases Y" / "no effect" / etc.
    direction: str = ""           # confirmed | refuted_reversed | inconclusive | not_tested
    effect_size: str = ""
    confidence_interval: str = ""
    p_value: str = ""
    sample_summary: str = ""
    status: str = "provisional"   # mirrors ClaimLedger status
    provenance: str = "run_evidence"
    supporting_findings: list[str] = field(default_factory=list)
    supporting_artifacts: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


@dataclass
class HypothesisOutcome:
    """An entry from the belief map, distilled to what external readers need."""
    id: str = ""
    statement: str = ""
    expected_direction: str = ""
    observed_direction: str = ""  # confirmed | refuted_reversed | inconclusive
    verdict: str = ""             # from tribunal when present
    confidence: str = ""          # unknown | hunch | supported | strong | resolved
    supporting_findings: list[str] = field(default_factory=list)


@dataclass
class ExperimentRecord:
    """One experiment / finding, flattened for external consumption."""
    id: str = ""
    method: str = ""              # finding title (cleaned)
    dataset: str = ""
    dataset_sha256: str = ""
    script: str = ""
    metric_name: str = ""
    baseline_value: str = ""
    treatment_value: str = ""
    effect_size: str = ""
    ci: str = ""
    p_value: str = ""
    n: str = ""
    stat_test: str = ""
    valence: str = ""             # positive | negative | inconclusive
    status: str = ""


@dataclass
class ProvenanceInfo:
    investigation_id: Optional[int] = None
    lineage_id: Optional[int] = None
    cycle_number: int = 1
    parent_id: Optional[int] = None
    codename: str = ""
    mode: str = ""
    rigor: str = ""
    git_commit: str = ""
    git_tag: str = ""
    workspace_path: str = ""
    started_at: str = ""
    completed_at: str = ""


@dataclass
class CostReport:
    wall_clock_seconds: float = 0.0
    total_tokens: int = 0
    total_usd: float = 0.0


@dataclass
class EvaluatorSummary:
    score: float = 0.0
    rounds: int = 0
    dimensions: dict = field(default_factory=dict)  # verbatim from eval-score.json
    remediations: list[str] = field(default_factory=list)


@dataclass
class ReviewerObjection:
    """An anticipated objection and its pre-answer.  Pattern 5 from scientist-UX."""
    objection: str = ""
    response: str = ""


@dataclass
class ValidationResult:
    valid: bool
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Root dataclass
# ---------------------------------------------------------------------------

@dataclass
class RunManifest:
    """Canonical structured record of a completed investigation run."""

    schema_version: str = SCHEMA_VERSION

    # --- Identity & framing --------------------------------------------------
    question: str = ""
    answer: str = ""                          # single-sentence scientific answer
    mode: str = ""                            # discover | prove | build
    rigor: str = ""                           # standard | adaptive | analytical | ...

    # --- Run status ---------------------------------------------------------
    status: str = "unknown"                   # converged | exhausted | diminishing_returns |
                                              # negative_result | failed | partial | unknown
    converged: bool = False
    reason: str = ""

    # --- Scientific content -------------------------------------------------
    primary_claims: list[PrimaryClaim] = field(default_factory=list)
    hypotheses: list[HypothesisOutcome] = field(default_factory=list)
    experiments: list[ExperimentRecord] = field(default_factory=list)
    artifacts: list[ManifestArtifact] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    reviewer_defense: list[ReviewerObjection] = field(default_factory=list)
    pending_objections: list[dict] = field(default_factory=list)
    continuation_proposals: list[dict] = field(default_factory=list)

    # --- Quality & meta -----------------------------------------------------
    evaluator: EvaluatorSummary = field(default_factory=EvaluatorSummary)
    provenance: ProvenanceInfo = field(default_factory=ProvenanceInfo)
    cost: CostReport = field(default_factory=CostReport)
    generated_at: str = ""


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _manifest_path(workspace: Path) -> Path:
    return workspace / ".swarm" / MANIFEST_FILENAME


def save_manifest(workspace: Path, manifest: RunManifest) -> Path:
    """Persist manifest to ``.swarm/run-manifest.json``.  Atomic write."""
    path = _manifest_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest.generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(manifest), indent=2, sort_keys=False))
    tmp.replace(path)
    return path


def load_manifest(workspace: Path) -> RunManifest | None:
    """Load manifest from workspace.  Returns ``None`` if missing or malformed."""
    path = _manifest_path(workspace)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        return None
    return _manifest_from_dict(data)


def _manifest_from_dict(data: dict) -> RunManifest:
    """Rehydrate a ``RunManifest`` from a plain dict (JSON-loaded)."""
    m = RunManifest()
    m.schema_version = data.get("schema_version", SCHEMA_VERSION)
    m.question = data.get("question", "")
    m.answer = data.get("answer", "")
    m.mode = data.get("mode", "")
    m.rigor = data.get("rigor", "")
    m.status = data.get("status", "unknown")
    m.converged = bool(data.get("converged", False))
    m.reason = data.get("reason", "")
    m.generated_at = data.get("generated_at", "")

    m.primary_claims = [
        PrimaryClaim(**_pick(c, PrimaryClaim.__dataclass_fields__))
        for c in data.get("primary_claims", []) if isinstance(c, dict)
    ]
    m.hypotheses = [
        HypothesisOutcome(**_pick(h, HypothesisOutcome.__dataclass_fields__))
        for h in data.get("hypotheses", []) if isinstance(h, dict)
    ]
    m.experiments = [
        ExperimentRecord(**_pick(e, ExperimentRecord.__dataclass_fields__))
        for e in data.get("experiments", []) if isinstance(e, dict)
    ]
    m.artifacts = [
        ManifestArtifact(**_pick(a, ManifestArtifact.__dataclass_fields__))
        for a in data.get("artifacts", []) if isinstance(a, dict)
    ]
    m.caveats = list(data.get("caveats", []))
    m.reviewer_defense = [
        ReviewerObjection(**_pick(r, ReviewerObjection.__dataclass_fields__))
        for r in data.get("reviewer_defense", []) if isinstance(r, dict)
    ]
    m.pending_objections = list(data.get("pending_objections", []))
    m.continuation_proposals = list(data.get("continuation_proposals", []))

    ev = data.get("evaluator", {}) or {}
    if isinstance(ev, dict):
        m.evaluator = EvaluatorSummary(
            score=float(ev.get("score", 0.0) or 0.0),
            rounds=int(ev.get("rounds", 0) or 0),
            dimensions=ev.get("dimensions", {}) or {},
            remediations=list(ev.get("remediations", []) or []),
        )

    prov = data.get("provenance", {}) or {}
    if isinstance(prov, dict):
        m.provenance = ProvenanceInfo(**_pick(prov, ProvenanceInfo.__dataclass_fields__))

    cost = data.get("cost", {}) or {}
    if isinstance(cost, dict):
        m.cost = CostReport(**_pick(cost, CostReport.__dataclass_fields__))
    return m


def _pick(d: dict, fields: Any) -> dict:
    """Return a shallow subset of ``d`` containing only keys in ``fields``."""
    return {k: d[k] for k in d if k in fields}


# ---------------------------------------------------------------------------
# Validation (rigor-tiered requirements)
# ---------------------------------------------------------------------------

def validate(manifest: RunManifest, rigor: str = "standard") -> ValidationResult:
    """Validate manifest against the requirements of the given rigor tier.

    Each tier is strictly additive: higher tiers require everything the
    lower tiers require plus more.  Unknown rigors are treated as ``adaptive``.
    """
    rigor = (rigor or "standard").lower()
    if rigor not in RIGOR_TIERS:
        rigor = "adaptive"

    missing: list[str] = []
    warnings: list[str] = []

    # --- standard tier -----------------------------------------------------
    if not manifest.question:
        missing.append("question")
    if manifest.status in ("", "unknown"):
        missing.append("status")
    if not manifest.generated_at:
        warnings.append("generated_at not set (call save_manifest)")

    if rigor == "standard":
        return ValidationResult(valid=not missing, missing=missing, warnings=warnings)

    # --- adaptive tier -----------------------------------------------------
    if not manifest.answer:
        missing.append("answer")
    if not manifest.primary_claims:
        missing.append("primary_claims (>=1)")

    if rigor == "adaptive":
        return ValidationResult(valid=not missing, missing=missing, warnings=warnings)

    # --- analytical tier ---------------------------------------------------
    if not manifest.experiments:
        missing.append("experiments (>=1)")
    if manifest.evaluator.score <= 0.0:
        warnings.append("evaluator.score is 0 — evaluator may not have run")
    if not manifest.caveats:
        warnings.append("caveats empty at analytical rigor")

    if rigor == "analytical":
        return ValidationResult(valid=not missing, missing=missing, warnings=warnings)

    # --- scientific tier ---------------------------------------------------
    if not manifest.hypotheses:
        missing.append("hypotheses (>=1)")
    if not manifest.reviewer_defense:
        warnings.append("reviewer_defense empty at scientific rigor")

    if rigor == "scientific":
        return ValidationResult(valid=not missing, missing=missing, warnings=warnings)

    # --- experimental tier -------------------------------------------------
    for c in manifest.primary_claims:
        if not c.effect_size or not c.confidence_interval:
            warnings.append(
                f"primary_claim {c.id or '?'} missing effect_size or CI "
                "(required at experimental rigor)"
            )
    return ValidationResult(valid=not missing, missing=missing, warnings=warnings)


# ---------------------------------------------------------------------------
# Factory — assemble a manifest from workspace state
# ---------------------------------------------------------------------------

def build_manifest_from_workspace(
    workspace: Path,
    *,
    question: str = "",
    mode: str = "",
    rigor: str = "",
    ledger: ClaimLedger | None = None,
    investigation: Any = None,
    findings: list[dict] | None = None,
) -> RunManifest:
    """Assemble a ``RunManifest`` from existing ``.swarm/`` state.

    This function is read-only with respect to the workspace — it never
    writes anything.  Call ``save_manifest`` to persist the result.

    Arguments:
        workspace: Path to the investigation workspace root.
        question:  Original NL prompt (from Investigation.question if empty).
        mode/rigor: Fallbacks if investigation is None.
        ledger:    Claim Ledger for this lineage (preferred source of claims).
        investigation: Optional ``Investigation`` dataclass for provenance.
        findings:  Optional pre-fetched findings list (saves a bd call).
    """
    m = RunManifest()
    m.question = question or (getattr(investigation, "question", "") or "")
    m.mode = mode or (getattr(investigation, "mode", "") or "")
    m.rigor = rigor or (getattr(investigation, "rigor", "") or "")

    # --- Provenance --------------------------------------------------------
    if investigation is not None:
        m.provenance = _build_provenance(workspace, investigation)
    else:
        m.provenance = ProvenanceInfo(workspace_path=str(workspace))

    # --- Convergence signal -----------------------------------------------
    conv = _load_json(workspace / ".swarm" / "convergence.json")
    if isinstance(conv, dict):
        m.converged = bool(conv.get("converged", False))
        m.status = str(conv.get("status", "unknown") or "unknown")
        m.reason = str(conv.get("reason", "") or "")

    # --- Evaluator ---------------------------------------------------------
    m.evaluator = _load_evaluator(workspace)

    # --- Hypotheses from belief map ---------------------------------------
    belief_map = load_belief_map(workspace)
    m.hypotheses = _hypotheses_from_belief_map(belief_map)

    # --- Experiments from Beads findings ----------------------------------
    if findings is None:
        findings = _safe_get_findings(workspace)
    m.experiments = _experiments_from_findings(findings)

    # --- Primary claims ----------------------------------------------------
    # Preferred source: Claim Ledger scoped to this cycle.  Fallback: the
    # `.swarm/claim-evidence.json` registry produced by the Synthesizer.
    if ledger is not None and m.provenance.cycle_number:
        m.primary_claims = _claims_from_ledger(
            ledger, cycle=m.provenance.cycle_number, findings=findings,
        )
        m.pending_objections = [
            _objection_to_dict(o) for o in ledger.objections
            if o.status in ("pending", "investigating", "surfaced")
        ]
    if not m.primary_claims:
        reg = load_claim_evidence(workspace)
        m.primary_claims = _claims_from_registry(reg, findings=findings)

    # --- Single-sentence answer -------------------------------------------
    m.answer = _derive_answer(m.primary_claims, belief_map)

    # --- Caveats -----------------------------------------------------------
    m.caveats = _derive_caveats(m, findings, conv if isinstance(conv, dict) else None)

    # --- Artifacts ---------------------------------------------------------
    m.artifacts = _discover_artifacts(workspace, findings)

    # --- Continuation proposals -------------------------------------------
    props = _load_json(workspace / ".swarm" / "continuation-proposals.json")
    if isinstance(props, list):
        m.continuation_proposals = props
    elif isinstance(props, dict) and isinstance(props.get("proposals"), list):
        m.continuation_proposals = props["proposals"]

    # --- Reviewer defense --------------------------------------------------
    # Derived heuristically from pending objections and caveats.
    m.reviewer_defense = _derive_reviewer_defense(m)

    return m


# ---------------------------------------------------------------------------
# Helper: provenance
# ---------------------------------------------------------------------------

def _build_provenance(workspace: Path, inv: Any) -> ProvenanceInfo:
    prov = ProvenanceInfo(
        investigation_id=getattr(inv, "id", None),
        lineage_id=getattr(inv, "lineage_id", None),
        cycle_number=getattr(inv, "cycle_number", 1) or 1,
        parent_id=getattr(inv, "parent_id", None),
        codename=getattr(inv, "codename", "") or "",
        mode=getattr(inv, "mode", "") or "",
        rigor=getattr(inv, "rigor", "") or "",
        workspace_path=str(workspace),
    )
    started = getattr(inv, "started_at", None)
    completed = getattr(inv, "completed_at", None)
    if started:
        prov.started_at = datetime.fromtimestamp(
            float(started), tz=timezone.utc).isoformat(timespec="seconds")
    if completed:
        prov.completed_at = datetime.fromtimestamp(
            float(completed), tz=timezone.utc).isoformat(timespec="seconds")

    # Git commit (optional, best-effort, non-fatal)
    commit = _git_head(workspace)
    if commit:
        prov.git_commit = commit
    return prov


def _git_head(workspace: Path) -> str:
    """Return the current git HEAD commit, or "" if unavailable."""
    head = workspace / ".git" / "HEAD"
    if not head.exists():
        return ""
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            ref_path = workspace / ".git" / ref[5:]
            if ref_path.exists():
                return ref_path.read_text().strip()[:40]
        # Detached HEAD already holds the hash
        return ref[:40]
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Helper: evaluator
# ---------------------------------------------------------------------------

def _load_evaluator(workspace: Path) -> EvaluatorSummary:
    data = _load_json(workspace / ".swarm" / "eval-score.json")
    if not isinstance(data, dict):
        return EvaluatorSummary()
    try:
        score = float(data.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    try:
        rounds = int(data.get("rounds", 0) or 0)
    except (TypeError, ValueError):
        rounds = 0
    dims = data.get("dimensions", {})
    if not isinstance(dims, dict):
        dims = {}
    rem = data.get("remediations", [])
    if not isinstance(rem, list):
        rem = []
    return EvaluatorSummary(
        score=score, rounds=rounds, dimensions=dims,
        remediations=[str(x) for x in rem if x],
    )


# ---------------------------------------------------------------------------
# Helper: hypotheses from belief map
# ---------------------------------------------------------------------------

_STATUS_TO_DIRECTION = {
    "confirmed": "confirmed",
    "supported": "confirmed",
    "refuted": "refuted_reversed",
    "refuted_reversed": "refuted_reversed",
    "rejected": "refuted_reversed",
    "inconclusive": "inconclusive",
    "untested": "",
    "testing": "",
}


def _hypotheses_from_belief_map(bm: BeliefMap) -> list[HypothesisOutcome]:
    out: list[HypothesisOutcome] = []
    for h in bm.hypotheses:
        out.append(HypothesisOutcome(
            id=h.id,
            statement=h.name or h.id,
            expected_direction="",
            observed_direction=_STATUS_TO_DIRECTION.get(h.status.lower(), ""),
            confidence=h.confidence or "",
            supporting_findings=list(h.evidence or []),
        ))
    return out


# ---------------------------------------------------------------------------
# Helper: experiments from findings
# ---------------------------------------------------------------------------

def _safe_get_findings(workspace: Path) -> list[dict]:
    """Fetch findings without importing gateway at module load time."""
    try:
        from voronoi.gateway.evidence import get_findings
        return get_findings(workspace) or []
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("get_findings failed: %s", e)
        return []


def _experiments_from_findings(findings: list[dict]) -> list[ExperimentRecord]:
    from voronoi.utils import clean_finding_title
    out: list[ExperimentRecord] = []
    for f in findings or []:
        out.append(ExperimentRecord(
            id=str(f.get("id", "")),
            method=clean_finding_title(f.get("title", "")),
            effect_size=str(f.get("effect_size", "") or ""),
            ci=str(f.get("ci_95", "") or ""),
            p_value=str(f.get("p", "") or ""),
            n=str(f.get("n", "") or ""),
            stat_test=str(f.get("stat_test", "") or ""),
            valence=str(f.get("valence", "") or ""),
            status=str(f.get("status", "") or ""),
        ))
    return out


# ---------------------------------------------------------------------------
# Helper: primary claims from Claim Ledger
# ---------------------------------------------------------------------------

def _claims_from_ledger(
    ledger: ClaimLedger, *, cycle: int, findings: list[dict] | None,
) -> list[PrimaryClaim]:
    """Extract primary claims for this run's cycle from the ledger."""
    findings_by_id = {f.get("id", ""): f for f in (findings or [])}
    out: list[PrimaryClaim] = []
    for c in ledger.claims:
        # Include claims either from this cycle OR still active across runs
        if c.source_cycle != cycle and c.status not in ("locked", "replicated"):
            continue
        pc = PrimaryClaim(
            id=c.id,
            statement=c.statement,
            effect_size=c.effect_summary or "",
            sample_summary=c.sample_summary or "",
            status=c.status,
            provenance=c.provenance,
            supporting_findings=list(c.supporting_findings),
            supporting_artifacts=[a.path for a in c.artifacts],
        )
        # Enrich from the finding's metadata if available
        for fid in pc.supporting_findings:
            f = findings_by_id.get(fid)
            if not f:
                continue
            if not pc.effect_size and f.get("effect_size"):
                pc.effect_size = str(f["effect_size"])
            if not pc.confidence_interval and f.get("ci_95"):
                pc.confidence_interval = str(f["ci_95"])
            if not pc.p_value and f.get("p"):
                pc.p_value = str(f["p"])
            valence = str(f.get("valence", "")).lower()
            if not pc.direction and valence:
                pc.direction = {
                    "positive": "confirmed",
                    "negative": "refuted_reversed",
                    "inconclusive": "inconclusive",
                }.get(valence, "")
            break  # one finding is enough to seed numeric fields
        out.append(pc)
    return out


def _claims_from_registry(
    reg: ClaimEvidenceRegistry, *, findings: list[dict] | None,
) -> list[PrimaryClaim]:
    """Fallback: build primary claims from .swarm/claim-evidence.json."""
    findings_by_id = {f.get("id", ""): f for f in (findings or [])}
    out: list[PrimaryClaim] = []
    for i, c in enumerate(reg.claims, start=1):
        pc = PrimaryClaim(
            id=c.claim_id or f"C{i}",
            statement=c.claim_text,
            status="provisional",
            supporting_findings=list(c.finding_ids),
        )
        # Seed from the first supporting finding, if any
        for fid in pc.supporting_findings:
            f = findings_by_id.get(fid)
            if not f:
                continue
            pc.effect_size = str(f.get("effect_size", "") or "")
            pc.confidence_interval = str(f.get("ci_95", "") or "")
            pc.p_value = str(f.get("p", "") or "")
            pc.sample_summary = f"N={f['n']}" if f.get("n") else ""
            break
        if c.strength:
            # Strength label maps to an informal status hint
            pc.caveats.append(f"strength={c.strength}")
        if c.interpretation:
            pc.caveats.append(c.interpretation)
        out.append(pc)
    return out


def _objection_to_dict(o: Any) -> dict:
    return {
        "id": getattr(o, "id", ""),
        "target_claim": getattr(o, "target_claim", ""),
        "concern": getattr(o, "concern", ""),
        "type": getattr(o, "objection_type", ""),
        "raised_by": getattr(o, "raised_by", ""),
        "status": getattr(o, "status", ""),
    }


# ---------------------------------------------------------------------------
# Helper: derived fields (answer, caveats, reviewer defense)
# ---------------------------------------------------------------------------

def _derive_answer(claims: list[PrimaryClaim], bm: BeliefMap) -> str:
    """Pick the strongest claim as a one-sentence answer."""
    if not claims:
        return ""
    # Prefer locked > replicated > asserted > provisional
    priority = {"replicated": 0, "locked": 1, "asserted": 2,
                "provisional": 3, "challenged": 4, "retired": 9}
    ordered = sorted(claims, key=lambda c: priority.get(c.status, 5))
    return ordered[0].statement


def _derive_caveats(
    manifest: RunManifest, findings: list[dict] | None,
    conv: dict | None,
) -> list[str]:
    """Build a honest limitations list from finding fragility + status."""
    caveats: list[str] = []
    if conv and not conv.get("converged", False):
        status = str(conv.get("status", "") or "")
        if status and status != "unknown":
            caveats.append(f"Run status: {status} — {conv.get('reason', '')}".strip(" —"))
    for f in findings or []:
        if str(f.get("robust", "")).lower() == "no":
            title = f.get("title", "")
            caveats.append(f"Fragile finding: {title} (ROBUST=no)")
        if str(f.get("stat_review", "")).upper() not in ("APPROVED", ""):
            caveats.append(
                f"{f.get('id', '?')} statistical review: {f.get('stat_review', '')}"
            )
    blockers = (conv or {}).get("blockers")
    if isinstance(blockers, list):
        for b in blockers:
            caveats.append(f"Blocker: {b}")
    # Dedup while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for c in caveats:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _derive_reviewer_defense(m: RunManifest) -> list[ReviewerObjection]:
    """Generate reviewer-defense entries from pending objections.

    This is a minimal, honest surface: each pending objection becomes an
    entry whose ``response`` is blank so it's obvious nothing is hidden.
    Synthesizer can override by writing the manifest directly in a later
    iteration of this feature.
    """
    out: list[ReviewerObjection] = []
    for o in m.pending_objections:
        out.append(ReviewerObjection(
            objection=str(o.get("concern", "") or ""),
            response="(unanswered — pending)",
        ))
    return out


# ---------------------------------------------------------------------------
# Helper: artifact discovery
# ---------------------------------------------------------------------------

_ARTIFACT_CANDIDATES: tuple[tuple[str, str], ...] = (
    # (relative path, kind)
    (".swarm/deliverable.md",      "paper"),
    (".swarm/paper.tex",           "paper"),
    (".swarm/paper.pdf",           "paper"),
    (".swarm/report.pdf",          "paper"),
    ("paper.tex",                  "paper"),
    ("paper.pdf",                  "paper"),
    ("output/paper/paper.pdf",     "paper"),
    ("submission.csv",             "submission"),
    ("pred.py",                    "code"),
    (".swarm/claim-evidence.json", "data"),
    (".swarm/belief-map.json",     "data"),
    (".swarm/eval-score.json",     "data"),
    (".swarm/convergence.json",    "data"),
)


def _discover_artifacts(
    workspace: Path, findings: list[dict] | None,
) -> list[ManifestArtifact]:
    """Discover artifacts in the workspace.  Best-effort, non-fatal on errors."""
    out: list[ManifestArtifact] = []
    seen: set[str] = set()

    for rel, kind in _ARTIFACT_CANDIDATES:
        p = workspace / rel
        if p.exists() and p.is_file() and rel not in seen:
            seen.add(rel)
            out.append(_make_artifact(p, rel, kind))

    # Figures anywhere under output/figures or figures/
    for fig_dir in (workspace / "output" / "figures", workspace / "figures"):
        if fig_dir.exists() and fig_dir.is_dir():
            for fig in sorted(fig_dir.glob("**/*")):
                if fig.is_file() and fig.suffix.lower() in (".png", ".pdf", ".svg", ".jpg"):
                    rel = str(fig.relative_to(workspace))
                    if rel not in seen:
                        seen.add(rel)
                        out.append(_make_artifact(fig, rel, "figure"))

    # Data artifacts referenced by findings (DATA_FILE notes)
    from voronoi.utils import extract_field
    for f in findings or []:
        df = extract_field(f.get("notes", ""), "DATA_FILE")
        if df and df not in seen:
            p = workspace / df
            if p.exists() and p.is_file():
                seen.add(df)
                out.append(_make_artifact(
                    p, df, "data",
                    description=f"data for {f.get('id', '?')}",
                ))
    return out


def _make_artifact(path: Path, rel: str, kind: str, *,
                   description: str = "") -> ManifestArtifact:
    """Build a ``ManifestArtifact``.  SHA-256 only for files < 50 MB."""
    art = ManifestArtifact(path=rel, kind=kind, description=description)
    try:
        st = path.stat()
        art.bytes = st.st_size
        if st.st_size < 50 * 1024 * 1024:
            import hashlib
            h = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            art.sha256 = h.hexdigest()
    except OSError as e:
        logger.debug("Could not hash %s: %s", path, e)
    return art


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Could not parse %s: %s", path, e)
        return None


__all__ = [
    "SCHEMA_VERSION",
    "MANIFEST_FILENAME",
    "RIGOR_TIERS",
    "ManifestArtifact",
    "PrimaryClaim",
    "HypothesisOutcome",
    "ExperimentRecord",
    "ProvenanceInfo",
    "CostReport",
    "EvaluatorSummary",
    "ReviewerObjection",
    "RunManifest",
    "ValidationResult",
    "save_manifest",
    "load_manifest",
    "validate",
    "build_manifest_from_workspace",
]
