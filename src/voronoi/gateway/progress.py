"""Progress formatting helpers.

The actual progress *polling* lives in ``voronoi.server.dispatcher``
(single source of truth).  This module provides the formatting functions
used by the router, dispatcher, and tests.

Design philosophy: messages should read like a sharp research lab manager
giving a brief, confident update — milestone-driven, phase-aware, and
adaptive to the time horizon. Early updates set expectations. Mid-run
updates highlight achievements and findings. Late updates focus on
convergence. Never dump raw data. Never alarm for normal states.

Voice: confident, concise, occasionally wry. Celebrates real milestones.
Speaks in terms of scientific progress, not task management.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

MODE_EMOJI: dict[str, str] = {
    "discover": "🔬",
    "prove": "🧪",
}

RIGOR_DESCRIPTIONS: dict[str, str] = {
    "adaptive": "adaptive rigor · escalates dynamically",
    "scientific": "pre-registration · hypothesis testing · full gates",
    "experimental": "controlled experiments · replication",
}

MODE_VERB: dict[str, str] = {
    "discover": "discovery",
    "prove": "proof",
}

# ---------------------------------------------------------------------------
# VOICE — Voronoi's personality for Telegram updates.
#
# Inspired by OpenClaw's SOUL.md concept, adapted for a science-discovery
# assistant.  The voice is a sharp lab manager: confident, concise, and
# research-aware.  Each phase has multiple variants that rotate by
# codename hash so repeated polls don't feel copy-pasted.
# ---------------------------------------------------------------------------

VOICE_PHASE_VARIANTS: dict[str, list[str]] = {
    "starting": [
        "Warming up the lab...",
        "Getting everything in order...",
        "Setting up the workspace...",
    ],
    "scouting": [
        "Reading up on prior work.",
        "Surveying the literature first.",
        "Checking what's already known.",
    ],
    "planning": [
        "Forming hypotheses and designing experiments.",
        "Turning the question into a research plan.",
        "Breaking this into testable pieces.",
    ],
    "investigating": [
        "Experiments underway — agents deep in it.",
        "The team's running experiments now.",
        "Multiple experiments running in parallel.",
    ],
    "reviewing": [
        "Cross-checking the numbers.",
        "Statistical audit in progress.",
        "Making sure the results hold up under scrutiny.",
    ],
    "synthesizing": [
        "Connecting the dots across experiments.",
        "Pulling findings together into a coherent picture.",
        "Seeing how all the pieces fit.",
    ],
    "converging": [
        "Finish line in sight — final quality checks.",
        "Nearly there — running last evaluations.",
        "Almost done — making sure it's solid.",
    ],
    "complete": [
        "Writing it up.",
        "Putting the final document together.",
        "Drafting the report.",
    ],
}

VOICE_CRITERIA_CONTEXT: dict[str, str] = {
    "zero": "early days",
    "some": "making progress",
    "most": "getting close",
    "all": "all met",
}

VOICE_QUALITY_LABELS: dict[str, str] = {
    "high": "solid",
    "ok": "improving",
    "low": "needs work",
}

# Legacy static descriptions — kept for backward compat and fallback
PHASE_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "discover": {
        "starting": "Setting things up...",
        "scouting": "Doing some background research first.",
        "planning": "Planning the investigation — generating hypotheses and breaking work into tasks.",
        "investigating": "Running experiments — agents are working in parallel.",
        "reviewing": "Reviewing the findings — statistical checks and adversarial critique.",
        "synthesizing": "Pulling everything together into a coherent picture.",
        "converging": "Almost done — evaluating the final deliverable.",
        "complete": "Wrapping up and writing the report.",
    },
    "prove": {
        "starting": "Setting things up...",
        "scouting": "Reviewing methodology and prior art.",
        "planning": "Designing and pre-registering experiments.",
        "investigating": "Running trials — agents executing experiments.",
        "reviewing": "Statistical audit and adversarial critique.",
        "synthesizing": "Processing results and checking consistency.",
        "converging": "Replication checks and final evaluation.",
        "complete": "Writing the manuscript.",
    },
}

# Ordered phase list for journey position display
PHASE_ORDER: list[str] = [
    "starting", "scouting", "planning", "investigating",
    "reviewing", "synthesizing", "converging", "complete",
]

# Message type constants — used by dispatcher to tell the bridge
# what kind of message this is (for button selection and edit-vs-send).
MSG_TYPE_STATUS = "status"           # live status (edit in place)
MSG_TYPE_MILESTONE = "milestone"     # new finding, phase change (new msg)


# ---------------------------------------------------------------------------
# Utility formatters
# ---------------------------------------------------------------------------

def progress_bar(done: int, total: int, width: int = 20) -> str:
    """Render a clean text progress bar: ████████████░░░░░░░░ 60%"""
    if total == 0:
        return "░" * width + " 0%"
    pct = min(done / total, 1.0)
    filled = round(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {int(pct * 100)}%"


def format_duration(seconds: float) -> str:
    """Format seconds as a human-friendly duration string."""
    if seconds < 60:
        return "< 1min"
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
    if done == 0 or done >= total:
        return ""
    rate = elapsed_sec / done
    remaining_sec = rate * (total - done)
    if remaining_sec < 60:
        return "almost done"
    return f"~{format_duration(remaining_sec)} left"


def phase_description(mode: str, phase: str, codename: str = "") -> str:
    """Return a conversational phase description.

    If *codename* is provided, uses VOICE_PHASE_VARIANTS with deterministic
    rotation so the same investigation always picks the same variant for a
    given phase, but different investigations get different wording.
    Falls back to the static PHASE_DESCRIPTIONS when no variant matches.
    """
    if codename and phase in VOICE_PHASE_VARIANTS:
        variants = VOICE_PHASE_VARIANTS[phase]
        idx = int(hashlib.md5(f"{codename}:{phase}".encode()).hexdigest(), 16)
        return variants[idx % len(variants)]
    descs = PHASE_DESCRIPTIONS.get(mode, PHASE_DESCRIPTIONS["discover"])
    return descs.get(phase, phase)


def phase_position(phase: str) -> tuple[int, int]:
    """Return (current_step, total_steps) for journey display.

    Returns 1-based step number. Unknown phases return (0, total).
    """
    total = len(PHASE_ORDER)
    if phase in PHASE_ORDER:
        return PHASE_ORDER.index(phase) + 1, total
    return 0, total


# ---------------------------------------------------------------------------
# Digest builder — the core of the new notification system
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Optional[dict | list]:
    """Safely read a JSON file, returning None on failure."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, (dict, list)) else None
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


def _read_swarm_config(workspace: Path) -> dict:
    data = _read_json(workspace / ".swarm-config.json")
    return data if isinstance(data, dict) else {}


def _iter_agent_worktrees(workspace: Path) -> list[Path]:
    config = _read_swarm_config(workspace)
    candidates: list[Path] = []

    configured = config.get("swarm_dir")
    if configured:
        candidates.append(Path(configured))
    candidates.append(workspace.parent / f"{workspace.name}-swarm")

    seen: set[Path] = set()
    worktrees: list[Path] = []
    for swarm_dir in candidates:
        if swarm_dir in seen or not swarm_dir.exists() or not swarm_dir.is_dir():
            continue
        seen.add(swarm_dir)
        for path in sorted(swarm_dir.glob("agent-*")):
            if path.is_dir():
                worktrees.append(path)
    return worktrees


def _read_all_experiment_rows(workspace: Path) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[tuple[str, str], ...]] = set()

    for path in [workspace, *_iter_agent_worktrees(workspace)]:
        for row in _read_tsv_rows(path / ".swarm" / "experiments.tsv"):
            key = tuple(sorted((str(k), str(v)) for k, v in row.items()))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _artifact_progress_summary(workspace: Path) -> str:
    observations: list[tuple[float, str]] = []
    now = time.time()

    for worktree in _iter_agent_worktrees(workspace):
        files: list[Path] = []
        files.extend(path for path in worktree.glob("demos/*/run.log") if path.is_file())
        files.extend(path for path in worktree.glob("demos/*/output/*.json") if path.is_file())
        files.extend(path for path in worktree.glob(".swarm/*.json") if path.is_file())
        if not files:
            continue

        latest = max(files, key=lambda path: path.stat().st_mtime)
        age_sec = max(0, now - latest.stat().st_mtime)
        age = format_duration(age_sec)
        output_count = sum(1 for path in worktree.glob("demos/*/output/*.json") if path.is_file())
        observations.append(
            (
                latest.stat().st_mtime,
                f"{worktree.name} updated {age} ago ({output_count} outputs; latest {latest.name})",
            )
        )

    if not observations:
        return ""

    observations.sort(reverse=True)
    lead = observations[0][1]
    if len(observations) == 1:
        return f"Observed artifacts: {lead}"
    return f"Observed artifacts: {lead} · +{len(observations) - 1} other active worktrees"


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
        return "watch", "No tasks created yet — still setting up."
    closed = sum(1 for t in task_snapshot.values() if t.get("status") == "closed")
    in_progress = sum(1 for t in task_snapshot.values() if t.get("status") == "in_progress")
    if in_progress > 0 or closed > 0:
        return "on_track", "Work is progressing normally."
    return "watch", "Tasks queued, waiting for agents to pick them up."


# ---------------------------------------------------------------------------
# Narrative synthesis — build context-aware descriptions from artifacts
# ---------------------------------------------------------------------------

def _synthesize_narrative(
    workspace: Path,
    phase: str,
    task_snapshot: dict,
    elapsed_sec: float,
) -> str:
    """Synthesize a 1-2 sentence narrative from workspace artifacts.

    Reads existing files (experiments.tsv, success-criteria.json,
    belief-map.json) to produce a context-aware description of what's
    happening.  Returns '' if not enough data for a meaningful narrative.

    This replaces static phase descriptions with research-aware text —
    no LLM needed, just smart synthesis from what the agents already wrote.
    """
    parts: list[str] = []

    # Experiment results
    rows = _read_all_experiment_rows(workspace)
    keep = sum(1 for r in rows if r.get("status") == "keep")
    discard = sum(1 for r in rows if r.get("status") == "discard")
    total_exp = len(rows)

    # Success criteria
    criteria_data = _read_json(workspace / ".swarm" / "success-criteria.json")
    criteria_met = 0
    criteria_total = 0
    if isinstance(criteria_data, list) and criteria_data:
        criteria_total = len(criteria_data)
        criteria_met = sum(1 for c in criteria_data if c.get("met"))

    # Belief map — leading hypothesis
    leading_hyp = ""
    belief_data = _read_json(workspace / ".swarm" / "belief-map.json")
    if isinstance(belief_data, dict):
        hyps = belief_data.get("hypotheses", [])
        if isinstance(hyps, dict):
            hyps = list(hyps.values())
        if isinstance(hyps, list):
            best = None
            best_conf = -1.0
            for h in hyps:
                if isinstance(h, dict):
                    conf = float(h.get("posterior", h.get("prior", 0)))
                    if conf > best_conf:
                        best_conf = conf
                        best = h
            if best and best_conf > 0:
                name = best.get("name", best.get("label", ""))
                if name:
                    leading_hyp = f"{name} (P={best_conf:.2f})"

    # Task counts
    total_tasks = len(task_snapshot)
    closed = sum(1 for t in task_snapshot.values() if t.get("status") == "closed")

    # Build narrative based on what artifacts exist
    if phase in ("investigating", "reviewing", "synthesizing") and total_exp > 0:
        if keep > 0 and discard > 0:
            parts.append(f"{keep}/{total_exp} experiments passed, {discard} discarded")
        elif keep > 0:
            parts.append(f"{keep}/{total_exp} experiments passed")
        elif total_exp > 0:
            parts.append(f"{total_exp} experiments run so far")

        if criteria_met > 0 and criteria_total > 0:
            ctx = VOICE_CRITERIA_CONTEXT.get(
                "all" if criteria_met == criteria_total
                else "most" if criteria_met / criteria_total > 0.6
                else "some" if criteria_met > 0 else "zero"
            )
            parts.append(f"{criteria_met}/{criteria_total} criteria met — {ctx}")

        if leading_hyp:
            parts.append(f"leading hypothesis: {leading_hyp}")

    elif phase == "converging":
        if criteria_met > 0 and criteria_total > 0:
            parts.append(f"{criteria_met}/{criteria_total} criteria met")
        if leading_hyp:
            parts.append(f"leading hypothesis: {leading_hyp}")
        if total_exp > 0:
            parts.append(f"{total_exp} experiments completed")

    elif phase == "planning" and total_tasks > 0:
        parts.append(f"{total_tasks} experiments designed")
        if criteria_total > 0:
            parts.append(f"{criteria_total} success criteria defined")

    if not parts:
        return ""

    return ". ".join(p.capitalize() if i == 0 else p for i, p in enumerate(parts)) + "."


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
    compact: bool = False,
) -> tuple[str, str]:
    """Build a phase-aware, milestone-driven digest message.

    Returns (message_text, message_type) where message_type is one of
    the MSG_TYPE_* constants, allowing the delivery layer to decide
    whether to edit-in-place or send a new message.

    Adapts structure and detail level to the current phase and elapsed time:
    - Early (setup/planning): set expectations, no empty progress bars
    - Active (investigating): highlight achievements, show pace + ETA
    - Late (reviewing/converging): focus on quality and criteria
    - Complete: celebrate, summarize

    compact=True produces a shorter message suitable for periodic updates.
    compact=False produces the full detailed view (for /details command).
    """
    elapsed_str = format_duration(elapsed_sec)

    total = len(task_snapshot)
    closed = sum(1 for t in task_snapshot.values() if t.get("status") == "closed")
    in_progress = sum(1 for t in task_snapshot.values() if t.get("status") == "in_progress")

    # Categorize recent events
    completed = [e for e in events_since_last if e.get("type") == "task_done"]
    findings = [e for e in events_since_last if e.get("type") == "finding"]
    new_tasks = [e for e in events_since_last if e.get("type") == "task_new"]
    design_invalids = [e for e in events_since_last if e.get("type") == "design_invalid"]

    # Determine if this update contains a milestone worth a new notification
    has_milestone = bool(findings or design_invalids)

    lines: list[str] = []

    # ── Header: codename · elapsed · phase label ──
    step, total_steps = phase_position(phase)
    if step > 0:
        lines.append(f"*{codename}* · {elapsed_str} · Phase {step}/{total_steps}")
    else:
        lines.append(f"*{codename}* · {elapsed_str}")

    # ── Phase narrative: prefer synthesized narrative, fall back to voice ──
    narrative = _synthesize_narrative(workspace, phase, task_snapshot, elapsed_sec)
    if narrative:
        lines.append(narrative)
    else:
        lines.append(phase_description(mode, phase, codename=codename))

    # ── What happened since last update (achievements, not raw events) ──
    milestones: list[str] = []
    if completed:
        titles = [_extract_task_title(e) for e in completed[:5]]
        if len(completed) <= 3:
            for t in titles:
                milestones.append(f"✓ {t}")
        else:
            milestones.append(f"✓ Completed {len(completed)} tasks")
    if findings:
        for f in findings:
            raw = f.get("msg", "")
            if compact:
                title = _compact_finding_line(raw)
            else:
                title = raw.replace("🔬 *NEW FINDING*\n", "").strip()
            milestones.append(f"★ {title}")
    if design_invalids:
        for d in design_invalids:
            milestones.append(f"⚠ {_extract_task_title(d)}")
    if new_tasks and not completed and not findings:
        milestones.append(f"Planned {len(new_tasks)} new tasks")

    if milestones:
        lines.append("")
        for m in milestones:
            lines.append(m)

    # ── Progress: adaptive to phase ──
    is_early = phase in ("starting", "scouting", "planning")

    if total > 0 and closed > 0:
        # Show progress bar only when there's actual completion
        bar = progress_bar(closed, total)
        lines.append(f"\n{bar}  {closed}/{total} tasks")
        eta = estimate_remaining(elapsed_sec, closed, total)
        if eta:
            lines.append(f"⏱ {eta}")
    elif total > 0 and is_early:
        # Early phase: mention task count without an empty progress bar
        lines.append(f"\n{total} tasks planned · agents getting started")
    elif total > 0:
        # Work hasn't started completing yet — brief status
        agent_note = f" · {in_progress} active" if in_progress > 0 else ""
        lines.append(f"\n{total} tasks in pipeline{agent_note}")

    # ── Experiments (if any) ──
    exp_summary = _experiment_summary(workspace)
    if exp_summary:
        lines.append(exp_summary)

    # ── Artifacts (detail view only) ──
    if not compact:
        artifact_summary = _artifact_progress_summary(workspace)
        if artifact_summary:
            lines.append(artifact_summary)

    # ── Success criteria: adaptive display ──
    criteria_summary = _criteria_summary(
        workspace, compact=compact, phase=phase,
        events_since_last=events_since_last,
    )
    if criteria_summary:
        lines.append(f"\n{criteria_summary}")

    # ── Quality score (when available) ──
    if eval_score > 0:
        label = VOICE_QUALITY_LABELS["high"] if eval_score >= 0.75 else (
            VOICE_QUALITY_LABELS["ok"] if eval_score >= 0.50
            else VOICE_QUALITY_LABELS["low"]
        )
        lines.append(f"Quality: {eval_score:.2f} — {label}")

    # ── Track assessment: only surface real problems ──
    track_status, track_reason = assess_track_status(workspace, task_snapshot, eval_score)
    if track_status == "off_track":
        lines.append(f"\n⚠️ {track_reason}")
    elif track_status == "watch" and not is_early:
        # Don't show "watch" warnings during early phases — it's normal
        lines.append(f"\n{track_reason}")

    # ── Agent activity (brief) ──
    if in_progress > 0:
        lines.append(f"\n{in_progress} {'agent' if in_progress == 1 else 'agents'} active")

    # ── Pace info for long-running investigations ──
    if compact and elapsed_sec > 3600 and closed > 0:
        pace_min = (elapsed_sec / 60) / closed
        if pace_min >= 60:
            lines.append(f"Averaging {format_duration(pace_min * 60)} per task")

    msg_type = MSG_TYPE_MILESTONE if has_milestone else MSG_TYPE_STATUS
    return "\n".join(lines), msg_type


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
        phase = inv.get("phase", "")
        mode = inv.get("mode", "discover")
        healthy = inv.get("agents_healthy", 0)
        stuck = inv.get("agents_stuck", 0)
        question = inv.get("question", "")[:80]

        # Header with phase position
        step, total_steps = phase_position(phase)
        if step > 0:
            lines.append(f"*{label}* · {elapsed} · Phase {step}/{total_steps}")
        else:
            lines.append(f"*{label}* · running for {elapsed}")
        if question:
            preview = _clean_question_preview(question, 80)
            lines.append(f"_{preview}_")

        # Phase description
        if phase:
            lines.append(phase_description(mode, phase, codename=label))

        # Progress — adaptive
        if total > 0 and closed > 0:
            bar = progress_bar(closed, total)
            lines.append(f"{bar}  {closed}/{total} tasks")
        elif total > 0:
            agent_note = f" · {in_prog} active" if in_prog > 0 else ""
            lines.append(f"{total} tasks planned{agent_note}")
        else:
            lines.append("Setting up — planning tasks")

        # Agent health (only mention problems)
        if stuck > 0:
            lines.append(f"⚠️ {stuck} agent{'s' if stuck > 1 else ''} stuck")

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


def _compact_finding_line(msg: str, max_len: int = 100) -> str:
    """Extract a short one-liner from a finding message for compact digests."""
    text = msg.replace("🔬 *NEW FINDING*\n", "").strip()
    # Strip "FINDING:" prefix
    upper = text.upper()
    if upper.startswith("FINDING:"):
        text = text[len("FINDING:"):].strip()
    # Take first sentence or clause
    for sep in (". ", " — ", "; "):
        idx = text.find(sep)
        if 0 < idx < max_len:
            text = text[:idx + 1]
            break
    if len(text) > max_len:
        text = text[:max_len - 1] + "…"
    return text


def _experiment_summary(workspace: Path) -> str:
    """Read experiments.tsv and return a one-line summary."""
    rows = _read_all_experiment_rows(workspace)
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


def _criteria_summary(workspace: Path, compact: bool = False,
                      phase: str = "", events_since_last: list[dict] | None = None) -> str:
    """Read success-criteria.json and return an adaptive summary.

    Display strategy:
    - Early phases (compact): just count ("13 criteria defined")
    - Mid phases (compact): count with met ratio ("3/13 criteria met")
    - Late phases / detail view: full list with per-criterion status
    - When criteria are newly met: highlight them specifically

    compact=True: brief count suitable for periodic digests.
    compact=False: full list with per-criterion status.
    """
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

    if compact:
        is_early = phase in ("starting", "scouting", "planning", "")
        if is_early and met == 0:
            return f"{total} success criteria defined"
        ctx = VOICE_CRITERIA_CONTEXT.get(
            "all" if met == total
            else "most" if total > 0 and met / total > 0.6
            else "some" if met > 0 else "zero"
        )
        return f"Criteria: {met}/{total} — {ctx}"

    # Full view: show all criteria
    header = f"Success criteria: {met}/{total} met"
    summaries: list[str] = []
    for c in data:
        cid = c.get("id", "?")
        check = "✓" if c.get("met") else "○"
        desc = c.get("description", "")[:40]
        summaries.append(f"{check} {cid}: {desc}")
    return header + "\n" + "\n".join(summaries)


# ---------------------------------------------------------------------------
# Internal preview helper
# ---------------------------------------------------------------------------

def _clean_question_preview(question: str, max_len: int = 120) -> str:
    """Return a clean single-line preview from a question or PROMPT.md blob.

    Strips markdown heading markers (``#``) and returns the first meaningful
    line, truncated with an ellipsis if needed.
    """
    for line in question.strip().splitlines():
        clean = line.strip().lstrip('#').strip()
        if clean:
            return clean[:max_len] + ("…" if len(clean) > max_len else "")
    return question[:max_len]


# ---------------------------------------------------------------------------
# High-level message formatters (buddy-style)
# ---------------------------------------------------------------------------

def format_launch(codename: str, mode: str, rigor: str, question: str) -> str:
    """Format a launch notification — conversational, not a status log."""
    rigor_desc = RIGOR_DESCRIPTIONS.get(rigor, rigor)
    preview = _clean_question_preview(question)
    return (
        f"*{codename}* is live.\n\n"
        f"_{preview}_\n\n"
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
                   log_tail: str = "", clean_exit: bool = False) -> str:
    """Format a restart notification."""
    if clean_exit:
        lines = [f"*{codename}* — the agent exited early. Restarting (attempt {attempt}/{max_retries})."]
    else:
        lines = [f"*{codename}* — the agent crashed. Restarting (attempt {attempt}/{max_retries})."]
    if log_tail:
        lines.append(f"\nLast output:\n```\n{log_tail[-300:]}\n```")
    return "\n".join(lines)


def format_pause(codename: str, reason: str, elapsed_sec: float,
                 closed: int, total: int) -> str:
    """Format a pause notification — recoverable, action needed."""
    elapsed = format_duration(elapsed_sec)
    lines = [f"⏸ *{codename}* paused after {elapsed}.\n"]
    lines.append(f"Reason: {reason}")
    if total > 0:
        lines.append(f"Progress: {closed}/{total} tasks completed.")
    lines.append(
        "\nFix the issue, then send `/voronoi resume` to continue."
    )
    return "\n".join(lines)

