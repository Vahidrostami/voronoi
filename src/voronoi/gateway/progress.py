"""Progress formatting helpers.

The actual progress *polling* lives in ``voronoi.server.dispatcher``
(single source of truth).  This module provides the formatting functions
used by the router and tests.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

MODE_EMOJI: dict[str, str] = {
    "investigate": "🔬",
    "explore": "🧭",
    "build": "🔨",
    "hybrid": "🔬🔨",
    "experiment": "🧪",
}

RIGOR_DESCRIPTIONS: dict[str, str] = {
    "standard": "quality checks",
    "analytical": "statistical validation · effect sizes",
    "scientific": "pre-registration · hypothesis testing",
    "experimental": "controlled experiments · replication",
}

MODE_VERB: dict[str, str] = {
    "investigate": "investigation",
    "explore": "exploration",
    "build": "build",
    "hybrid": "investigation",
    "experiment": "experiment",
}

PHASE_LABELS: dict[str, dict[str, str]] = {
    "investigate": {
        "planning": "🗺️ *Planning* — decomposing into tasks…",
        "investigating": "🔬 *Running* — agents investigating in parallel",
        "synthesizing": "🧩 *Synthesizing* — integrating findings…",
        "complete": "📄 *Wrapping up* — writing deliverable…",
    },
    "explore": {
        "planning": "🗺️ *Planning* — mapping the exploration…",
        "investigating": "🧭 *Exploring* — agents researching in parallel",
        "synthesizing": "🧩 *Synthesizing* — comparing alternatives…",
        "complete": "📄 *Wrapping up* — writing report…",
    },
    "build": {
        "planning": "🗺️ *Architecting* — breaking down the build…",
        "investigating": "🔨 *Building* — agents coding in parallel",
        "synthesizing": "🧩 *Integrating* — assembling components…",
        "complete": "📄 *Finalizing* — polishing deliverables…",
    },
    "experiment": {
        "planning": "🗺️ *Designing* — setting up the experiment…",
        "investigating": "🧪 *Running trials* — agents executing experiments",
        "synthesizing": "🧩 *Analyzing* — processing results…",
        "complete": "📄 *Wrapping up* — writing manuscript…",
    },
}


# ---------------------------------------------------------------------------
# Utility formatters
# ---------------------------------------------------------------------------

def progress_bar(done: int, total: int, width: int = 10) -> str:
    """Render a text progress bar: ██████░░░░ 60%  6/10 tasks"""
    if total == 0:
        return "░" * width + "  0/0 tasks"
    pct = done / total
    filled = round(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {int(pct * 100)}%  {done}/{total} tasks"


def estimate_remaining(elapsed_sec: float, done: int, total: int) -> str:
    """Estimate time remaining based on current rate. Returns '' if unknown."""
    if done == 0 or total == done:
        return ""
    rate = elapsed_sec / done
    remaining_min = (rate * (total - done)) / 60
    if remaining_min < 1:
        return "~<1min left"
    return f"~{remaining_min:.0f}min left"


def voronoi_header(inv_id: int, mode: str, suffix: str = "",
                   codename: str = "") -> str:
    """Build the branded header: ⚡ Voronoi · Dopamine 🔬 LAUNCHED"""
    emoji = MODE_EMOJI.get(mode, "🔷")
    label = codename or f"#{inv_id}"
    parts = [f"Voronoi · {label} {emoji}"]
    if suffix:
        parts[0] += f" {suffix}"
    return parts[0]


def phase_label(mode: str, phase: str) -> str:
    """Return the mode-aware phase label."""
    labels = PHASE_LABELS.get(mode, PHASE_LABELS["investigate"])
    return labels.get(phase, f"Phase: {phase}")


# ---------------------------------------------------------------------------
# High-level message formatters
# ---------------------------------------------------------------------------

def format_workflow_start(mode: str, rigor: str, summary: str) -> str:
    """Format a workflow-start notification for Telegram."""
    emoji = MODE_EMOJI.get(mode, "🔷")
    rigor_desc = RIGOR_DESCRIPTIONS.get(rigor, rigor)

    return (
        f"{emoji} *{mode.upper()}* mode activated\n\n"
        f"_{summary}_\n\n"
        f"Rigor: *{rigor}* — {rigor_desc}\n\n"
        f"Dispatching agents…"
    )


def format_workflow_complete(mode: str, total_tasks: int, findings: int, duration_min: float) -> str:
    """Format a workflow-completion notification for Telegram."""
    emoji = MODE_EMOJI.get(mode, "🔷")
    bar = progress_bar(total_tasks, total_tasks)
    return (
        f"🏁 *{mode.upper()} COMPLETE* {emoji} · {duration_min:.1f}min\n\n"
        f"{bar}\n"
        f"Findings: {findings}\n\n"
        f"📎 Deliverable attached"
    )
