"""Citation-coverage gate — fuzzy-match citation integrity for manuscripts.

Enforces that every verified
citation candidate in ``.swarm/manuscript/citation-ledger.json`` is actually
``\\cite``-d in the compiled ``paper.tex``, and every ``\\cite{key}`` resolves
to a verified ledger entry. The required integration rate is 0.90 by default.

This module uses only the Python standard library — ``difflib.SequenceMatcher``
provides the Levenshtein-like fuzzy match. No new runtime dependency.

Public API
----------
fuzzy_match_title(a, b, threshold=0.70) -> bool
check_coverage(ledger_path, paper_tex_path, *, target=0.90) -> CoverageResult
write_coverage_audit(result, out_path) -> Path
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TITLE_THRESHOLD: float = 0.70
DEFAULT_COVERAGE_TARGET: float = 0.90

# Matches \cite{key}, \citep{key}, \citet{key}, \citeauthor{key} etc,
# and multi-key forms \cite{a,b,c}. Captures the inside of the braces.
_CITE_RE = re.compile(r"\\cite[a-zA-Z]*\{([^}]+)\}")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CoverageResult:
    """Result of a citation-coverage audit.

    Fields
    ------
    integration_rate : float
        Fraction of verified ledger entries that were ``\\cite``-d in the paper.
        ``integrated_count / verified_count``. ``1.0`` when ``verified_count == 0``.
    verified_count : int
        Number of ledger entries with ``verified == True``.
    integrated_count : int
        Number of verified ledger entries that appear as a ``\\cite{key}`` in
        the paper.
    unintegrated_keys : list[str]
        Verified ledger ``bibtex_key``s that never appear in the paper.
    orphan_cites : list[str]
        ``\\cite{...}`` keys in the paper that have no verified ledger entry.
        These are potential hallucinations and must be fixed.
    target : float
        The required integration rate (default 0.90).
    passes : bool
        ``True`` iff ``integration_rate >= target`` AND ``orphan_cites`` is empty.
    """

    integration_rate: float
    verified_count: int
    integrated_count: int
    unintegrated_keys: list[str] = field(default_factory=list)
    orphan_cites: list[str] = field(default_factory=list)
    target: float = DEFAULT_COVERAGE_TARGET

    @property
    def passes(self) -> bool:
        return self.integration_rate >= self.target and not self.orphan_cites

    def to_dict(self) -> dict:
        d = asdict(self)
        d["passes"] = self.passes
        return d


# ---------------------------------------------------------------------------
# Fuzzy match
# ---------------------------------------------------------------------------

def _normalize_title(s: str) -> str:
    # Lowercase, collapse whitespace, strip non-alphanum-space.
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fuzzy_match_title(a: str, b: str, threshold: float = DEFAULT_TITLE_THRESHOLD) -> bool:
    """Return True when two titles are similar enough to treat as the same paper.

    Uses ``difflib.SequenceMatcher.ratio()`` which is a Levenshtein-like
    similarity in ``[0, 1]``. Empty inputs always return ``False``.

    The spec is "Levenshtein > 70" (on a 0–100 scale). We map that
    to ``ratio() >= 0.70``. Titles are normalised (lowercase, whitespace
    collapsed, punctuation stripped) before comparison to avoid false negatives
    from trivial formatting differences.
    """
    if not a or not b:
        return False
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return False
    return SequenceMatcher(None, na, nb).ratio() >= threshold


# ---------------------------------------------------------------------------
# Coverage gate
# ---------------------------------------------------------------------------

# Matches verbatim-like environments whose content should not be scanned.
_VERBATIM_RE = re.compile(
    r"\\begin\{(verbatim|lstlisting|minted)\}.*?\\end\{\1\}",
    re.DOTALL,
)


def _strip_latex_comments(tex: str) -> str:
    """Remove LaTeX comment lines and verbatim-like environments.

    A LaTeX comment is any text from an *unescaped* ``%`` to end-of-line.
    Content inside ``verbatim``, ``lstlisting``, and ``minted`` environments
    is also removed so that example ``\\cite`` keys are not counted.
    """
    # 1. Strip verbatim-like blocks first (they may contain %-lines).
    tex = _VERBATIM_RE.sub("", tex)
    # 2. Remove comment portions: unescaped % to EOL.
    #    (?<!\\) ensures we don't strip \% (escaped percent).
    tex = re.sub(r"(?<!\\)%.*", "", tex)
    return tex


def extract_cite_keys(tex: str) -> set[str]:
    """Extract every ``\\cite*{key}`` key from a LaTeX source string.

    Handles multi-key forms ``\\cite{a,b,c}`` and whitespace inside braces.
    LaTeX comments (``%``-lines) and verbatim-like environments are stripped
    before extraction so that commented-out or example citations are ignored.
    """
    tex = _strip_latex_comments(tex)
    keys: set[str] = set()
    for group in _CITE_RE.findall(tex):
        for k in group.split(","):
            k = k.strip()
            if k:
                keys.add(k)
    return keys


def check_coverage(
    ledger_path: str | Path,
    paper_tex_path: str | Path,
    *,
    target: float = DEFAULT_COVERAGE_TARGET,
) -> CoverageResult:
    """Run the citation-coverage audit.

    Parameters
    ----------
    ledger_path : str | Path
        Path to ``.swarm/manuscript/citation-ledger.json`` (as produced by the
        Lit-Synthesizer agent). Must contain a top-level ``entries`` list where
        each entry has at least ``bibtex_key`` and ``verified``.
    paper_tex_path : str | Path
        Path to ``paper.tex``.
    target : float
        Required integration rate. Default 0.90.

    Returns
    -------
    CoverageResult

    Raises
    ------
    FileNotFoundError
        If either input file is missing.
    ValueError
        If the ledger JSON is malformed or missing required keys.
    """
    ledger_path = Path(ledger_path)
    paper_tex_path = Path(paper_tex_path)

    if not ledger_path.is_file():
        raise FileNotFoundError(f"citation ledger not found: {ledger_path}")
    if not paper_tex_path.is_file():
        raise FileNotFoundError(f"paper.tex not found: {paper_tex_path}")

    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"citation ledger is not valid JSON: {e}") from e

    entries = ledger.get("entries")
    if not isinstance(entries, list):
        raise ValueError("citation ledger missing top-level 'entries' list")

    verified_keys: set[str] = set()
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("verified") is not True:
            continue
        key = e.get("bibtex_key")
        if not isinstance(key, str) or not key.strip():
            continue
        verified_keys.add(key.strip())

    tex = paper_tex_path.read_text(encoding="utf-8", errors="replace")
    cited_keys = extract_cite_keys(tex)

    integrated_keys = verified_keys & cited_keys
    unintegrated = sorted(verified_keys - cited_keys)
    orphans = sorted(cited_keys - verified_keys)

    verified_count = len(verified_keys)
    integrated_count = len(integrated_keys)
    rate = 1.0 if verified_count == 0 else integrated_count / verified_count

    return CoverageResult(
        integration_rate=round(rate, 4),
        verified_count=verified_count,
        integrated_count=integrated_count,
        unintegrated_keys=unintegrated,
        orphan_cites=orphans,
        target=target,
    )


def write_coverage_audit(result: CoverageResult, out_path: str | Path) -> Path:
    """Persist a CoverageResult to ``.swarm/manuscript/coverage-audit.json``."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return out_path
