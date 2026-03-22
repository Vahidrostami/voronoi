"""Shared internal helpers for the science subpackage.

This module collects utilities consumed by convergence.py, gates.py,
fabrication.py, and the rest of the codebase.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from voronoi.beads import run_bd as _run_bd
from voronoi.utils import clean_finding_title, extract_field

logger = logging.getLogger("voronoi.science")


# ---------------------------------------------------------------------------
# Beads task queries
# ---------------------------------------------------------------------------

def _fetch_tasks(workspace: Path) -> list[dict] | None:
    """Fetch all tasks from Beads.  Returns None on failure."""
    code, output = _run_bd("list", "--json", cwd=str(workspace))
    if code != 0:
        logger.warning("bd list --json failed (exit=%d) in %s", code, workspace)
        return None
    if not output:
        return None
    try:
        data = json.loads(output)
        if not isinstance(data, list):
            logger.warning("bd list --json returned non-list: %s", type(data).__name__)
            return None
        return data
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("bd list --json returned invalid JSON in %s: %s", workspace, e)
        return None


def _find_consistency_conflicts(workspace: Path, tasks: list[dict] | None = None) -> list[dict]:
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    conflicts = []
    for task in tasks:
        notes = task.get("notes", "")
        if "CONSISTENCY_CONFLICT" in notes and task.get("status") != "closed":
            conflict_val = extract_field(notes, "CONSISTENCY_CONFLICT")
            finding_a = finding_b = ""
            if " vs " in conflict_val:
                parts = conflict_val.split(" vs ")
                finding_a, finding_b = parts[0].strip(), parts[-1].strip()
            conflicts.append({"id": task.get("id", ""), "finding_a": finding_a, "finding_b": finding_b})
    return conflicts


def _find_contested_findings(workspace: Path, tasks: list[dict] | None = None) -> list[str]:
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    return [t.get("id", "") for t in tasks
            if "ADVERSARIAL_RESULT: CONTESTED" in t.get("notes", "")]


def _find_theories(workspace: Path, tasks: list[dict] | None = None) -> list[dict]:
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    return [{"id": t.get("id", ""), "status": extract_field(t.get("notes", ""), "STATUS")}
            for t in tasks if "TYPE:theory" in t.get("notes", "")]


def _find_tested_predictions(workspace: Path, tasks: list[dict] | None = None) -> list[str]:
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    return [t.get("id", "") for t in tasks
            if "PREDICTION_TESTED" in t.get("notes", "") and t.get("status") == "closed"]


def _find_undocumented_fragile(workspace: Path, tasks: list[dict] | None = None) -> list[str]:
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    return [t.get("id", "") for t in tasks
            if "ROBUST:no" in t.get("notes", "").lower() and "CONDITIONS:" not in t.get("notes", "")]


def _find_unreplicated_high_impact(workspace: Path, tasks: list[dict] | None = None) -> list[str]:
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    return [t.get("id", "") for t in tasks
            if "FINDING" in t.get("title", "").upper() and t.get("priority", 9) <= 1
            and ("replicated:no" in t.get("notes", "").lower() or "replicated" not in t.get("notes", "").lower())]


def _find_design_invalid(workspace: Path, tasks: list[dict] | None = None) -> list[str]:
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    return [t.get("id", "") for t in tasks
            if "DESIGN_INVALID" in t.get("notes", "") and t.get("status") != "closed"]


# ---------------------------------------------------------------------------
# Consistency Gate (pairwise finding checks)
# ---------------------------------------------------------------------------

@dataclass
class ConsistencyConflict:
    finding_a: str
    finding_b: str
    conflict_type: str
    description: str


def check_consistency(findings: list[dict]) -> list[ConsistencyConflict]:
    """Pairwise consistency check across validated findings."""
    conflicts: list[ConsistencyConflict] = []
    validated = [f for f in findings if "STAT_REVIEW: APPROVED" in f.get("notes", "")]
    for i, a in enumerate(validated):
        for b in validated[i + 1:]:
            c = _check_pair_consistency(a, b)
            if c:
                conflicts.append(c)
    return conflicts


def _check_pair_consistency(a: dict, b: dict) -> ConsistencyConflict | None:
    notes_a, notes_b = a.get("notes", ""), b.get("notes", "")
    valence_a, valence_b = extract_field(notes_a, "VALENCE"), extract_field(notes_b, "VALENCE")
    words_a = set(re.findall(r'\b\w{4,}\b', a.get("title", "").lower()))
    words_b = set(re.findall(r'\b\w{4,}\b', b.get("title", "").lower()))
    if len(words_a & words_b) < 2:
        return None
    if valence_a and valence_b and {valence_a, valence_b} == {"positive", "negative"}:
        return ConsistencyConflict(
            finding_a=a.get("id", ""), finding_b=b.get("id", ""),
            conflict_type="direction",
            description=f"Opposing valence: {a.get('title', '')} ({valence_a}) vs {b.get('title', '')} ({valence_b})",
        )
    return None


def _tokenize_title(title: str) -> set[str]:
    _STOPWORDS = frozenset({
        "finding", "that", "this", "with", "from", "have", "been", "were",
        "does", "more", "than", "also", "into", "when", "each", "only",
        "both", "over", "some", "other", "about", "between", "through",
        "after", "before", "under", "above", "such", "most", "very",
        "just", "those", "these", "their", "there", "which", "while",
        "would", "could", "should", "shall", "will", "being", "having",
        "make", "made", "like", "used",
    })
    words = set(re.findall(r'\b[a-z]{3,}\b', title.lower())) - _STOPWORDS
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
    """Enhanced pairwise check with stemming + magnitude comparison."""
    conflicts: list[ConsistencyConflict] = []
    validated = [f for f in findings if "STAT_REVIEW: APPROVED" in f.get("notes", "")]
    for i, a in enumerate(validated):
        for b in validated[i + 1:]:
            c = _check_pair_enhanced(a, b)
            if c:
                conflicts.append(c)
    return conflicts


def _check_pair_enhanced(a: dict, b: dict) -> ConsistencyConflict | None:
    notes_a, notes_b = a.get("notes", ""), b.get("notes", "")
    overlap = _tokenize_title(a.get("title", "")) & _tokenize_title(b.get("title", ""))
    if len(overlap) < 2:
        return None
    valence_a, valence_b = extract_field(notes_a, "VALENCE"), extract_field(notes_b, "VALENCE")
    if valence_a and valence_b and {valence_a.lower(), valence_b.lower()} == {"positive", "negative"}:
        return ConsistencyConflict(
            finding_a=a.get("id", ""), finding_b=b.get("id", ""),
            conflict_type="direction",
            description=f"Opposing valence (shared: {', '.join(sorted(overlap)[:5])}): "
                        f"{a.get('title', '')} ({valence_a}) vs {b.get('title', '')} ({valence_b})",
        )
    es_a, es_b = extract_field(notes_a, "EFFECT_SIZE"), extract_field(notes_b, "EFFECT_SIZE")
    if es_a and es_b and len(overlap) >= 3:
        try:
            va = abs(float(re.findall(r'[-+]?\d*\.?\d+', es_a)[0]))
            vb = abs(float(re.findall(r'[-+]?\d*\.?\d+', es_b)[0]))
            if va > 0 and vb > 0 and max(va, vb) / min(va, vb) > 3.0:
                return ConsistencyConflict(
                    finding_a=a.get("id", ""), finding_b=b.get("id", ""),
                    conflict_type="magnitude",
                    description=f"Large magnitude difference (shared: {', '.join(sorted(overlap)[:5])}): "
                                f"d={es_a} vs d={es_b} ({max(va, vb) / min(va, vb):.1f}x)",
                )
        except (ValueError, ZeroDivisionError, IndexError):
            pass
    return None


# ---------------------------------------------------------------------------
# Paradigm Stress
# ---------------------------------------------------------------------------

@dataclass
class ParadigmStressResult:
    stressed: bool
    contradiction_count: int
    contradicting_findings: list[str]
    message: str


def check_paradigm_stress(workspace: Path) -> ParadigmStressResult:
    contradictions = _find_consistency_conflicts(workspace)
    count = len(contradictions)
    ids = list(set(c.get("finding_a", "") for c in contradictions) |
               set(c.get("finding_b", "") for c in contradictions) - {""})
    if count >= 3:
        return ParadigmStressResult(True, count, ids,
                                    f"PARADIGM STRESS: {count} contradictions detected.")
    return ParadigmStressResult(False, count, ids, f"{count} contradiction(s) — within normal range")


# ---------------------------------------------------------------------------
# Heartbeat stall detection (used by dispatcher)
# ---------------------------------------------------------------------------

def check_heartbeat_stall(workspace: Path, branch: str, stall_minutes: int = 10) -> bool:
    """Return True if the agent appears stalled."""
    path = workspace / ".swarm" / f"heartbeat-{branch}.jsonl"
    if not path.exists():
        return False
    try:
        lines = path.read_text().strip().split("\n")
        beats = [json.loads(line) for line in lines[-5:] if line.strip()]
    except (json.JSONDecodeError, OSError):
        return False
    if len(beats) < 2:
        return False
    if len({(b.get("phase", ""), b.get("status", "")) for b in beats}) > 1:
        return False
    try:
        span = (datetime.fromisoformat(beats[-1]["timestamp"]) -
                datetime.fromisoformat(beats[0]["timestamp"])).total_seconds() / 60
        return span >= stall_minutes
    except (ValueError, TypeError, KeyError):
        return False


# ---------------------------------------------------------------------------
# Finding Interpretation (used by report.py)
# ---------------------------------------------------------------------------

def classify_effect_size(d: float) -> str:
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
    try:
        nums_e = re.findall(r'[-+]?\d*\.?\d+', effect_str)
        nums_ci = re.findall(r'[-+]?\d*\.?\d+', ci_str)
        if not nums_e or len(nums_ci) < 2:
            return "unknown"
        effect = abs(float(nums_e[0]))
        width = float(nums_ci[1]) - float(nums_ci[0])
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
    notes = finding.get("notes", "")
    es = extract_field(notes, "EFFECT_SIZE")
    ci = extract_field(notes, "CI_95")
    valence = extract_field(notes, "VALENCE")
    robust = extract_field(notes, "ROBUST")
    stat_review = extract_field(notes, "STAT_REVIEW")
    result: dict = {"practical_significance": "unknown", "ci_quality": "unknown",
                    "interpretation_text": "", "strength_label": "unreviewed"}
    if es:
        try:
            result["practical_significance"] = classify_effect_size(float(re.findall(r'[-+]?\d*\.?\d+', es)[0]))
        except (ValueError, IndexError):
            pass
    if es and ci:
        result["ci_quality"] = assess_ci_quality(es, ci)
    if "APPROVED" in str(stat_review):
        result["strength_label"] = ("robust" if robust and robust.lower() == "yes"
                                    else "fragile" if robust and robust.lower() == "no"
                                    else "reviewed")
    elif "REJECTED" in str(stat_review):
        result["strength_label"] = "rejected"
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
# Claim-Evidence Registry I/O
# ---------------------------------------------------------------------------

@dataclass
class ClaimEvidence:
    claim_id: str
    claim_text: str
    finding_ids: list[str] = field(default_factory=list)
    hypothesis_ids: list[str] = field(default_factory=list)
    strength: str = "provisional"
    interpretation: str = ""


@dataclass
class ClaimEvidenceRegistry:
    claims: list[ClaimEvidence] = field(default_factory=list)
    orphan_findings: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    coverage_score: float = 0.0

    def add_claim(self, claim: ClaimEvidence) -> None:
        self.claims.append(claim)

    def audit(self, all_finding_ids: list[str]) -> None:
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
    path = workspace / ".swarm" / "claim-evidence.json"
    if not path.exists():
        return ClaimEvidenceRegistry()
    try:
        data = json.loads(path.read_text())
        if isinstance(data, list):
            data = {"claims": data}
        if not isinstance(data, dict):
            return ClaimEvidenceRegistry()
        reg = ClaimEvidenceRegistry(
            orphan_findings=data.get("orphan_findings", []),
            unsupported_claims=data.get("unsupported_claims", []),
            coverage_score=data.get("coverage_score", 0.0),
        )
        for c in data.get("claims", []):
            if isinstance(c, dict):
                reg.claims.append(ClaimEvidence(
                    claim_id=c.get("claim_id", ""), claim_text=c.get("claim_text", ""),
                    finding_ids=c.get("finding_ids", []), hypothesis_ids=c.get("hypothesis_ids", []),
                    strength=c.get("strength", "provisional"), interpretation=c.get("interpretation", ""),
                ))
        return reg
    except (json.JSONDecodeError, OSError, AttributeError, TypeError) as e:
        logger.warning("Failed to load claim-evidence registry: %s", e)
        return ClaimEvidenceRegistry()


def save_claim_evidence(workspace: Path, reg: ClaimEvidenceRegistry) -> None:
    path = workspace / ".swarm" / "claim-evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "claims": [asdict(c) for c in reg.claims],
        "orphan_findings": reg.orphan_findings,
        "unsupported_claims": reg.unsupported_claims,
        "coverage_score": reg.coverage_score,
    }, indent=2))


# ---------------------------------------------------------------------------
# Success Criteria helpers
# ---------------------------------------------------------------------------

def load_success_criteria(workspace: Path) -> list[dict]:
    path = workspace / ".swarm" / "success-criteria.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_success_criteria(workspace: Path, criteria: list[dict]) -> None:
    path = workspace / ".swarm" / "success-criteria.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(criteria, indent=2))
