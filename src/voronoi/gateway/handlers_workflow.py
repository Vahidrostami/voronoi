"""Workflow dispatch handlers for Voronoi commands.

Enqueue investigations: discover, prove, demo.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from voronoi.gateway.config import get_gateway_base_dir
from voronoi.gateway.codename import codename_for_id
from voronoi.gateway.progress import MODE_EMOJI, MODE_VERB
from voronoi.science.claims import (
    STATUS_ASSERTED,
    STATUS_CHALLENGED,
    STATUS_LOCKED,
    STATUS_PROVISIONAL,
    STATUS_REPLICATED,
    STATUS_RETIRED,
    Claim,
    load_ledger,
)
from voronoi.server.queue import Investigation, InvestigationQueue
from voronoi.server.runner import make_slug

logger = logging.getLogger("voronoi.router")


def _get_queue(project_dir: str) -> InvestigationQueue:
    return InvestigationQueue(get_gateway_base_dir() / "queue.db")


def _enqueue(project_dir: str, question: str, mode: str,
             rigor: str, chat_id: str) -> tuple[int, str, str]:
    """Enqueue an investigation and return (inv_id, status_message, codename)."""
    q = _get_queue(project_dir)
    inv = Investigation(
        chat_id=chat_id,
        question=question,
        slug=make_slug(question[:40]),
        mode=mode,
        rigor=rigor,
        investigation_type="lab",
    )
    inv_id = q.enqueue(inv)
    stored = q.get(inv_id)
    codename = stored.codename if stored else codename_for_id(inv_id)
    queued = len(q.get_queued())
    running = len(q.get_running())
    logger.info("Enqueued investigation %s (#%d) mode=%s rigor=%s (queued=%d running=%d)",
                codename, inv_id, mode, rigor, queued, running)
    return inv_id, f"Queue: {queued} waiting · {running} running", codename


def _workflow_response(mode: str, rigor: str, question: str,
                       inv_id: int, queue_status: str,
                       codename: str = "") -> str:
    emoji = MODE_EMOJI.get(mode, "🔷")
    verb = MODE_VERB.get(mode, mode)
    label = codename or f"#{inv_id}"
    return (
        f"{emoji} *{label}* — {verb} is live.\n\n"
        f"_{question}_\n\n"
        f"Agents are spinning up — I'll keep you posted."
    )


def handle_discover(project_dir: str, question: str, chat_id: str = "") -> str:
    """Handle DISCOVER mode — open question, adaptive rigor."""
    inv_id, qs, cn = _enqueue(project_dir, question, "discover", "adaptive", chat_id)
    return _workflow_response("discover", "adaptive", question, inv_id, qs, cn)


def handle_prove(project_dir: str, hypothesis: str, chat_id: str = "") -> str:
    """Handle PROVE mode — specific hypothesis, full science gates."""
    inv_id, qs, cn = _enqueue(project_dir, hypothesis, "prove", "scientific", chat_id)
    return _workflow_response("prove", "scientific", hypothesis, inv_id, qs, cn)


# ---------------------------------------------------------------------------
# Paper track (manuscript production on an already-completed investigation)
# ---------------------------------------------------------------------------

_PAPER_QUESTION_TEMPLATE = (
    "[PAPER-TRACK] Produce a submission-ready LaTeX manuscript for "
    "investigation `{codename}` (#{parent_id}).\n\n"
    "Original question: {original}\n\n"
    "Activate the paper-track role sequence: Outliner → "
    "(Lit-Synthesizer ∥ Figure-Critic) → Scribe → Refiner. Use the "
    "completed investigation's `.swarm/deliverable.md`, "
    "`.swarm/claim-evidence.json`, `.swarm/belief-map.json`, and "
    "`data/raw/` as inputs. Treat only locked or replicated Claim Ledger "
    "claims as headline manuscript claims; supported/provisional claims "
    "belong in exploratory context or limitations, and challenged/retired "
    "claims must be excluded from headline results. Enforce the "
    "citation-coverage gate (≥0.90 integration, zero orphan \\cite keys) "
    "and the Refiner safety halt rules. Dual-rubric evaluator must report "
    "both CCSAN and MS_QUALITY."
)

_ACCEPTED_CLAIM_STATUSES = {STATUS_LOCKED, STATUS_REPLICATED}
_FRAGILE_CLAIM_STATUSES = {STATUS_PROVISIONAL, STATUS_ASSERTED}


def _find_completed_by_codename(q: InvestigationQueue, codename: str) -> Optional[Investigation]:
    """Look up a completed (or review) investigation by case-insensitive codename."""
    target = codename.strip()
    if not target:
        return None
    results = q.find_by_codename(target, statuses=("complete", "review"))
    return results[0] if results else None


def _queue_base_dir(q: InvestigationQueue) -> Path:
    """Return the Voronoi base directory associated with a queue."""
    db_path = getattr(q, "db_path", None)
    if isinstance(db_path, (str, Path)):
        return Path(db_path).parent
    return get_gateway_base_dir()


def _fallback_claim_evidence_count(parent: Investigation) -> int:
    """Count legacy claim-evidence entries when no Claim Ledger exists."""
    if not parent.workspace_path:
        return 0
    path = Path(parent.workspace_path) / ".swarm" / "claim-evidence.json"
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0
    if isinstance(data, list):
        return len([item for item in data if isinstance(item, dict) and item.get("claim")])
    if isinstance(data, dict):
        claims = data.get("claims")
        if isinstance(claims, list):
            return len([item for item in claims if isinstance(item, dict) and item.get("claim")])
    return 0


def _claim_line(claim: Claim) -> str:
    statement = " ".join(claim.statement.split())
    if len(statement) > 96:
        statement = statement[:93].rstrip() + "..."
    return f"• *{claim.id}* ({claim.status}): {statement}"


def _reviewer_defense_brief(q: InvestigationQueue, parent: Investigation) -> str | None:
    """Return a not-ready brief, or None when paper-track may proceed."""
    lineage_id = parent.lineage_id or parent.id
    ledger = load_ledger(lineage_id, base_dir=_queue_base_dir(q))
    accepted = [c for c in ledger.claims if c.status in _ACCEPTED_CLAIM_STATUSES]
    if accepted:
        return None

    fragile = [c for c in ledger.claims if c.status in _FRAGILE_CLAIM_STATUSES]
    challenged = [c for c in ledger.claims if c.status == STATUS_CHALLENGED]
    retired = [c for c in ledger.claims if c.status == STATUS_RETIRED]
    fallback_count = _fallback_claim_evidence_count(parent) if not ledger.claims else 0
    fragile_count = len(fragile) or fallback_count
    label = parent.codename or f"#{parent.id}"

    lines = [
        f"🧪 *Reviewer Defense Brief — {label}*",
        "",
        "*Readiness verdict:* not paper-ready yet.",
        "No `locked` or `replicated` Claim Ledger claim is available as a headline result.",
        "",
        "*Claim readiness*",
        "• Paper-worthy headline claims: 0",
        f"• Fragile/provisional claims: {fragile_count}",
        f"• Challenged/retired claims: {len(challenged) + len(retired)}",
    ]

    if fragile:
        lines.extend(["", "*Main claims needing PI acceptance*"])
        lines.extend(_claim_line(claim) for claim in fragile[:3])
    elif fallback_count:
        lines.extend([
            "",
            f"`.swarm/claim-evidence.json` has {fallback_count} claim(s), but no Claim Ledger statuses.",
            "Review and lock claims before turning them into a manuscript headline.",
        ])
    else:
        lines.extend(["", "No claim ledger entries were found for this lineage."])

    objections: list[str] = []
    if fragile_count:
        objections.append("Reviewer is likely to ask why the headline claim is not PI-accepted or replicated.")
    if challenged:
        ids = ", ".join(c.id for c in challenged[:5])
        objections.append(f"Active challenged claim(s) need resolution or exclusion: {ids}.")
    if retired:
        objections.append("Retired claims must stay out of the headline results.")
    if not objections:
        objections.append("The paper needs at least one accepted claim before manuscript production.")

    lines.extend(["", "*Likely reviewer objection*"])
    lines.extend(f"• {item}" for item in objections[:3])
    lines.extend([
        "",
        "*Likely next action*",
        f"Run `/voronoi review {label}` and lock at least one defensible claim, or continue with a specific challenge.",
        "",
        "*Commands*",
        f"• `/voronoi review {label}`",
        f"• `/voronoi continue {label} lock C<id>`",
        f"• `/voronoi continue {label} challenge C<id>: <reason>`",
        f"• `/voronoi complete {label}` once the accepted claims are settled",
    ])
    return "\n".join(lines)


def handle_paper(project_dir: str, codename: str, chat_id: str = "") -> str:
    """Enqueue a paper-track sub-investigation for a completed investigation.

    The user invokes ``/voronoi paper <codename>`` once an investigation has
    converged. This enqueues a new investigation in PROVE/SCIENTIFIC mode
    with ``parent_id`` set to the completed one; the dispatcher + orchestrator
    recognise the ``[PAPER-TRACK]`` marker in the question and activate the
    paper-track agent sequence.
    """
    codename = (codename or "").strip()
    if not codename:
        return (
            "Usage: `/voronoi paper <codename>`\n\n"
            "Example: `/voronoi paper Dopamine` — writes a manuscript for the "
            "completed investigation *Dopamine*."
        )

    q = _get_queue(project_dir)
    parent = _find_completed_by_codename(q, codename)
    if parent is None:
        return (
            f"❌ No completed investigation named *{codename}* found.\n\n"
            "Paper-track requires a converged investigation. "
            "Use `/voronoi status` to list recent ones."
        )

    # Prevent duplicate paper-track runs (queued, running, paused, or failed).
    # Check all non-terminal paper-track investigations for this parent.
    candidates = q.get_queued() + q.get_running() + q.get_paused()
    existing = [
        inv for inv in candidates
        if inv.parent_id == parent.id and inv.question.startswith("[PAPER-TRACK]")
    ]
    if not existing:
        # Also check recently failed paper-track runs to warn the user.
        for inv in q.get_recent(limit=50):
            if (inv.parent_id == parent.id
                    and inv.question.startswith("[PAPER-TRACK]")
                    and inv.status == "failed"):
                existing.append(inv)
                break
    if existing:
        inv = existing[0]
        label = inv.codename or f"#{inv.id}"
        if inv.status == "failed":
            return (
                f"⚠️ A previous paper-track attempt for *{parent.codename}* "
                f"failed as *{label}*.\n\n"
                f"Use `/voronoi resume {label}` to retry, or re-run "
                f"`/voronoi paper {codename}` after resolving the failure."
            )
        return (
            f"⚠️ Paper-track already {inv.status} for *{parent.codename}* "
            f"as *{label}*.\n\nUse `/voronoi status` to check progress."
        )

    readiness_brief = _reviewer_defense_brief(q, parent)
    if readiness_brief is not None:
        return readiness_brief

    question = _PAPER_QUESTION_TEMPLATE.format(
        codename=parent.codename,
        parent_id=parent.id,
        original=(parent.question or "").strip() or "(no question recorded)",
    )

    inv = Investigation(
        chat_id=chat_id,
        question=question,
        slug=make_slug(f"paper-{parent.codename or parent.id}"),
        mode="prove",
        rigor="scientific",
        investigation_type="lab",
        parent_id=parent.id,
        lineage_id=parent.lineage_id or parent.id,
    )
    inv_id = q.enqueue(inv)
    stored = q.get(inv_id)
    child_codename = stored.codename if stored else codename_for_id(inv_id)
    queued = len(q.get_queued())
    running = len(q.get_running())
    logger.info(
        "Enqueued paper-track investigation %s (#%d) parent=%s (#%d) queued=%d running=%d",
        child_codename, inv_id, parent.codename, parent.id, queued, running,
    )

    return (
        f"📝 *{child_codename}* — paper-track is live.\n\n"
        f"Manuscript for *{parent.codename}*. "
        "Running Outliner → Lit-Synthesizer ∥ Figure-Critic → Scribe → "
        "Refiner. Citation-coverage gate enforced at ≥0.90."
    )


def handle_demo(project_dir: str, demo_name: str, chat_id: str = "") -> str:
    """Set up and enqueue a demo as an investigation."""
    from voronoi.cli import find_data_dir, list_demos

    data = find_data_dir()
    demos = list_demos(data)
    demo = next((d for d in demos if d["name"] == demo_name), None)
    if demo is None:
        available = ", ".join(d["name"] for d in demos)
        return f"❌ Demo `{demo_name}` not found. Available: {available}"
    if not demo["has_prompt"]:
        return f"❌ Demo `{demo_name}` has no PROMPT.md."

    prompt_path = demo["path"] / "PROMPT.md"
    prompt_content = prompt_path.read_text()

    q = _get_queue(project_dir)

    # Prevent duplicate
    slug = make_slug(demo_name)
    for inv in q.get_queued() + q.get_running():
        if inv.slug == slug:
            label = inv.codename or f"#{inv.id}"
            return (
                f"⚠️ Demo `{demo_name}` is already {inv.status} "
                f"as *{label}*.\n\n"
                f"Use `/voronoi status` to check progress."
            )

    from voronoi.gateway.intent import _determine_rigor, WorkflowMode, RigorLevel
    _RIGOR_ORDER = [RigorLevel.ADAPTIVE,
                    RigorLevel.SCIENTIFIC, RigorLevel.EXPERIMENTAL]
    detected_rigor = _determine_rigor(prompt_content, WorkflowMode.PROVE)
    if _RIGOR_ORDER.index(detected_rigor) < _RIGOR_ORDER.index(RigorLevel.SCIENTIFIC):
        detected_rigor = RigorLevel.SCIENTIFIC

    inv = Investigation(
        chat_id=chat_id,
        question=prompt_content,
        slug=make_slug(demo_name),
        mode="prove",
        rigor=detected_rigor.value,
        investigation_type="lab",
    )
    inv_id = q.enqueue(inv)
    stored = q.get(inv_id)
    codename = stored.codename if stored else codename_for_id(inv_id)

    q.set_demo_source(inv_id, demo_name, str(demo["path"]))

    logger.info("Enqueued demo %s as investigation %s (#%d)", demo_name, codename, inv_id)

    return (
        f"🎮 *{codename}* — demo is live.\n\n"
        f"Running *{demo_name}* — agents are spinning up."
    )
