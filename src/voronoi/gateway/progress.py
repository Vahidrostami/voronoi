"""Progress formatting helpers.

The actual progress *polling* lives in ``voronoi.server.dispatcher``
(single source of truth).  This module provides the formatting functions
used by the router, dispatcher, and tests.

Design philosophy: messages should read like a teammate giving you an
update over chat — conversational, informative, and forward-looking.
Minimal emoji. Narrative over data dumps.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


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

# Buddy-style phase descriptions — conversational, not labels
PHASE_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "investigate": {
        "starting": "Setting things up...",
        "scouting": "Doing some background research first.",
        "planning": "Planning the investigation — generating hypotheses and breaking work into tasks.",
        "investigating": "Running experiments — agents are working in parallel.",
        "reviewing": "Reviewing the findings — statistical checks and adversarial critique.",
        "synthesizing": "Pulling everything together into a coherent picture.",
        "converging": "Almost done — evaluating the final deliverable.",
        "complete": "Wrapping up and writing the report.",
    },
    "explore": {
        "starting": "Setting things up...",
        "scouting": "Surveying what's out there.",
        "planning": "Mapping out what to explore.",
        "investigating": "Researching options in parallel.",
        "reviewing": "Evaluating and comparing what we found.",
        "synthesizing": "Comparing alternatives — building the recommendation.",
        "converging": "Finalizing the recommendation.",
        "complete": "Writing up the report.",
    },
    "build": {
        "starting": "Setting things up...",
        "planning": "Breaking down the build into tasks.",
        "investigating": "Building — agents coding in parallel.",
        "reviewing": "Code review in progress.",
        "synthesizing": "Integrating all the pieces.",
        "complete": "Polishing the deliverables.",
    },
    "experiment": {
        "starting": "Setting things up...",
        "scouting": "Reviewing methodology and prior art.",
        "planning": "Designing and pre-registering experiments.",
        "investigating": "Running trials — agents executing experiments.",
        "reviewing": "Statistical audit and adversarial critique.",
        "synthesizing": "Processing results and checking consistency.",
        "converging": "Replication checks and final evaluation.",
        "complete": "Writing the manuscript.",
    },
    "hybrid": {
        "starting": "Setting things up...",
        "scouting": "Researching before we plan.",
        "planning": "Planning the investigation + build.",
        "investigating": "Working — agents running in parallel.",
        "reviewing": "Validating findings.",
        "synthesizing": "Integrating investigation + build.",
        "converging": "Evaluating completeness.",
        "complete": "Writing the deliverable.",
    },
}

# Keep old PHASE_LABELS alive as alias for backward compat (scripts may use it)
PHASE_LABELS: dict[str, dict[str, str]] = {
    mode: {phase: f"*{desc}*" for phase, desc in phases.items()}
    for mode, phases in PHASE_DESCRIPTIONS.items()
}


# ---------------------------------------------------------------------------
# Utility formatters
# ---------------------------------------------------------------------------

def progress_bar(done: int, total: int, width: int = 20) -> str:
    """Render a clean text progress bar: ████████████░░░░░░░░ 60%"""
    if total == 0:
        return "░" * width + " 0%"
    pct = done / total
    filled = round(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {int(pct * 100)}%"


def format_duration(seconds: float) -> str:
    """Format seconds as a human-friendly duration string."""
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)}min"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins}min"


def estimate_remaining(elapsed_sec: float, done: int, total: int) -> str:
    """Estimate time remaining based on current rate. Returns '' if unknown."""
    if done == 0 or total == done:
        return ""
    rate = elapsed_sec / done
    remaining_sec = rate * (total - done)
    if remaining_sec < 60:
        return "almost done"
    return f"~{format_duration(remaining_sec)} left"


def phase_description(mode: str, phase: str) -> str:
    """Return the conversational phase description."""
    descs = PHASE_DESCRIPTIONS.get(mode, PHASE_DESCRIPTIONS["investigate"])
    return descs.get(phase, phase)


# Keep old API alive
def voronoi_header(inv_id: int, mode: str, suffix: str = "",
                   codename: str = "") -> str:
    """Build a simple header: Codename — Xh Ymin"""
    label = codename or f"#{inv_id}"
    parts = [f"*{label}*"]
    if suffix:
        parts[0] += f" — {suffix}"
    return parts[0]


def phase_label(mode: str, phase: str) -> str:
    """Return the mode-aware phase label (backward compat)."""
    return phase_description(mode, phase)


# ---------------------------------------------------------------------------
# Digest builder — the core of the new notification system
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Optional[dict]:
    """Safely read a JSON file, returning None on failure."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _read_tsv_rows(path: Path) -> list[dict]:
    """Read a TSV file (with header) into a list of dicts."""
    if not path.exists():
        return []
    try:
        lines = path.read_text().strip().split("\n")
        if len(lines) < 2:
            return []
        headers = lines[0].split("\t")
        rows = []
        for line in lines[1:]:
            fields = line.split("\t")
            if len(fields) >= len(headers):
                rows.append(dict(zip(headers, fields)))
        return rows
    except OSError:
        return []


def assess_track_status(
    workspace: Path,
    task_snapshot: dict,
    eval_score: float = 0.0,
) -> tuple[str, str]:
    """Assess whether the investigation is on track.

    Returns (status, reason) where status is one of:
      'on_track', 'watch', 'off_track'
    """
    # Check for DESIGN_INVALID
    for t in task_snapshot.values():
        if t.get("status") != "closed" and "DESIGN_INVALID" in t.get("notes", ""):
            return "off_track", "An experiment design was flagged as invalid — being fixed."

    # Check success criteria
    criteria_data = _read_json(workspace / ".swarm" / "success-criteria.json")
    if criteria_data and isinstance(criteria_data, list):
        total_sc = len(criteria_data)
        met_sc = sum(1 for c in criteria_data if c.get("met"))
        if total_sc > 0 and met_sc == total_sc:
            return "on_track", "All success criteria met."
        # If we have results but criteria aren't met, that's watchable
        closed = sum(1 for t in task_snapshot.values() if t.get("status") == "closed")
        total = len(task_snapshot)
        if total > 0 and closed / total > 0.7 and met_sc == 0:
            return "watch", f"70%+ tasks done but no success criteria met yet ({met_sc}/{total_sc})."

    # Check eval score if available
    if eval_score > 0:
        if eval_score >= 0.75:
            return "on_track", f"Quality score is {eval_score:.2f} — above threshold."
        if eval_score >= 0.50:
            return "watch", f"Quality score is {eval_score:.2f} — needs improvement (target: 0.75)."
        return "off_track", f"Quality score is {eval_score:.2f} — significantly below target."

    # Default: if things are moving, we're on track
    total = len(task_snapshot)
    if total == 0:
        return "watch", "No tasks created yet."
    closed = sum(1 for t in task_snapshot.values() if t.get("status") == "closed")
    in_progress = sum(1 for t in task_snapshot.values() if t.get("status") == "in_progress")
    if in_progress > 0 or closed > 0:
        return "on_track", "Work is progressing normally."
    return "watch", "Tasks exist but nothing started yet."


def build_digest(
    *,
    codename: str,
    mode: str,
    phase: str,
    elapsed_sec: float,
    task_snapshot: dict,
    workspace: Path,
    events_since_last: list[dict],
    eval_score: float = 0.0,
) -> str:
    """Build a conversational narrative digest message.

    This replaces the old per-event ``_send_progress_batch`` with a single
    buddy-style message that covers: what happened, where we are, what's next.
    """
    elapsed_str = format_duration(elapsed_sec)

    total = len(task_snapshot)
    closed = sum(1 for t in task_snapshot.values() if t.get("status") == "closed")
    in_progress = sum(1 for t in task_snapshot.values() if t.get("status") == "in_progress")

    # Categorize recent events
    completed = [e for e in events_since_last if e.get("type") == "task_done"]
    findings = [e for e in events_since_last if e.get("type") == "finding"]
    started = [e for e in events_since_last if e.get("type") == "task_started"]
    new_tasks = [e for e in events_since_last if e.get("type") == "task_new"]
    design_invalids = [e for e in events_since_last if e.get("type") == "design_invalid"]
    phase_changes = [e for e in events_since_last if e.get("type") == "phase"]

    lines: list[str] = []

    # Header — codename + time only
    lines.append(f"*{codename}* — {elapsed_str}\n")

    # What happened since last update
    happened: list[str] = []
    if completed:
        titles = [_extract_task_title(e) for e in completed[:5]]
        if len(completed) <= 3:
            for t in titles:
                happened.append(f"Finished: {t}")
        else:
            happened.append(f"Finished {len(completed)} tasks")
    if findings:
        for f in findings:
            title = f.get("msg", "").replace("🔬 *NEW FINDING*\n", "").strip()
            happened.append(f"New finding: {title}")
    if design_invalids:
        for d in design_invalids:
            happened.append(f"Problem: {_extract_task_title(d)}")
    if new_tasks and not completed and not findings:
        happened.append(f"{len(new_tasks)} new tasks created")

    if happened:
        for h in happened:
            lines.append(f"• {h}")
        lines.append("")

    # Where we are — phase + narrative
    phase_desc = phase_description(mode, phase)
    lines.append(phase_desc)

    # Progress numbers woven into a sentence
    if total > 0:
        pct = int(closed / total * 100)
        bar = progress_bar(closed, total)
        lines.append(f"{bar}  ({closed}/{total} tasks)")
        eta = estimate_remaining(elapsed_sec, closed, total)
        if eta:
            lines.append(f"Estimated: {eta}")

    # Experiment progress (if experiments.tsv exists)
    exp_summary = _experiment_summary(workspace)
    if exp_summary:
        lines.append("")
        lines.append(exp_summary)

    # Success criteria check
    criteria_summary = _criteria_summary(workspace)
    if criteria_summary:
        lines.append("")
        lines.append(criteria_summary)

    # Eval score if available
    if eval_score > 0:
        lines.append(f"\nQuality score: {eval_score:.2f}" +
                      (" — looks good" if eval_score >= 0.75 else " — needs work"))

    # Track assessment
    track_status, track_reason = assess_track_status(workspace, task_snapshot, eval_score)
    if track_status == "off_track":
        lines.append(f"\n⚠️ {track_reason}")
    elif track_status == "watch":
        lines.append(f"\nHeads up: {track_reason}")

    # What's next — agents working
    if in_progress > 0:
        lines.append(f"\n{in_progress} {'agent' if in_progress == 1 else 'agents'} working right now.")

    return "\n".join(lines)


def build_digest_whatsup(
    *,
    running_investigations: list[dict],
    queued: int,
) -> str:
    """Build a conversational 'what's up' response combining status+tasks+health.

    Each item in running_investigations should have:
      label, mode, elapsed_sec, total_tasks, closed_tasks, in_progress_tasks,
      ready_tasks, agents_healthy, agents_stuck, phase, question
    """
    if not running_investigations and queued == 0:
        return "Nothing running right now. Send me a question to get started."

    lines: list[str] = []

    if queued > 0:
        lines.append(f"{queued} investigation{'s' if queued > 1 else ''} queued, waiting to start.\n")

    for inv in running_investigations:
        label = inv.get("label", "Unknown")
        elapsed = format_duration(inv.get("elapsed_sec", 0))
        total = inv.get("total_tasks", 0)
        closed = inv.get("closed_tasks", 0)
        in_prog = inv.get("in_progress_tasks", 0)
        ready = inv.get("ready_tasks", 0)
        phase = inv.get("phase", "")
        mode = inv.get("mode", "investigate")
        healthy = inv.get("agents_healthy", 0)
        stuck = inv.get("agents_stuck", 0)
        question = inv.get("question", "")[:80]

        lines.append(f"*{label}* is running — started {elapsed} ago.")
        if question:
            lines.append(f"_{question}_\n")

        if total > 0:
            lines.append(f"{closed}/{total} tasks done, {in_prog} in progress, {ready} ready to go.")
        else:
            lines.append("Setting up — no tasks created yet.")

        # Agent health in one line
        agent_parts: list[str] = []
        if healthy > 0:
            agent_parts.append(f"{healthy} healthy")
        if stuck > 0:
            agent_parts.append(f"{stuck} stuck")
        if agent_parts:
            lines.append(f"Agents: {', '.join(agent_parts)}.")

        if phase:
            lines.append(f"\n{phase_description(mode, phase)}")

        lines.append("")  # blank line between investigations

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Internal digest helpers
# ---------------------------------------------------------------------------

def _extract_task_title(event: dict) -> str:
    """Extract a clean task title from an event dict."""
    msg = event.get("msg", "")
    # Strip common prefixes from old-style event messages
    for prefix in ("✅ Done: ", "⚡ Working: ", "📋 New: ", "🚨 "):
        if msg.startswith(prefix):
            msg = msg[len(prefix):]
    # Strip markdown bold
    msg = msg.replace("*", "")
    return msg[:80]


def _experiment_summary(workspace: Path) -> str:
    """Read experiments.tsv and return a one-line summary."""
    rows = _read_tsv_rows(workspace / ".swarm" / "experiments.tsv")
    if not rows:
        return ""
    keep = sum(1 for r in rows if r.get("status") == "keep")
    discard = sum(1 for r in rows if r.get("status") == "discard")
    crash = sum(1 for r in rows if r.get("status") == "crash")
    total = len(rows)
    parts = [f"{total} experiment runs"]
    detail: list[str] = []
    if keep:
        detail.append(f"{keep} good")
    if discard:
        detail.append(f"{discard} discarded")
    if crash:
        detail.append(f"{crash} crashed")
    if detail:
        parts.append(f"({', '.join(detail)})")
    return "Experiments: " + " ".join(parts)


def _criteria_summary(workspace: Path) -> str:
    """Read success-criteria.json and return a one-line summary."""
    path = workspace / ".swarm" / "success-criteria.json"
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return ""
    if not isinstance(data, list) or not data:
        return ""
    met = sum(1 for c in data if c.get("met"))
    total = len(data)
    summaries: list[str] = []
    for c in data:
        cid = c.get("id", "?")
        check = "✓" if c.get("met") else "○"
        desc = c.get("description", "")[:40]
        summaries.append(f"{check} {cid}: {desc}")
    header = f"Success criteria: {met}/{total} met"
    return header + "\n" + "\n".join(summaries)


# ---------------------------------------------------------------------------
# High-level message formatters (buddy-style)
# ---------------------------------------------------------------------------

def format_launch(codename: str, mode: str, rigor: str, question: str) -> str:
    """Format a launch notification — conversational, not a status log."""
    rigor_desc = RIGOR_DESCRIPTIONS.get(rigor, rigor)
    return (
        f"*{codename}* is live.\n\n"
        f"_{question[:200]}_\n\n"
        f"Mode: {mode} · Rigor: {rigor_desc}\n"
        f"I'll send you updates as things progress."
    )


def format_complete(codename: str, mode: str, total_tasks: int,
                    closed_tasks: int, elapsed_sec: float,
                    eval_score: float = 0.0) -> str:
    """Format a completion message — brief, celebratory."""
    elapsed = format_duration(elapsed_sec)
    bar = progress_bar(closed_tasks, total_tasks)
    lines = [f"*{codename}* is done. {elapsed}, {closed_tasks} tasks completed.\n"]
    lines.append(bar)
    if eval_score > 0:
        lines.append(f"\nQuality score: {eval_score:.2f}")
    lines.append("\nReport attached below.")
    return "\n".join(lines)


def format_failure(codename: str, reason: str, elapsed_sec: float,
                   closed: int, total: int, log_tail: str = "",
                   retry_count: int = 0, max_retries: int = 0) -> str:
    """Format a failure message — honest, diagnostic."""
    elapsed = format_duration(elapsed_sec)
    lines = [f"*{codename}* failed after {elapsed}.\n"]
    lines.append(f"Reason: {reason}")
    lines.append(f"Got through {closed}/{total} tasks before it stopped.")
    if retry_count > 0:
        lines.append(f"Tried to restart {retry_count} time{'s' if retry_count > 1 else ''} (max {max_retries}).")
    if log_tail:
        lines.append(f"\nLast output:\n```\n{log_tail[-400:]}\n```")
    return "\n".join(lines)


def format_alert(codename: str, message: str) -> str:
    """Format an alert — something needs attention."""
    return f"*{codename}* — heads up:\n{message}"


def format_restart(codename: str, attempt: int, max_retries: int,
                   log_tail: str = "") -> str:
    """Format a restart notification."""
    lines = [f"*{codename}* — the agent crashed. Restarting (attempt {attempt}/{max_retries})."]
    if log_tail:
        lines.append(f"\nLast output:\n```\n{log_tail[-300:]}\n```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Backward-compat wrappers (used by old tests)
# ---------------------------------------------------------------------------

def format_workflow_start(mode: str, rigor: str, summary: str) -> str:
    """Format a workflow-start notification for Telegram (backward compat)."""
    return format_launch(
        codename="Voronoi",
        mode=mode,
        rigor=rigor,
        question=summary,
    )


def format_workflow_complete(mode: str, total_tasks: int, findings: int,
                             duration_min: float) -> str:
    """Format a workflow-completion notification for Telegram (backward compat)."""
    return format_complete(
        codename="Voronoi",
        mode=mode,
        total_tasks=total_tasks,
        closed_tasks=total_tasks,
        elapsed_sec=duration_min * 60,
    )
