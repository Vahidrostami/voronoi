"""Evidence layer — claim-evidence registry, consistency, finding interpretation."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from voronoi.utils import extract_field, clean_finding_title

logger = logging.getLogger("voronoi.science")


# ---------------------------------------------------------------------------
# Consistency Gate
# ---------------------------------------------------------------------------

@dataclass
class ConsistencyConflict:
    """A contradiction between two findings."""
    finding_a: str
    finding_b: str
    conflict_type: str  # direction, magnitude, conclusion
    description: str


def check_consistency(findings: list[dict]) -> list[ConsistencyConflict]:
    """Pairwise consistency check across validated findings."""
    conflicts: list[ConsistencyConflict] = []
    validated = [f for f in findings
                 if "STAT_REVIEW: APPROVED" in f.get("notes", "")]

    for i, a in enumerate(validated):
        for b in validated[i + 1:]:
            conflict = _check_pair_consistency(a, b)
            if conflict:
                conflicts.append(conflict)

    return conflicts


def _check_pair_consistency(a: dict, b: dict) -> ConsistencyConflict | None:
    """Check if two findings contradict each other."""
    notes_a = a.get("notes", "")
    notes_b = b.get("notes", "")

    valence_a = extract_field(notes_a, "VALENCE")
    valence_b = extract_field(notes_b, "VALENCE")

    title_a = a.get("title", "").lower()
    title_b = b.get("title", "").lower()

    words_a = set(re.findall(r'\b\w{4,}\b', title_a))
    words_b = set(re.findall(r'\b\w{4,}\b', title_b))
    overlap = words_a & words_b

    if len(overlap) < 2:
        return None

    if valence_a and valence_b and valence_a != valence_b:
        if {valence_a, valence_b} == {"positive", "negative"}:
            return ConsistencyConflict(
                finding_a=a.get("id", ""),
                finding_b=b.get("id", ""),
                conflict_type="direction",
                description=f"Opposing valence on related topic: "
                            f"{a.get('title', '')} ({valence_a}) vs "
                            f"{b.get('title', '')} ({valence_b})",
            )

    return None


# ---------------------------------------------------------------------------
# Enhanced Consistency Check — Semantic Similarity
# ---------------------------------------------------------------------------

def _tokenize_title(title: str) -> set[str]:
    """Extract meaningful tokens from a finding title for topic comparison."""
    _STOPWORDS = frozenset({
        "finding", "that", "this", "with", "from", "have", "been", "were",
        "does", "more", "than", "also", "into", "when", "each", "only",
        "both", "over", "some", "other", "about", "between", "through",
        "after", "before", "under", "above", "such", "most", "very",
        "just", "those", "these", "their", "there", "which", "while",
        "would", "could", "should", "shall", "will", "being", "having",
        "make", "made", "like", "used",
    })
    words = set(re.findall(r'\b[a-z]{3,}\b', title.lower()))
    words -= _STOPWORDS
    stemmed = set()
    for w in words:
        for suffix in ("ation", "tion", "ness", "ment", "ting", "ing",
                        "ies", "ied", "ed", "ly", "er", "es", "ss"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                w = w[:-len(suffix)]
                break
        stemmed.add(w)
    return stemmed


def check_consistency_enhanced(findings: list[dict]) -> list[ConsistencyConflict]:
    """Enhanced pairwise consistency check with better topic matching."""
    conflicts: list[ConsistencyConflict] = []
    validated = [f for f in findings
                 if "STAT_REVIEW: APPROVED" in f.get("notes", "")]

    for i, a in enumerate(validated):
        for b in validated[i + 1:]:
            conflict = _check_pair_enhanced(a, b)
            if conflict:
                conflicts.append(conflict)

    return conflicts


def _check_pair_enhanced(a: dict, b: dict) -> ConsistencyConflict | None:
    """Enhanced pair consistency check — direction + magnitude + overlap."""
    notes_a = a.get("notes", "")
    notes_b = b.get("notes", "")

    title_a = a.get("title", "")
    title_b = b.get("title", "")

    tokens_a = _tokenize_title(title_a)
    tokens_b = _tokenize_title(title_b)
    overlap = tokens_a & tokens_b

    if len(overlap) < 2:
        return None

    valence_a = extract_field(notes_a, "VALENCE")
    valence_b = extract_field(notes_b, "VALENCE")

    if valence_a and valence_b:
        if {valence_a.lower(), valence_b.lower()} == {"positive", "negative"}:
            return ConsistencyConflict(
                finding_a=a.get("id", ""),
                finding_b=b.get("id", ""),
                conflict_type="direction",
                description=f"Opposing valence on related topic "
                            f"(shared: {', '.join(sorted(overlap)[:5])}): "
                            f"{title_a} ({valence_a}) vs "
                            f"{title_b} ({valence_b})",
            )

    es_a = extract_field(notes_a, "EFFECT_SIZE")
    es_b = extract_field(notes_b, "EFFECT_SIZE")
    if es_a and es_b and len(overlap) >= 3:
        try:
            nums_a = re.findall(r'[-+]?\d*\.?\d+', es_a)
            nums_b = re.findall(r'[-+]?\d*\.?\d+', es_b)
            if nums_a and nums_b:
                val_a = abs(float(nums_a[0]))
                val_b = abs(float(nums_b[0]))
                if val_a > 0 and val_b > 0:
                    ratio = max(val_a, val_b) / min(val_a, val_b)
                    if ratio > 3.0:
                        return ConsistencyConflict(
                            finding_a=a.get("id", ""),
                            finding_b=b.get("id", ""),
                            conflict_type="magnitude",
                            description=f"Large magnitude difference on related topic "
                                        f"(shared: {', '.join(sorted(overlap)[:5])}): "
                                        f"d={es_a} vs d={es_b} ({ratio:.1f}x)",
                        )
        except (ValueError, ZeroDivisionError):
            pass

    return None


# ---------------------------------------------------------------------------
# Claim-Evidence Registry
# ---------------------------------------------------------------------------

@dataclass
class ClaimEvidence:
    """A single claim linked to its supporting evidence."""
    claim_id: str
    claim_text: str
    finding_ids: list[str] = field(default_factory=list)
    hypothesis_ids: list[str] = field(default_factory=list)
    strength: str = "provisional"
    interpretation: str = ""


@dataclass
class ClaimEvidenceRegistry:
    """Maps every claim in the deliverable to supporting findings."""
    claims: list[ClaimEvidence] = field(default_factory=list)
    orphan_findings: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    coverage_score: float = 0.0

    def add_claim(self, claim: ClaimEvidence) -> None:
        self.claims.append(claim)

    def audit(self, all_finding_ids: list[str]) -> None:
        """Compute orphan findings and unsupported claims."""
        cited = set()
        for c in self.claims:
            cited.update(c.finding_ids)
            if not c.finding_ids:
                self.unsupported_claims.append(c.claim_id)
        self.orphan_findings = [f for f in all_finding_ids if f not in cited]
        total = len(self.claims)
        supported = total - len(self.unsupported_claims)
        self.coverage_score = supported / total if total > 0 else 0.0


def load_claim_evidence(workspace: Path) -> ClaimEvidenceRegistry:
    """Load claim-evidence registry from .swarm/claim-evidence.json."""
    path = workspace / ".swarm" / "claim-evidence.json"
    if not path.exists():
        return ClaimEvidenceRegistry()
    try:
        data = json.loads(path.read_text())
        if isinstance(data, list):
            data = {"claims": data}
        if not isinstance(data, dict):
            logger.warning("claim-evidence.json: expected dict, got %s", type(data).__name__)
            return ClaimEvidenceRegistry()
        reg = ClaimEvidenceRegistry(
            orphan_findings=data.get("orphan_findings", []),
            unsupported_claims=data.get("unsupported_claims", []),
            coverage_score=data.get("coverage_score", 0.0),
        )
        for c in data.get("claims", []):
            if not isinstance(c, dict):
                logger.warning("claim-evidence.json: skipping non-dict claim entry: %s", type(c).__name__)
                continue
            reg.claims.append(ClaimEvidence(
                claim_id=c.get("claim_id", ""),
                claim_text=c.get("claim_text", ""),
                finding_ids=c.get("finding_ids", []),
                hypothesis_ids=c.get("hypothesis_ids", []),
                strength=c.get("strength", "provisional"),
                interpretation=c.get("interpretation", ""),
            ))
        return reg
    except (json.JSONDecodeError, OSError, AttributeError, TypeError) as e:
        logger.warning("Failed to load claim-evidence registry: %s", e)
        return ClaimEvidenceRegistry()


def save_claim_evidence(workspace: Path, reg: ClaimEvidenceRegistry) -> None:
    """Save claim-evidence registry to .swarm/claim-evidence.json."""
    path = workspace / ".swarm" / "claim-evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "claims": [asdict(c) for c in reg.claims],
        "orphan_findings": reg.orphan_findings,
        "unsupported_claims": reg.unsupported_claims,
        "coverage_score": reg.coverage_score,
    }
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Finding Interpretation Helpers
# ---------------------------------------------------------------------------

def classify_effect_size(d: float) -> str:
    """Classify Cohen's d into practical significance categories."""
    d = abs(d)
    if d < 0.2:
        return "negligible"
    if d < 0.5:
        return "small"
    if d < 0.8:
        return "medium"
    if d < 1.2:
        return "large"
    return "very large"


def assess_ci_quality(effect_str: str, ci_str: str) -> str:
    """Assess confidence interval precision relative to effect size."""
    try:
        nums_e = re.findall(r'[-+]?\d*\.?\d+', effect_str)
        nums_ci = re.findall(r'[-+]?\d*\.?\d+', ci_str)
        if not nums_e or len(nums_ci) < 2:
            return "unknown"
        effect = abs(float(nums_e[0]))
        lo, hi = float(nums_ci[0]), float(nums_ci[1])
        width = hi - lo
        if effect <= 0:
            return "unknown"
        ratio = width / effect
        if ratio < 0.5:
            return "precise"
        if ratio < 1.0:
            return "adequate"
        if ratio < 1.5:
            return "wide"
        return "very wide"
    except (ValueError, IndexError):
        return "unknown"


def interpret_finding(finding: dict) -> dict:
    """Produce a rich interpretation of a finding for report generation."""
    notes = finding.get("notes", "")
    es = extract_field(notes, "EFFECT_SIZE")
    ci = extract_field(notes, "CI_95")
    valence = extract_field(notes, "VALENCE")
    robust = extract_field(notes, "ROBUST")
    stat_review = extract_field(notes, "STAT_REVIEW")

    result: dict = {
        "practical_significance": "unknown",
        "ci_quality": "unknown",
        "interpretation_text": "",
        "strength_label": "unreviewed",
    }

    if es:
        try:
            nums = re.findall(r'[-+]?\d*\.?\d+', es)
            if nums:
                d_val = float(nums[0])
                result["practical_significance"] = classify_effect_size(d_val)
        except ValueError:
            pass

    if es and ci:
        result["ci_quality"] = assess_ci_quality(es, ci)

    if "APPROVED" in str(stat_review):
        if robust and robust.lower() == "yes":
            result["strength_label"] = "robust"
        elif robust and robust.lower() == "no":
            result["strength_label"] = "fragile"
        else:
            result["strength_label"] = "reviewed"
    elif "REJECTED" in str(stat_review):
        result["strength_label"] = "rejected"

    title = clean_finding_title(finding.get("title", ""))
    parts = []
    if valence:
        parts.append(f"{valence} result")
    if result["practical_significance"] != "unknown":
        parts.append(f"{result['practical_significance']} practical effect")
    if result["ci_quality"] in ("wide", "very wide"):
        parts.append("imprecise estimate — interpret with caution")
    elif result["ci_quality"] == "precise":
        parts.append("precisely estimated")
    if result["strength_label"] == "robust":
        parts.append("robust under sensitivity analysis")
    elif result["strength_label"] == "fragile":
        parts.append("fragile — conditions documented")

    result["interpretation_text"] = "; ".join(parts) if parts else ""

    return result


# ---------------------------------------------------------------------------
# Paradigm Stress Detection
# ---------------------------------------------------------------------------

@dataclass
class ParadigmStressResult:
    """Result of paradigm stress check."""
    stressed: bool
    contradiction_count: int
    contradicting_findings: list[str]
    message: str


def check_paradigm_stress(workspace: Path) -> ParadigmStressResult:
    """Detect if 3+ findings contradict the working model."""
    from voronoi.science._helpers import _find_consistency_conflicts
    contradictions = _find_consistency_conflicts(workspace)
    count = len(contradictions)
    finding_ids = [c.get("finding_a", "") for c in contradictions] + \
                  [c.get("finding_b", "") for c in contradictions]
    finding_ids = list(set(f for f in finding_ids if f))

    if count >= 3:
        return ParadigmStressResult(
            stressed=True,
            contradiction_count=count,
            contradicting_findings=finding_ids,
            message=f"PARADIGM STRESS: {count} contradictions detected. "
                    f"Working model may need fundamental revision.",
        )
    return ParadigmStressResult(
        stressed=False,
        contradiction_count=count,
        contradicting_findings=finding_ids,
        message=f"{count} contradiction(s) — within normal range",
    )
