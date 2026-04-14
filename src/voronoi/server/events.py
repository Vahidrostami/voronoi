"""Structured event log for investigation observability.

Workers and the orchestrator append structured events to
``.swarm/events.jsonl`` during execution.  The dispatcher reads these
events for real-time monitoring, stall detection, and post-mortem
analysis.

Design: append-only JSONL — one JSON object per line.  No locking
required because each agent writes to its own branch/worktree and the
dispatcher only reads the main workspace copy.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("voronoi.events")


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------

@dataclass
class SwarmEvent:
    """A single structured event in the investigation event log."""

    ts: float = field(default_factory=time.time)
    agent: str = ""          # e.g. "orchestrator", "investigator", branch name
    task_id: str = ""        # Beads task ID
    event: str = ""          # e.g. "tool_call", "finding_committed", "test_pass"
    status: str = ""         # e.g. "ok", "fail", "skip"
    detail: str = ""         # Human-readable detail (truncated if long)
    tokens_used: int = 0     # Estimated tokens consumed by this action

    def to_json(self) -> str:
        d = asdict(self)
        # Truncate detail to prevent log bloat
        if len(d.get("detail", "")) > 500:
            d["detail"] = d["detail"][:497] + "..."
        return json.dumps(d, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Writer — used by workers and orchestrator
# ---------------------------------------------------------------------------

def append_event(workspace: Path, event: SwarmEvent) -> None:
    """Append a single event to the workspace event log.

    Creates ``.swarm/events.jsonl`` if it doesn't exist.  Safe to call
    from any agent — the JSONL format is append-friendly.
    """
    log_path = workspace / ".swarm" / "events.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_path, "a") as f:
            f.write(event.to_json() + "\n")
    except OSError as e:
        logger.warning("Failed to write event to %s: %s", log_path, e)


def log_tool_call(
    workspace: Path,
    *,
    agent: str,
    task_id: str,
    tool: str,
    status: str = "ok",
    detail: str = "",
    tokens_used: int = 0,
) -> None:
    """Convenience: log a tool invocation event."""
    append_event(workspace, SwarmEvent(
        agent=agent, task_id=task_id, event="tool_call",
        status=status, detail=f"{tool}: {detail}" if detail else tool,
        tokens_used=tokens_used,
    ))


def log_finding(
    workspace: Path,
    *,
    agent: str,
    task_id: str,
    finding_id: str,
    detail: str = "",
) -> None:
    """Convenience: log a finding committed to Beads."""
    append_event(workspace, SwarmEvent(
        agent=agent, task_id=task_id, event="finding_committed",
        status="ok", detail=f"{finding_id}: {detail}" if detail else finding_id,
    ))


def log_test_result(
    workspace: Path,
    *,
    agent: str,
    task_id: str,
    passed: bool,
    attempt: int = 1,
    detail: str = "",
) -> None:
    """Convenience: log a test run result."""
    append_event(workspace, SwarmEvent(
        agent=agent, task_id=task_id,
        event="test_run",
        status="pass" if passed else "fail",
        detail=f"attempt {attempt}: {detail}" if detail else f"attempt {attempt}",
    ))


def log_verify_step(
    workspace: Path,
    *,
    agent: str,
    task_id: str,
    step: str,
    passed: bool,
    detail: str = "",
) -> None:
    """Convenience: log a self-verification step result."""
    append_event(workspace, SwarmEvent(
        agent=agent, task_id=task_id,
        event="verify_step",
        status="pass" if passed else "fail",
        detail=f"{step}: {detail}" if detail else step,
    ))


def log_serendipity(
    workspace: Path,
    *,
    agent: str,
    task_id: str,
    description: str,
) -> None:
    """Convenience: log a serendipitous/unexpected observation."""
    append_event(workspace, SwarmEvent(
        agent=agent, task_id=task_id, event="serendipity",
        status="ok", detail=description,
    ))


def log_context_snapshot(
    workspace: Path,
    *,
    agent: str,
    cycle: int = 0,
    model: str = "",
    model_limit: int = 0,
    total_used: int = 0,
    system_tokens: int = 0,
    message_tokens: int = 0,
    free_tokens: int = 0,
    buffer_tokens: int = 0,
) -> None:
    """Convenience: log a /context snapshot for timeline analysis."""
    parts = []
    if model:
        parts.append(model)
    if model_limit:
        parts.append(f"{total_used}/{model_limit}")
    if system_tokens:
        parts.append(f"sys={system_tokens}")
    if message_tokens:
        parts.append(f"msg={message_tokens}")
    if free_tokens:
        parts.append(f"free={free_tokens}")
    if buffer_tokens:
        parts.append(f"buf={buffer_tokens}")
    detail_str = f"cycle={cycle} " + " ".join(parts)
    append_event(workspace, SwarmEvent(
        agent=agent, task_id="",
        event="context_snapshot",
        status="ok",
        detail=detail_str.strip(),
        tokens_used=total_used,
    ))


# ---------------------------------------------------------------------------
# Reader — used by dispatcher for monitoring
# ---------------------------------------------------------------------------

def read_events(
    workspace: Path,
    *,
    since: float = 0,
    max_events: int = 100,
) -> list[SwarmEvent]:
    """Read recent events from the event log.

    Parameters
    ----------
    workspace : Path
        Investigation workspace root.
    since : float
        Only return events with ``ts > since`` (unix timestamp).
    max_events : int
        Maximum events to return (most recent first).

    Returns
    -------
    list[SwarmEvent]
        Events in chronological order (oldest first), capped at max_events.
    """
    log_path = workspace / ".swarm" / "events.jsonl"
    if not log_path.exists():
        return []

    events: list[SwarmEvent] = []
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if not isinstance(d, dict):
                        continue
                    ts = float(d.get("ts", 0))
                    if ts <= since:
                        continue
                    events.append(SwarmEvent(
                        ts=ts,
                        agent=d.get("agent", ""),
                        task_id=d.get("task_id", ""),
                        event=d.get("event", ""),
                        status=d.get("status", ""),
                        detail=d.get("detail", ""),
                        tokens_used=int(d.get("tokens_used", 0)),
                    ))
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
    except OSError as e:
        logger.warning("Failed to read events from %s: %s", log_path, e)
        return []

    # Return last max_events in chronological order
    if len(events) > max_events:
        events = events[-max_events:]
    return events


def summarize_events(
    workspace: Path,
    *,
    since: float = 0,
) -> dict:
    """Produce a summary of recent event activity.

    Returns a dict with counts by event type and agent, total tokens,
    plus a ``last_event_ts`` for use as the next ``since`` value.
    """
    events = read_events(workspace, since=since, max_events=500)
    if not events:
        return {"count": 0, "last_event_ts": since}

    by_event: dict[str, int] = {}
    by_agent: dict[str, int] = {}
    total_tokens = 0
    fails = 0

    for e in events:
        by_event[e.event] = by_event.get(e.event, 0) + 1
        if e.agent:
            by_agent[e.agent] = by_agent.get(e.agent, 0) + 1
        total_tokens += e.tokens_used
        if e.status == "fail":
            fails += 1

    return {
        "count": len(events),
        "by_event": by_event,
        "by_agent": by_agent,
        "total_tokens": total_tokens,
        "failures": fails,
        "last_event_ts": events[-1].ts,
    }
