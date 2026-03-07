"""Progress formatting helpers.

The actual progress *polling* lives in ``voronoi.server.dispatcher``
(single source of truth).  This module provides the formatting functions
used by the router and tests.
"""

from __future__ import annotations


def format_workflow_start(mode: str, rigor: str, summary: str) -> str:
    """Format a workflow-start notification for Telegram."""
    mode_emoji = {
        "investigate": "🔬",
        "explore": "🧭",
        "build": "🔨",
        "hybrid": "🔬🔨",
    }.get(mode, "🔷")

    rigor_emoji = {
        "standard": "",
        "analytical": "📊",
        "scientific": "🧪",
        "experimental": "🔬",
    }.get(rigor, "")

    return (
        f"{mode_emoji} *{mode.upper()}* mode activated {rigor_emoji}\n"
        f"Rigor: {rigor}\n\n"
        f"_{summary}_\n\n"
        f"Dispatching agents..."
    )


def format_workflow_complete(mode: str, total_tasks: int, findings: int, duration_min: float) -> str:
    """Format a workflow-completion notification for Telegram."""
    return (
        f"🏁 *{mode.upper()} COMPLETE*\n\n"
        f"Tasks: {total_tasks}\n"
        f"Findings: {findings}\n"
        f"Duration: {duration_min:.1f}min\n\n"
        f"Check deliverable: `.swarm/deliverable.md`"
    )
