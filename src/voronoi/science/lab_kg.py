"""Lab-wide Knowledge Graph — per-PI institutional memory across investigations.

While the Claim Ledger (``claims.py``) is scoped to a single *lineage* of
investigations, the Lab-KG accumulates snapshots of ledger claims, dead ends,
and known artifact-traps across **every** lineage a single scientist runs.
The 100th investigation becomes structurally smarter than the 1st.

Scope: **per-PI**.  Storage lives at ``~/.voronoi/lab/kg/kg.json`` (overridable
via the ``VORONOI_LAB_KG_PATH`` environment variable).  Cross-lab sharing is
explicit opt-in (not implemented in this module — out of scope).

Safeguards against contamination and groupthink (see ``docs/INVARIANTS.md``
INV-53 and ``docs/SCIENCE.md`` §23):

  * Every KG entry preserves the Claim Ledger *provenance tag*
    (``model_prior`` / ``retrieved_prior`` / ``run_evidence``).  Callers that
    inject KG context into prompts MUST NOT elevate an entry's trust beyond
    what its provenance + status justify.
  * Only ``locked``, ``replicated``, or ``retired`` claims are injected into
    future Scout/Theorist prompts as priors.  ``provisional`` and ``asserted``
    are retained for queries but flagged as "not yet durable".
  * Every entry records the set of lineages that have challenged it
    (``dissent``).  A claim with unresolved dissent is surfaced alongside its
    objections — never as a bare fact.
  * Every ``locked`` or ``replicated`` entry carries a ``half_life_due`` ISO
    timestamp.  When queried after that date, the KG marks the entry
    ``stale=True`` and callers MUST re-examine rather than trust.
  * Dead ends (failed hypotheses, known artifacts, methodology traps) are a
    first-class entity — searchable, never lost to scientist memory.

This module is deliberately minimal: read/write/query.  It does NOT wire into
the dispatcher or prompt builder yet; those are separate follow-ups with their
own spec sections.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .claims import (
    PROVENANCE_MODEL_PRIOR,
    PROVENANCE_RETRIEVED_PRIOR,
    PROVENANCE_RUN_EVIDENCE,
    STATUS_ASSERTED,
    STATUS_CHALLENGED,
    STATUS_LOCKED,
    STATUS_PROVISIONAL,
    STATUS_REPLICATED,
    STATUS_RETIRED,
    VALID_PROVENANCES,
    VALID_STATUSES,
    Claim,
    ClaimLedger,
)

logger = logging.getLogger("voronoi.science.lab_kg")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Durable statuses whose content may be injected into future prompts as priors.
DURABLE_STATUSES = frozenset({STATUS_LOCKED, STATUS_REPLICATED})

#: Half-life — how long a durable claim is trusted before forced re-examination.
DEFAULT_HALF_LIFE_DAYS = 180

#: Ambiguity-aware word tokenizer for the lightweight keyword query.
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}")

#: Common stop-words ignored by the query matcher.
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "are", "was", "were",
    "has", "have", "been", "our", "their", "from", "into", "when", "what",
    "why", "how", "which", "does", "can", "but", "not", "all", "any",
    "some", "one", "two", "more", "most", "over", "about", "these",
    "those", "them", "they", "there", "than", "then", "will", "would",
    "could", "should", "may", "might",
})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _half_life_due(days: int = DEFAULT_HALF_LIFE_DAYS) -> str:
    return (_now() + timedelta(days=days)).isoformat(timespec="seconds")


def _tokens(text: str) -> set[str]:
    """Lower-cased content words, min length 3, stop-words removed."""
    if not text:
        return set()
    return {
        m.group(0).lower()
        for m in _WORD_RE.finditer(text)
        if m.group(0).lower() not in _STOPWORDS
    }


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LabEntry:
    """A claim snapshot in the Lab-KG.

    This mirrors a ``Claim`` from ``claims.py`` but adds cross-lineage fields
    (``supporting_lineages``, ``replicated_in``, ``dissent``) and durability
    metadata (``half_life_due``, ``stale_as_of_query``).
    """

    id: str                                # Lab-KG id, e.g. "L17"
    statement: str
    provenance: str                        # model_prior | retrieved_prior | run_evidence
    status: str                            # any VALID_STATUSES value
    source_lineage: str                    # lineage where first seen
    source_claim_id: str                   # original claim id in that ledger
    supporting_lineages: list[str] = field(default_factory=list)
    replicated_in: list[str] = field(default_factory=list)
    dissent: list[str] = field(default_factory=list)  # lineages that challenged this
    effect_summary: str | None = None
    artifact_paths: list[str] = field(default_factory=list)
    first_recorded: str = field(default_factory=_now_iso)
    last_updated: str = field(default_factory=_now_iso)
    half_life_due: str | None = None       # set only for durable statuses

    # Query-time only — not persisted.
    stale_as_of_query: bool = False

    def __post_init__(self) -> None:
        if self.provenance not in VALID_PROVENANCES:
            raise ValueError(f"Invalid provenance: {self.provenance!r}")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {self.status!r}")


@dataclass
class DeadEnd:
    """A recorded dead end — failed hypothesis, artifact-trap, methodology pitfall.

    Searchable across investigations so future Scouts/Theorists can avoid the
    same trap.  Never expires (dead ends are evergreen; the reason a path
    failed 5 years ago is usually still informative)."""

    id: str
    lineage: str
    description: str
    reason: str
    category: str                          # artifact | hypothesis | method | data | other
    recorded: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        valid = {"artifact", "hypothesis", "method", "data", "other"}
        if self.category not in valid:
            raise ValueError(f"Invalid dead-end category: {self.category!r}")


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def default_store_path() -> Path:
    """Resolve the per-PI Lab-KG JSON path.

    Overridable via ``VORONOI_LAB_KG_PATH`` (used by tests and by operators
    who want to segregate KGs by project or persona).
    """
    override = os.environ.get("VORONOI_LAB_KG_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".voronoi" / "lab" / "kg" / "kg.json"


class LabKG:
    """Per-PI knowledge graph of durable claims and dead ends across lineages.

    The store is a single JSON file.  Writes are full-file rewrites (atomic
    via ``os.replace``).  Concurrent access from two simultaneous investigations
    is acceptable-risk today: the last writer wins.  Entries are idempotent —
    a re-insert of an existing ``(source_lineage, source_claim_id)`` pair
    updates in place, it does not duplicate.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: Path | None = None) -> None:
        self.path: Path = Path(path) if path is not None else default_store_path()
        self.entries: list[LabEntry] = []
        self.dead_ends: list[DeadEnd] = []
        self._next_entry_id: int = 1
        self._next_dead_end_id: int = 1

    # -- Persistence ------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "LabKG":
        kg = cls(path)
        if not kg.path.exists():
            return kg
        try:
            raw = json.loads(kg.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
            logger.warning("Lab-KG unreadable at %s (%s); starting fresh", kg.path, exc)
            return kg
        kg.entries = [_entry_from_dict(e) for e in raw.get("entries", []) if _entry_valid(e)]
        kg.dead_ends = [_dead_end_from_dict(d) for d in raw.get("dead_ends", []) if _dead_end_valid(d)]
        kg._next_entry_id = max(
            (int(e.id[1:]) for e in kg.entries if e.id.startswith("L") and e.id[1:].isdigit()),
            default=0,
        ) + 1
        kg._next_dead_end_id = max(
            (int(d.id[2:]) for d in kg.dead_ends if d.id.startswith("DE") and d.id[2:].isdigit()),
            default=0,
        ) + 1
        return kg

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "entries": [_entry_to_dict(e) for e in self.entries],
            "dead_ends": [asdict(d) for d in self.dead_ends],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    # -- Upsert -----------------------------------------------------------

    def upsert_from_ledger(self, lineage_id: str, ledger: ClaimLedger) -> list[LabEntry]:
        """Snapshot *ledger* into the KG under *lineage_id*.

        Returns the list of entries touched (created or updated).  Only claims
        with ``supporting_findings`` or ``status in DURABLE_STATUSES`` are
        considered — ``provisional`` claims backed by nothing are ignored to
        keep the KG free of hunches.

        Replication detection: when a claim with matching normalized statement
        already exists under a different ``source_lineage``, the new
        ``lineage_id`` is added to ``replicated_in`` and, if the incoming
        claim is locked, the KG entry is promoted to ``replicated``.
        """
        if not lineage_id:
            raise ValueError("lineage_id is required")

        touched: list[LabEntry] = []
        for claim in ledger.claims:
            if claim.status == STATUS_RETIRED:
                # Retired claims are still useful memory — record them, but
                # never as durable priors.  Skip the empty-hunch filter for
                # retirees since the PI explicitly marked them.
                pass
            elif claim.status not in DURABLE_STATUSES and not claim.supporting_findings:
                continue

            existing = self._match(claim)
            if existing is None:
                touched.append(self._create_entry(lineage_id, claim))
            else:
                touched.append(self._merge_entry(existing, lineage_id, claim))
        return touched

    def record_dead_end(
        self,
        lineage_id: str,
        description: str,
        reason: str,
        category: str = "other",
    ) -> DeadEnd:
        """Record a dead end — a path tried and rejected, so future runs can
        check before re-walking it."""
        if not description or not reason:
            raise ValueError("dead-end requires non-empty description and reason")
        de = DeadEnd(
            id=f"DE{self._next_dead_end_id}",
            lineage=lineage_id,
            description=description,
            reason=reason,
            category=category,
        )
        self._next_dead_end_id += 1
        self.dead_ends.append(de)
        return de

    # -- Query ------------------------------------------------------------

    def query(
        self,
        topic: str,
        *,
        limit: int = 20,
        include_non_durable: bool = False,
    ) -> list[LabEntry]:
        """Return entries relevant to *topic*, ranked by keyword overlap.

        Groupthink safeguard: by default only ``durable`` entries (locked or
        replicated) are returned as *priors*.  Callers that want to see
        provisional/asserted hits for broader context must set
        ``include_non_durable=True`` — and MUST present them to downstream
        agents as "prior attempts, unsettled", never as established facts.

        Stale detection: entries whose ``half_life_due`` is in the past are
        returned with ``stale_as_of_query=True``.  Callers SHOULD render
        these as "trusted in the past — re-examine before relying on them".
        """
        query_tokens = _tokens(topic)
        if not query_tokens:
            return []

        candidates = (
            self.entries
            if include_non_durable
            else [e for e in self.entries if e.status in DURABLE_STATUSES]
        )

        now = _now()
        ranked: list[tuple[int, LabEntry]] = []
        for e in candidates:
            score = len(_tokens(e.statement) & query_tokens)
            if e.effect_summary:
                score += len(_tokens(e.effect_summary) & query_tokens)
            if score <= 0:
                continue
            # Mutate a shallow copy's stale flag to avoid polluting stored state.
            stale = _is_stale(e, now)
            entry_view = _with_stale(e, stale)
            ranked.append((score, entry_view))

        # Primary: highest score first.  Secondary (stable): most recent first.
        ranked.sort(key=lambda t: t[1].last_updated, reverse=True)
        ranked.sort(key=lambda t: t[0], reverse=True)
        return [e for _, e in ranked[:limit]]

    def query_dead_ends(self, topic: str, *, limit: int = 20) -> list[DeadEnd]:
        tokens = _tokens(topic)
        if not tokens:
            return []
        scored: list[tuple[int, DeadEnd]] = []
        for de in self.dead_ends:
            score = len(_tokens(de.description) & tokens) + len(_tokens(de.reason) & tokens)
            if score > 0:
                scored.append((score, de))
        scored.sort(key=lambda t: t[1].recorded, reverse=True)
        scored.sort(key=lambda t: t[0], reverse=True)
        return [d for _, d in scored[:limit]]

    def get_dissent(self, entry_id: str) -> list[str]:
        """Return the list of lineages that challenged *entry_id*."""
        for e in self.entries:
            if e.id == entry_id:
                return list(e.dissent)
        return []

    # -- Rendering --------------------------------------------------------

    def format_brief(
        self,
        topic: str,
        *,
        limit: int = 10,
        include_non_durable: bool = False,
    ) -> str:
        """Produce a *Lab Context Brief* for injection into Scout/Theorist prompts.

        The brief is explicitly framed **adversarially**: priors are presented
        as hypotheses to challenge, not facts to accept.  Dead ends are
        presented as traps to check against, not boundaries.

        If nothing matches, returns the empty string (caller should omit the
        section rather than injecting "no matches")."""
        hits = self.query(topic, limit=limit, include_non_durable=include_non_durable)
        dead_ends = self.query_dead_ends(topic, limit=limit)
        if not hits and not dead_ends:
            return ""

        lines: list[str] = [
            "### Lab Context Brief — prior attempts across this PI's investigations",
            "",
            "**Treat every entry below as a hypothesis to challenge, not a fact to accept.**",
            "Always run fresh external `/research` before trusting any lab-KG item.",
            "",
        ]
        if hits:
            lines.append("**Prior claims** (provenance + status shown; `⚠` = stale, re-examine):")
            for e in hits:
                stale = " ⚠ stale" if e.stale_as_of_query else ""
                dissent = f" [dissent from {len(e.dissent)} lineage(s)]" if e.dissent else ""
                replicated = (
                    f" ✓ replicated in {len(e.replicated_in)}" if e.replicated_in else ""
                )
                eff = f" — {e.effect_summary}" if e.effect_summary else ""
                lines.append(
                    f"- [{e.status}/{e.provenance}] {e.id}: {e.statement}{eff}"
                    f"{replicated}{dissent}{stale}"
                )
            lines.append("")
        if dead_ends:
            lines.append("**Recorded dead ends** (paths tried and rejected — verify they still apply before avoiding):")
            for d in dead_ends:
                lines.append(f"- [{d.category}] {d.description} — {d.reason} ({d.lineage})")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    # -- Internals --------------------------------------------------------

    def _match(self, claim: Claim) -> LabEntry | None:
        """Find an existing entry whose normalized statement matches *claim*."""
        normalized = _normalize(claim.statement)
        for e in self.entries:
            if _normalize(e.statement) == normalized:
                return e
        return None

    def _create_entry(self, lineage_id: str, claim: Claim) -> LabEntry:
        status = claim.status
        entry = LabEntry(
            id=f"L{self._next_entry_id}",
            statement=claim.statement,
            provenance=claim.provenance,
            status=status,
            source_lineage=lineage_id,
            source_claim_id=claim.id,
            supporting_lineages=[lineage_id],
            replicated_in=[],
            dissent=[],
            effect_summary=claim.effect_summary,
            artifact_paths=[a.path for a in claim.artifacts],
            half_life_due=_half_life_due() if status in DURABLE_STATUSES else None,
        )
        self._next_entry_id += 1
        self.entries.append(entry)
        return entry

    def _merge_entry(
        self,
        entry: LabEntry,
        lineage_id: str,
        claim: Claim,
    ) -> LabEntry:
        if lineage_id not in entry.supporting_lineages:
            entry.supporting_lineages.append(lineage_id)

        # Replication: same statement reappearing under a NEW lineage
        # (i.e. not the one that originally created this entry) as durable
        # evidence is replication — promote and record.
        if (
            lineage_id != entry.source_lineage
            and claim.status in DURABLE_STATUSES
            and lineage_id not in entry.replicated_in
        ):
            entry.replicated_in.append(lineage_id)
            if entry.status == STATUS_LOCKED:
                entry.status = STATUS_REPLICATED

        # Dissent: this lineage challenged the claim
        if claim.status == STATUS_CHALLENGED and lineage_id not in entry.dissent:
            entry.dissent.append(lineage_id)

        # Retirement: if any lineage retires the claim, reflect it
        if claim.status == STATUS_RETIRED:
            entry.status = STATUS_RETIRED

        # Promote provenance if run_evidence has been seen (stronger than model_prior)
        if claim.provenance == PROVENANCE_RUN_EVIDENCE:
            entry.provenance = PROVENANCE_RUN_EVIDENCE
        elif claim.provenance == PROVENANCE_RETRIEVED_PRIOR and entry.provenance == PROVENANCE_MODEL_PRIOR:
            entry.provenance = PROVENANCE_RETRIEVED_PRIOR

        # Status elevation (monotonic within a single merge): provisional <
        # asserted < locked < replicated.  Never downgrade here — PI demotions
        # happen via retirement or challenge.
        if _status_rank(claim.status) > _status_rank(entry.status) and claim.status != STATUS_RETIRED:
            entry.status = claim.status

        if entry.status in DURABLE_STATUSES and entry.half_life_due is None:
            entry.half_life_due = _half_life_due()

        if claim.effect_summary and not entry.effect_summary:
            entry.effect_summary = claim.effect_summary
        for art in claim.artifacts:
            if art.path not in entry.artifact_paths:
                entry.artifact_paths.append(art.path)
        entry.last_updated = _now_iso()
        return entry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_STATUS_ORDER = {
    STATUS_PROVISIONAL: 0,
    STATUS_ASSERTED: 1,
    STATUS_CHALLENGED: 1,
    STATUS_LOCKED: 2,
    STATUS_REPLICATED: 3,
    STATUS_RETIRED: -1,
}


def _status_rank(status: str) -> int:
    return _STATUS_ORDER.get(status, 0)


def _normalize(statement: str) -> str:
    return " ".join(statement.lower().split()).rstrip(".?!,; ")


def _is_stale(entry: LabEntry, now: datetime) -> bool:
    if entry.status not in DURABLE_STATUSES or not entry.half_life_due:
        return False
    try:
        due = datetime.fromisoformat(entry.half_life_due)
    except ValueError:  # pragma: no cover - defensive
        return False
    return due < now


def _with_stale(entry: LabEntry, stale: bool) -> LabEntry:
    # Copy with independent lists to avoid mutation leaks when the original
    # entry is updated after query results are returned.
    copy = LabEntry(
        id=entry.id,
        statement=entry.statement,
        provenance=entry.provenance,
        status=entry.status,
        source_lineage=entry.source_lineage,
        source_claim_id=entry.source_claim_id,
        supporting_lineages=list(entry.supporting_lineages),
        replicated_in=list(entry.replicated_in),
        dissent=list(entry.dissent),
        effect_summary=entry.effect_summary,
        artifact_paths=list(entry.artifact_paths),
        first_recorded=entry.first_recorded,
        last_updated=entry.last_updated,
        half_life_due=entry.half_life_due,
    )
    copy.stale_as_of_query = stale
    return copy


def _entry_to_dict(e: LabEntry) -> dict:
    d = asdict(e)
    d.pop("stale_as_of_query", None)  # transient
    return d


def _entry_from_dict(d: dict) -> LabEntry:
    known = {
        "id", "statement", "provenance", "status", "source_lineage",
        "source_claim_id", "supporting_lineages", "replicated_in", "dissent",
        "effect_summary", "artifact_paths", "first_recorded", "last_updated",
        "half_life_due",
    }
    return LabEntry(**{k: v for k, v in d.items() if k in known})


def _dead_end_from_dict(d: dict) -> DeadEnd:
    known = {"id", "lineage", "description", "reason", "category", "recorded"}
    return DeadEnd(**{k: v for k, v in d.items() if k in known})


def _entry_valid(d: dict) -> bool:
    try:
        return (
            d.get("provenance") in VALID_PROVENANCES
            and d.get("status") in VALID_STATUSES
            and bool(d.get("statement", "").strip())
        )
    except AttributeError:
        return False


def _dead_end_valid(d: dict) -> bool:
    try:
        return (
            d.get("category") in {"artifact", "hypothesis", "method", "data", "other"}
            and bool(d.get("description", "").strip())
            and bool(d.get("reason", "").strip())
        )
    except AttributeError:
        return False


# Re-export for test ergonomics
__all__ = [
    "DeadEnd",
    "DEFAULT_HALF_LIFE_DAYS",
    "DURABLE_STATUSES",
    "LabEntry",
    "LabKG",
    "default_store_path",
]
