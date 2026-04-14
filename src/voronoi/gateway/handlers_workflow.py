"""Workflow dispatch handlers for Voronoi commands.

Enqueue investigations: discover, prove, demo.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from voronoi.gateway.progress import MODE_EMOJI, MODE_VERB
from voronoi.server.queue import Investigation, InvestigationQueue
from voronoi.server.runner import make_slug
from voronoi.gateway.codename import codename_for_id

logger = logging.getLogger("voronoi.router")


def _get_queue(project_dir: str) -> InvestigationQueue:
    base = Path.home() / ".voronoi"
    return InvestigationQueue(base / "queue.db")


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
