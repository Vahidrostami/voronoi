"""Intent classifier for scientific questions.

Classifies free-text messages into Voronoi workflow modes and rigor levels,
matching the classification logic defined in DESIGN.md §3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class WorkflowMode(Enum):
    """Voronoi workflow modes — matches DESIGN.md §3."""
    BUILD = "build"
    INVESTIGATE = "investigate"
    EXPLORE = "explore"
    HYBRID = "hybrid"
    STATUS = "status"          # Meta: query swarm state
    RECALL = "recall"          # Meta: search knowledge store
    GUIDE = "guide"            # Meta: operator guidance


class RigorLevel(Enum):
    """Rigor levels — matches DESIGN.md §3."""
    STANDARD = "standard"
    ANALYTICAL = "analytical"
    SCIENTIFIC = "scientific"
    EXPERIMENTAL = "experimental"


@dataclass(frozen=True)
class ClassifiedIntent:
    """Result of intent classification."""
    mode: WorkflowMode
    rigor: RigorLevel
    confidence: float          # 0.0–1.0
    summary: str               # One-line description for the user
    original_text: str         # The raw input

    @property
    def is_science(self) -> bool:
        return self.mode in (WorkflowMode.INVESTIGATE, WorkflowMode.EXPLORE, WorkflowMode.HYBRID)

    @property
    def is_meta(self) -> bool:
        return self.mode in (WorkflowMode.STATUS, WorkflowMode.RECALL, WorkflowMode.GUIDE)


# ---------------------------------------------------------------------------
# Pattern banks — ordered by specificity (most specific first)
# ---------------------------------------------------------------------------

# Explicit command patterns (highest priority)
_COMMAND_PATTERNS: list[tuple[re.Pattern, WorkflowMode, Optional[RigorLevel]]] = [
    (re.compile(r"^/voronoi\s+status", re.I), WorkflowMode.STATUS, None),
    (re.compile(r"^/voronoi\s+tasks", re.I), WorkflowMode.STATUS, None),
    (re.compile(r"^/voronoi\s+ready", re.I), WorkflowMode.STATUS, None),
    (re.compile(r"^/voronoi\s+recall\b", re.I), WorkflowMode.RECALL, None),
    (re.compile(r"^/voronoi\s+investigate\b", re.I), WorkflowMode.INVESTIGATE, RigorLevel.SCIENTIFIC),
    (re.compile(r"^/voronoi\s+explore\b", re.I), WorkflowMode.EXPLORE, RigorLevel.ANALYTICAL),
    (re.compile(r"^/voronoi\s+build\b", re.I), WorkflowMode.BUILD, RigorLevel.STANDARD),
    (re.compile(r"^/voronoi\s+experiment\b", re.I), WorkflowMode.INVESTIGATE, RigorLevel.EXPERIMENTAL),
    (re.compile(r"^/voronoi\s+guide\b", re.I), WorkflowMode.GUIDE, None),
    (re.compile(r"^/voronoi\s+pivot\b", re.I), WorkflowMode.GUIDE, None),
]

# Scientific investigation signals
_INVESTIGATE_SIGNALS = [
    r"\bwhy\b.*\b(is|are|did|does|was|were|do|has|have)\b",
    r"\broot\s*cause\b",
    r"\bwhat\s+caused\b",
    r"\binvestigat",
    r"\bdiagnos",
    r"\bhypothes[ie]s",
    r"\bcorrelat",
    r"\bcausal",
    r"\bregress",     # regression analysis context
    r"\bwhat\s+explains?\b",
    r"\bwhy\s+is\s+\w+\s+(dropping|increasing|failing|crashing|slow)",
    r"\bfigure\s+out\b.*\bwhy\b",
    r"\bdetermine\s+(the\s+)?cause\b",
]

# Exploration signals
_EXPLORE_SIGNALS = [
    r"\bwhich\b.*\b(should|best|better|versus|vs\.?)\b",
    r"\bcompare\b",
    r"\bcomparison\b",
    r"\bevaluat",
    r"\boptions?\s+(for|to)\b",
    r"\btrade.?off",
    r"\bpros?\s+(and|&)\s+cons?\b",
    r"\balternativ",
    r"\bbenchmark",
    r"\bwhat\s+(are|is)\s+(the\s+)?(best|top|recommended)",
]

# Experimental signals (highest rigor)
_EXPERIMENTAL_SIGNALS = [
    r"\btest\s+whether\b",
    r"\bexperiment\b",
    r"\ba/?b\s+test\b",
    r"\bcontrolled?\s+(trial|experiment|test)",
    r"\bstatistical\s+(power|significance|test)",
    r"\brandomiz",
    r"\bplacebo\b",
    r"\bdouble.?blind",
    r"\breplicate\b",
    r"\breproducib",
    r"\bsample\s+size\b",
    r"\bsignificance\b",
]

# Analytical signals (elevated rigor for build/explore)
_ANALYTICAL_SIGNALS = [
    r"\boptimiz",
    r"\bimprov",
    r"\bperformanc",
    r"\bmeasur",
    r"\bquantif",
    r"\bmetric",
    r"\bstatistic",
    r"\banalyz",
    r"\banalysi",
    r"\beffect\s+size\b",
    r"\bconfidence\s+interval\b",
    r"\bsample\s+size\b",
]

# Build signals
_BUILD_SIGNALS = [
    r"\bbuild\b",
    r"\bcreate\b",
    r"\bimplement\b",
    r"\bship\b",
    r"\bdeploy\b",
    r"\bscaffold\b",
    r"\bwrite\s+(a|the|some)\b",
    r"\bset\s+up\b",
    r"\bconfigure\b",
    r"\binstall\b",
    r"\brefactor\b",
    r"\bmigrat",
]

# Hybrid signals (investigate + build)
_HYBRID_SIGNALS = [
    r"\bfigure\s+out\b.*\b(and|then)\s+(fix|build|implement)\b",
    r"\bdiagnose\b.*\b(and|then)\s+(fix|resolve)\b",
    r"\bfind\b.*\b(and|then)\s+(fix|patch)\b",
    r"\bwhy\b.*\band\b.*\bfix\b",
    r"\bdebug\s+and\s+(fix|resolve)\b",
    r"\bwrite\s+(a\s+)?(research\s+)?paper\b",
    r"\bgenerate\s+(a\s+)?paper\b",
    r"\bdraft\s+(a\s+)?paper\b",
    r"\bpaper\s+(on|about|for)\b",
    r"\bwrite\s+(a\s+)?(research\s+)?manuscript\b",
    r"\bdraft\s+(a\s+)?manuscript\b",
    r"\bmanuscript\s+(on|about|for)\b",
    r"\babstract\s*:?\s*.{20,}",
]

# Recall/knowledge-query signals
_RECALL_SIGNALS = [
    r"\bwhat\s+did\s+we\s+(learn|find|discover)\b",
    r"\brecall\b",
    r"\bprevious\s+(finding|result|experiment)",
    r"\blast\s+time\b.*\b(we|found|learned)\b",
    r"\bknowledge\b.*\b(store|base)\b",
    r"\bhistory\s+of\b",
    r"\bwhat\s+do\s+we\s+know\s+about\b",
]


def _count_matches(text: str, patterns: list[str]) -> int:
    """Count how many patterns match in the text."""
    return sum(1 for p in patterns if re.search(p, text, re.I))


def classify(text: str) -> ClassifiedIntent:
    """Classify a free-text message into a Voronoi workflow intent.

    Priority order:
    1. Explicit /voronoi commands (highest confidence)
    2. Pattern-based classification with signal counting
    3. Default to GUIDE (lowest confidence)
    """
    text = text.strip()
    if not text:
        return ClassifiedIntent(
            mode=WorkflowMode.GUIDE,
            rigor=RigorLevel.STANDARD,
            confidence=0.0,
            summary="Empty message",
            original_text=text,
        )

    # 1. Check explicit commands
    for pattern, mode, rigor in _COMMAND_PATTERNS:
        if pattern.search(text):
            # Extract the payload after the command
            payload = pattern.sub("", text).strip()
            return ClassifiedIntent(
                mode=mode,
                rigor=rigor or RigorLevel.STANDARD,
                confidence=1.0,
                summary=payload or f"{mode.value} command",
                original_text=text,
            )

    # 2. Pattern-based classification
    scores: dict[WorkflowMode, int] = {
        WorkflowMode.INVESTIGATE: _count_matches(text, _INVESTIGATE_SIGNALS),
        WorkflowMode.EXPLORE: _count_matches(text, _EXPLORE_SIGNALS),
        WorkflowMode.BUILD: _count_matches(text, _BUILD_SIGNALS),
        WorkflowMode.HYBRID: _count_matches(text, _HYBRID_SIGNALS),
        WorkflowMode.RECALL: _count_matches(text, _RECALL_SIGNALS),
    }

    # Experimental signals boost investigation score (experiments are investigations)
    experimental_score = _count_matches(text, _EXPERIMENTAL_SIGNALS)
    scores[WorkflowMode.INVESTIGATE] += experimental_score

    # Hybrid check first (it's a combination)
    if scores[WorkflowMode.HYBRID] > 0:
        rigor = RigorLevel.SCIENTIFIC
        return ClassifiedIntent(
            mode=WorkflowMode.HYBRID,
            rigor=rigor,
            confidence=min(0.6 + scores[WorkflowMode.HYBRID] * 0.15, 0.95),
            summary=_make_summary(text),
            original_text=text,
        )

    # Find best non-hybrid mode
    best_mode = max(
        [WorkflowMode.INVESTIGATE, WorkflowMode.EXPLORE, WorkflowMode.BUILD, WorkflowMode.RECALL],
        key=lambda m: scores[m],
    )
    best_score = scores[best_mode]

    if best_score == 0:
        # No strong signals — default to GUIDE
        return ClassifiedIntent(
            mode=WorkflowMode.GUIDE,
            rigor=RigorLevel.STANDARD,
            confidence=0.3,
            summary=_make_summary(text),
            original_text=text,
        )

    # Determine rigor level
    rigor = _determine_rigor(text, best_mode)

    # Confidence based on signal strength
    confidence = min(0.5 + best_score * 0.15, 0.95)

    return ClassifiedIntent(
        mode=best_mode,
        rigor=rigor,
        confidence=confidence,
        summary=_make_summary(text),
        original_text=text,
    )


def _determine_rigor(text: str, mode: WorkflowMode) -> RigorLevel:
    """Determine rigor level for a classified mode.

    DESIGN.md §3: "When in doubt, classify higher."
    """
    experimental_score = _count_matches(text, _EXPERIMENTAL_SIGNALS)
    if experimental_score > 0:
        return RigorLevel.EXPERIMENTAL

    analytical_score = _count_matches(text, _ANALYTICAL_SIGNALS)

    if mode == WorkflowMode.INVESTIGATE:
        # Investigations default to Scientific
        return RigorLevel.SCIENTIFIC
    elif mode == WorkflowMode.EXPLORE:
        # Explorations default to Analytical
        return RigorLevel.ANALYTICAL
    elif mode == WorkflowMode.RECALL:
        return RigorLevel.STANDARD
    elif mode == WorkflowMode.BUILD:
        if analytical_score > 0:
            return RigorLevel.ANALYTICAL
        return RigorLevel.STANDARD
    else:
        return RigorLevel.STANDARD


def _make_summary(text: str, max_len: int = 80) -> str:
    """Create a short summary from the input text."""
    # Strip /voronoi prefix if present
    cleaned = re.sub(r"^/voronoi\s*", "", text, flags=re.I).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len - 3] + "..."
