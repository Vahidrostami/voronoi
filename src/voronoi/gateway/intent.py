"""Intent classifier for scientific questions.

Classifies free-text messages into Voronoi workflow modes:
- DISCOVER: open questions, adaptive rigor, creative exploration
- PROVE: specific hypotheses, full science gates from the start

Plus meta modes: STATUS, RECALL, GUIDE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class WorkflowMode(Enum):
    """Voronoi workflow modes — two science modes + five meta modes."""
    DISCOVER = "discover"      # Open question — adaptive rigor
    PROVE = "prove"            # Specific hypothesis — full science gates
    STATUS = "status"          # Meta: query swarm state
    RECALL = "recall"          # Meta: search knowledge store
    GUIDE = "guide"            # Meta: operator guidance
    ASK = "ask"                # Meta: question about a running investigation
    DELIBERATE = "deliberate"  # Meta: multi-turn Socratic reasoning about results


class RigorLevel(Enum):
    """Rigor levels for Voronoi investigations."""
    ADAPTIVE = "adaptive"            # DISCOVER — starts analytical, escalates
    SCIENTIFIC = "scientific"        # PROVE — full gates from the start
    EXPERIMENTAL = "experimental"    # PROVE + replication


#: PROVE classifications whose confidence is at or below this value are
#: treated as ambiguous by :func:`classify_for_new_investigation`.  The
#: router uses this to prompt the user to confirm PROVE (locks the question)
#: vs switch to DISCOVER (allows question refinement).  See INV-54.
PROVE_AMBIGUITY_THRESHOLD = 0.75


@dataclass(frozen=True)
class ClassifiedIntent:
    """Result of intent classification."""
    mode: WorkflowMode
    rigor: RigorLevel
    confidence: float          # 0.0–1.0
    summary: str               # One-line description for the user
    original_text: str         # The raw input
    # True when the classifier picked PROVE but confidence is borderline.
    # Surface a confirmation gate to the user before committing to fixed
    # rigor: the PROVE contract locks the question (INV-10, INV-54), which
    # is expensive to get wrong.
    ambiguous: bool = False

    @property
    def is_science(self) -> bool:
        return self.mode in (WorkflowMode.DISCOVER, WorkflowMode.PROVE)

    @property
    def is_meta(self) -> bool:
        return self.mode in (WorkflowMode.STATUS, WorkflowMode.RECALL,
                             WorkflowMode.GUIDE, WorkflowMode.ASK,
                             WorkflowMode.DELIBERATE)


# ---------------------------------------------------------------------------
# Pattern banks — ordered by specificity (most specific first)
# ---------------------------------------------------------------------------

# Explicit command patterns (highest priority)
_COMMAND_PATTERNS: list[tuple[re.Pattern, WorkflowMode, Optional[RigorLevel]]] = [
    (re.compile(r"^/voronoi\s+status", re.I), WorkflowMode.STATUS, None),
    (re.compile(r"^/voronoi\s+tasks", re.I), WorkflowMode.STATUS, None),
    (re.compile(r"^/voronoi\s+ready", re.I), WorkflowMode.STATUS, None),
    (re.compile(r"^/voronoi\s+recall\b", re.I), WorkflowMode.RECALL, None),
    (re.compile(r"^/voronoi\s+dead-ends\b", re.I), WorkflowMode.RECALL, None),
    (re.compile(r"^/voronoi\s+discover\b", re.I), WorkflowMode.DISCOVER, RigorLevel.ADAPTIVE),
    (re.compile(r"^/voronoi\s+prove\b", re.I), WorkflowMode.PROVE, RigorLevel.SCIENTIFIC),
    (re.compile(r"^/voronoi\s+guide\b", re.I), WorkflowMode.GUIDE, None),
    (re.compile(r"^/voronoi\s+pivot\b", re.I), WorkflowMode.GUIDE, None),
    (re.compile(r"^/voronoi\s+ask\b", re.I), WorkflowMode.ASK, None),
    (re.compile(r"^/voronoi\s+deliberate\b", re.I), WorkflowMode.DELIBERATE, None),
]

# PROVE signals — specific hypothesis, controlled experiments, structured validation
_PROVE_SIGNALS = [
    r"\btest\s+whether\b",
    r"\bprove\b",
    r"\bvalidat",
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
    r"\bpre.?regist",
    r"\bhypothesis\s*:\s*.{10,}",  # "hypothesis: <detailed statement>"
    r"\bh[0-9]\s*:",               # "H1: ...", "H0: ..."
    r"\bnull\s+hypothesis\b",
    r"\balternative\s+hypothesis\b",
]

# DISCOVER signals — open questions, exploration, building, investigation
_DISCOVER_SIGNALS = [
    r"\bwhy\b.*\b(is|are|did|does|was|were|do|has|have)\b",
    r"\broot\s*cause\b",
    r"\bwhat\s+caused\b",
    r"\binvestigat",
    r"\bdiagnos",
    r"\bhypothes[ie]s",
    r"\bcorrelat",
    r"\bcausal",
    r"\bregress",
    r"\bwhat\s+explains?\b",
    r"\bfigure\s+out\b",
    r"\bdetermine\s+(the\s+)?cause\b",
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
    r"\boptimiz",
    r"\bimprov",
    r"\bperformanc",
    r"\banalyz",
    r"\bwrite\s+(a\s+)?(research\s+)?paper\b",
    r"\bpaper\s+(on|about|for)\b",
    r"\bwrite\s+(a\s+)?(research\s+)?manuscript\b",
    r"\bmanuscript\s+(on|about|for)\b",
    r"\bfigure\s+out\b.*\b(and|then)\s+(fix|build|implement)\b",
    r"\bdiagnose\b.*\b(and|then)\s+(fix|resolve)\b",
    r"\bdebug\s+and\s+(fix|resolve)\b",
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

# ASK signals — questions about a currently running investigation's progress,
# findings, experiment results, or agent activity. These are NOT new science
# questions; they ask about what the agents have found/done so far.
_ASK_SIGNALS = [
    r"\bhow\s+(are|is)\s+(the|things|it)\s+(going|progressing|looking)\b",
    r"\bhow\s+(are|is)\s+the\s+(results?|findings?|experiments?|progress|investigation)\b",
    r"\bwhat\s+have\s+(the\s+)?(agents?|they|we)\s+(found|discovered|learned)\s+so\s+far\b",
    r"\bwhat\s+(are|is)\s+the\s+(current|latest)\s+(results?|findings?|status)\b",
    r"\bany\s+(new\s+|recent\s+|latest\s+)?(results?|findings?|progress)(\s+(yet|so\s+far))?\b",
    r"\bwhat\s+happened\s+with\b",
    r"\bwhy\s+did\s+(experiment|task|agent)\b.*\b(fail|crash|stop)\b",
    r"\bwhat\s+(does|do)\s+the\s+(data|results?|experiments?)\s+(show|say|suggest|indicate)\b",
    r"\bcan\s+you\s+(summarize|explain|tell\s+me)\b.*\b(findings?|results?|progress)\b",
    r"\b(show|tell)\s+me\s+(about|what)\b.*\b(so\s+far|current|latest|right\s+now)\b",
    r"\bwhat\s+did\s+(the\s+)?(experiment|agent|team)\s+(find|discover|show|produce)\b",
    r"\bare\s+(there|any)\s+(any\s+)?(results?|findings?|conclusions?)\b",
    r"\bwhich\s+(experiments?|classifiers?|models?)\s+(are|is|were|was)\s+(best|worst|failing|passing|showing)\b",
    r"\bupdate\s+(me|us)\s+(on|about)\b",
]

# DELIBERATE signals — multi-turn reasoning about results, brainstorming
_DELIBERATE_SIGNALS = [
    r"\bdeliberat",
    r"\bbrain\s*storm",
    r"\bthink\s+(through|about)\s+(the\s+)?(results?|findings?)\b",
    r"\bwhy\s+(does|do|did)\s+(this|these|the)\s+(results?|findings?)\s+(not\s+)?make\s+sense\b",
    r"\bdoesn.?t\s+make\s+sense\b",
    r"\bdon.?t\s+understand\s+(the\s+)?(results?|findings?)\b",
    r"\blet.?s\s+(reason|think|discuss)\s+(about|through)\b",
    r"\bwhat\s+(should|could)\s+we\s+(do|test|try)\s+next\b",
    r"\binterpret\s+(the\s+)?(results?|findings?)\b",
    r"\breview\s+(the\s+)?(results?|conclusions?|claims?)\s+(together|with\s+me)\b",
]


def _count_matches(text: str, patterns: list[str]) -> int:
    """Count how many patterns match in the text."""
    return sum(1 for p in patterns if re.search(p, text, re.I))


def classify(text: str) -> ClassifiedIntent:
    """Classify a free-text message into a Voronoi workflow intent.

    NOTE: For free-text routing, the router uses state-aware dispatch instead
    of this function directly. When an investigation is running, all free text
    routes to ASK. When nothing is running, classify_for_new_investigation()
    handles DISCOVER/PROVE/RECALL classification.

    This function is still used for:
    - Explicit /voronoi command parsing
    - Backward compatibility
    - Cases where state-awareness isn't available

    Priority order:
    1. Explicit /voronoi commands (highest confidence)
    2. ASK signals (mid-investigation questions)
    3. PROVE signals (specific hypothesis, controlled experiments)
    4. DISCOVER signals (open questions, building, exploring)
    5. Default to GUIDE (lowest confidence)
    """
    text = text.strip()
    if not text:
        return ClassifiedIntent(
            mode=WorkflowMode.GUIDE,
            rigor=RigorLevel.ADAPTIVE,
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
                rigor=rigor or RigorLevel.ADAPTIVE,
                confidence=1.0,
                summary=payload or f"{mode.value} command",
                original_text=text,
            )

    # 2. Check for PROVE signals first (specific hypothesis → full gates)
    prove_score = _count_matches(text, _PROVE_SIGNALS)
    discover_score = _count_matches(text, _DISCOVER_SIGNALS)
    recall_score = _count_matches(text, _RECALL_SIGNALS)
    ask_score = _count_matches(text, _ASK_SIGNALS)
    deliberate_score = _count_matches(text, _DELIBERATE_SIGNALS)

    # DELIBERATE — multi-turn reasoning about results
    if deliberate_score > 0 and deliberate_score >= ask_score:
        return ClassifiedIntent(
            mode=WorkflowMode.DELIBERATE,
            rigor=RigorLevel.ADAPTIVE,
            confidence=min(0.6 + deliberate_score * 0.15, 0.95),
            summary=_make_summary(text),
            original_text=text,
        )

    # ASK — mid-investigation questions about current progress/findings
    # Must dominate other signals to avoid misclassification
    if ask_score > 0 and ask_score >= discover_score and ask_score >= prove_score:
        return ClassifiedIntent(
            mode=WorkflowMode.ASK,
            rigor=RigorLevel.ADAPTIVE,
            confidence=min(0.6 + ask_score * 0.15, 0.95),
            summary=_make_summary(text),
            original_text=text,
        )

    # PROVE if strong prove signals dominate
    if prove_score >= 2 or (prove_score >= 1 and discover_score == 0):
        rigor = RigorLevel.EXPERIMENTAL if prove_score >= 3 else RigorLevel.SCIENTIFIC
        confidence = min(0.6 + prove_score * 0.15, 0.95)
        # PROVE locks the question (INV-10, INV-49).  Flag as ambiguous when
        # the signal is borderline so the router can surface a confirmation
        # gate.  Borderline means: confidence below threshold, OR the PROVE
        # signal count only narrowly beats the DISCOVER signal count.
        ambiguous = (
            confidence <= PROVE_AMBIGUITY_THRESHOLD
            or discover_score >= prove_score
        )
        return ClassifiedIntent(
            mode=WorkflowMode.PROVE,
            rigor=rigor,
            confidence=confidence,
            summary=_make_summary(text),
            original_text=text,
            ambiguous=ambiguous,
        )

    # Recall — only if recall signals strictly dominate discovery
    if recall_score > 0 and recall_score > discover_score:
        return ClassifiedIntent(
            mode=WorkflowMode.RECALL,
            rigor=RigorLevel.ADAPTIVE,
            confidence=min(0.5 + recall_score * 0.15, 0.95),
            summary=_make_summary(text),
            original_text=text,
        )

    # DISCOVER if any discover signals
    if discover_score > 0:
        return ClassifiedIntent(
            mode=WorkflowMode.DISCOVER,
            rigor=RigorLevel.ADAPTIVE,
            confidence=min(0.5 + discover_score * 0.15, 0.95),
            summary=_make_summary(text),
            original_text=text,
        )

    # No strong signals — default to GUIDE
    return ClassifiedIntent(
        mode=WorkflowMode.GUIDE,
        rigor=RigorLevel.ADAPTIVE,
        confidence=0.3,
        summary=_make_summary(text),
        original_text=text,
    )


def _determine_rigor(text: str, mode: WorkflowMode) -> RigorLevel:
    """Determine rigor level for a classified mode.

    PROVE → scientific or experimental.
    DISCOVER → always adaptive (orchestrator escalates dynamically).
    """
    prove_score = _count_matches(text, _PROVE_SIGNALS)
    if prove_score >= 3:
        return RigorLevel.EXPERIMENTAL
    if mode == WorkflowMode.PROVE:
        return RigorLevel.SCIENTIFIC
    return RigorLevel.ADAPTIVE


def _make_summary(text: str, max_len: int = 80) -> str:
    """Create a short summary from the input text."""
    # Strip /voronoi prefix if present
    cleaned = re.sub(r"^/voronoi\s*", "", text, flags=re.I).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len - 3] + "..."


# ---------------------------------------------------------------------------
# State-aware classifier for new investigations (no running investigation)
# ---------------------------------------------------------------------------

def classify_for_new_investigation(text: str) -> ClassifiedIntent:
    """Classify free text when NO investigation is running.

    Only distinguishes DISCOVER vs PROVE vs RECALL.
    Used by the state-aware router when no investigation is active.
    ASK and GUIDE are never returned — the router handles those via state.
    """
    text = text.strip()
    if not text:
        return ClassifiedIntent(
            mode=WorkflowMode.DISCOVER,
            rigor=RigorLevel.ADAPTIVE,
            confidence=0.0,
            summary="Empty message",
            original_text=text,
        )

    # Check explicit commands (still needed for /voronoi discover/prove in edge cases)
    for pattern, mode, rigor in _COMMAND_PATTERNS:
        if pattern.search(text):
            payload = pattern.sub("", text).strip()
            return ClassifiedIntent(
                mode=mode,
                rigor=rigor or RigorLevel.ADAPTIVE,
                confidence=1.0,
                summary=payload or f"{mode.value} command",
                original_text=text,
            )

    prove_score = _count_matches(text, _PROVE_SIGNALS)
    discover_score = _count_matches(text, _DISCOVER_SIGNALS)
    recall_score = _count_matches(text, _RECALL_SIGNALS)

    # PROVE if strong prove signals
    if prove_score >= 2 or (prove_score >= 1 and discover_score == 0):
        rigor = RigorLevel.EXPERIMENTAL if prove_score >= 3 else RigorLevel.SCIENTIFIC
        confidence = min(0.6 + prove_score * 0.15, 0.95)
        ambiguous = (
            confidence <= PROVE_AMBIGUITY_THRESHOLD
            or discover_score >= prove_score
        )
        return ClassifiedIntent(
            mode=WorkflowMode.PROVE,
            rigor=rigor,
            confidence=confidence,
            summary=_make_summary(text),
            original_text=text,
            ambiguous=ambiguous,
        )

    # Recall — if recall signals dominate discovery
    if recall_score > 0 and recall_score > discover_score:
        return ClassifiedIntent(
            mode=WorkflowMode.RECALL,
            rigor=RigorLevel.ADAPTIVE,
            confidence=min(0.5 + recall_score * 0.15, 0.95),
            summary=_make_summary(text),
            original_text=text,
        )

    # DISCOVER — any discover signal or a substantive message
    if discover_score > 0:
        return ClassifiedIntent(
            mode=WorkflowMode.DISCOVER,
            rigor=RigorLevel.ADAPTIVE,
            confidence=min(0.5 + discover_score * 0.15, 0.95),
            summary=_make_summary(text),
            original_text=text,
        )

    # Default: DISCOVER with low confidence (let router decide to prompt)
    return ClassifiedIntent(
        mode=WorkflowMode.DISCOVER,
        rigor=RigorLevel.ADAPTIVE,
        confidence=0.3,
        summary=_make_summary(text),
        original_text=text,
    )


# ---------------------------------------------------------------------------
# Compound / Phased Intent Detection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClassifiedPhase:
    """A single phase in a compound intent."""
    mode: WorkflowMode
    rigor: RigorLevel
    description: str
    order: int


# Phase boundary markers — patterns indicating a new phase
_PHASE_BOUNDARIES = [
    # "then" / "after that" / "once done" indicate sequencing
    re.compile(r"\.\s*then\s", re.I),
    re.compile(r"\.\s*after\s+that\s*,", re.I),
    re.compile(r"\.\s*once\s+(done|complete)", re.I),
    re.compile(r"\.\s*finally\s*,", re.I),
    re.compile(r"\.\s*next\s*,", re.I),
    # Numbered steps
    re.compile(r"(?:^|\n)\s*\d+\.\s", re.M),
    # Explicit section headers (## Phase, ## Step)
    re.compile(r"(?:^|\n)##\s+", re.M),
    # Deliverables section as boundary
    re.compile(r"(?:^|\n)##?\s*Deliverables?\b", re.I | re.M),
]


def classify_compound(text: str) -> list[ClassifiedPhase]:
    """Classify a multi-phase prompt into an ordered sequence of phases.

    For simple single-phase prompts, returns a list with one phase.
    For compound prompts (BUILD→INVESTIGATE→BUILD), returns the full sequence.
    """
    text = text.strip()
    if not text:
        return []

    # Split text at phase boundaries
    segments = _split_into_segments(text)

    if len(segments) <= 1:
        # Single phase — delegate to classify()
        result = classify(text)
        return [ClassifiedPhase(
            mode=result.mode, rigor=result.rigor,
            description=result.summary, order=0,
        )]

    phases: list[ClassifiedPhase] = []
    for i, segment in enumerate(segments):
        segment = segment.strip()
        if len(segment) < 10:
            continue  # Skip tiny fragments
        result = classify(segment)
        if result.is_meta:
            continue  # Skip meta commands in compound prompts
        phases.append(ClassifiedPhase(
            mode=result.mode, rigor=result.rigor,
            description=result.summary, order=i,
        ))

    # Deduplicate consecutive identical modes
    deduped: list[ClassifiedPhase] = []
    for phase in phases:
        if deduped and deduped[-1].mode == phase.mode and deduped[-1].rigor == phase.rigor:
            continue
        deduped.append(phase)

    return deduped if deduped else [ClassifiedPhase(
        mode=WorkflowMode.GUIDE, rigor=RigorLevel.ADAPTIVE,
        description=_make_summary(text), order=0,
    )]


def _split_into_segments(text: str) -> list[str]:
    """Split text into segments at phase boundaries."""
    # Collect all split positions
    positions: set[int] = set()
    for pattern in _PHASE_BOUNDARIES:
        for match in pattern.finditer(text):
            positions.add(match.start())

    if not positions:
        return [text]

    # Sort and split
    sorted_pos = sorted(positions)
    segments: list[str] = []
    prev = 0
    for pos in sorted_pos:
        if pos > prev:
            segments.append(text[prev:pos])
        prev = pos
    if prev < len(text):
        segments.append(text[prev:])

    return [s for s in segments if s.strip()]
