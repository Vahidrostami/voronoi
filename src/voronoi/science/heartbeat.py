"""Heartbeats, lab notebook, and LLM-as-Judge primitive."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("voronoi.science")


# ---------------------------------------------------------------------------
# Lab Notebook
# ---------------------------------------------------------------------------

@dataclass
class LabNotebookEntry:
    """A single entry in the lab notebook."""
    cycle: int
    phase: str
    verdict: str  # pass, fail, iterate, blocked
    metrics: dict = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    timestamp: str = ""


def load_lab_notebook(workspace: Path) -> list[LabNotebookEntry]:
    """Load the lab notebook from .swarm/lab-notebook.json."""
    path = workspace / ".swarm" / "lab-notebook.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        entries = []
        for e in data.get("entries", []):
            entries.append(LabNotebookEntry(
                cycle=e.get("cycle", 0),
                phase=e.get("phase", ""),
                verdict=e.get("verdict", ""),
                metrics=e.get("metrics", {}),
                failures=e.get("failures", []),
                next_steps=e.get("next_steps", []),
                timestamp=e.get("timestamp", ""),
            ))
        return entries
    except (json.JSONDecodeError, OSError):
        return []


def append_lab_notebook(workspace: Path, entry: LabNotebookEntry) -> None:
    """Append an entry to the lab notebook."""
    entries = load_lab_notebook(workspace)
    entry.timestamp = datetime.now(timezone.utc).isoformat()
    entries.append(entry)
    path = workspace / ".swarm" / "lab-notebook.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"entries": [asdict(e) for e in entries]}
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Structured Heartbeats
# ---------------------------------------------------------------------------

@dataclass
class Heartbeat:
    """A single heartbeat from a running agent."""
    branch: str
    phase: str
    iteration: int
    last_action: str
    status: str
    timestamp: str = ""


def write_heartbeat(workspace: Path, heartbeat: Heartbeat) -> None:
    """Append a heartbeat entry to .swarm/heartbeat-<branch>.jsonl."""
    heartbeat.timestamp = datetime.now(timezone.utc).isoformat()
    path = workspace / ".swarm" / f"heartbeat-{heartbeat.branch}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(asdict(heartbeat)) + "\n")


def read_heartbeats(workspace: Path, branch: str,
                    last_n: int = 10) -> list[Heartbeat]:
    """Read last N heartbeats for a branch."""
    path = workspace / ".swarm" / f"heartbeat-{branch}.jsonl"
    if not path.exists():
        return []
    heartbeats: list[Heartbeat] = []
    try:
        lines = path.read_text().strip().split("\n")
        for line in lines[-last_n:]:
            if not line.strip():
                continue
            data = json.loads(line)
            heartbeats.append(Heartbeat(
                branch=data.get("branch", branch),
                phase=data.get("phase", ""),
                iteration=data.get("iteration", 0),
                last_action=data.get("last_action", ""),
                status=data.get("status", ""),
                timestamp=data.get("timestamp", ""),
            ))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read heartbeats for %s: %s", branch, e)
    return heartbeats


def check_heartbeat_stall(workspace: Path, branch: str,
                          stall_minutes: int = 10) -> bool:
    """Return True if the agent appears stalled (same status for stall_minutes)."""
    beats = read_heartbeats(workspace, branch, last_n=5)
    if len(beats) < 2:
        return False
    signatures = {(b.phase, b.status) for b in beats}
    if len(signatures) > 1:
        return False
    try:
        first_ts = datetime.fromisoformat(beats[0].timestamp)
        last_ts = datetime.fromisoformat(beats[-1].timestamp)
        span = (last_ts - first_ts).total_seconds() / 60
        return span >= stall_minutes
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# LLM-as-Judge Primitive
# ---------------------------------------------------------------------------

@dataclass
class JudgeVerdict:
    """Structured verdict from an LLM judge call."""
    match: bool
    confidence: float
    justification: str
    rubric_id: str = ""
    model: str = ""


@dataclass
class JudgeRubric:
    """Structured evaluation rubric for LLM judge calls."""
    rubric_id: str
    criteria: str
    scale: str = "binary"
    examples: str = ""


def format_judge_prompt(rubric: JudgeRubric, candidate: str,
                       reference: str) -> str:
    """Format a structured judge prompt from rubric + candidate + reference."""
    parts = [
        "You are an evaluation judge. Assess whether the candidate matches "
        "the reference according to the rubric below.\n",
        f"## Rubric\n{rubric.criteria}\n",
        f"## Scale\n{rubric.scale}\n",
    ]
    if rubric.examples:
        parts.append(f"## Examples\n{rubric.examples}\n")
    parts.append(f"## Reference\n{reference}\n")
    parts.append(f"## Candidate\n{candidate}\n")
    parts.append(
        "## Your Verdict\n"
        "Respond with EXACTLY this JSON (no other text):\n"
        '{"match": true/false, "confidence": 0.0-1.0, "justification": "..."}\n'
    )
    return "\n".join(parts)


def parse_judge_verdict(raw_output: str, rubric_id: str = "",
                       model: str = "") -> JudgeVerdict:
    """Parse a judge verdict from raw LLM output."""
    json_match = re.search(r'\{[^{}]*"match"[^{}]*\}', raw_output, re.S)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return JudgeVerdict(
                match=bool(data.get("match", False)),
                confidence=float(data.get("confidence", 0.0)),
                justification=str(data.get("justification", "")),
                rubric_id=rubric_id,
                model=model,
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    lower = raw_output.lower()
    if '"match": true' in lower:
        match_val = True
    elif '"match": false' in lower:
        match_val = False
    else:
        match_val = "yes" in lower.split("\n")[0]
    return JudgeVerdict(
        match=match_val,
        confidence=0.5,
        justification=raw_output[:200],
        rubric_id=rubric_id,
        model=model,
    )


def log_judge_call(workspace: Path, rubric: JudgeRubric,
                   verdict: JudgeVerdict) -> None:
    """Append a judge call to the experiment ledger."""
    path = workspace / ".swarm" / "judge-log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rubric_id": rubric.rubric_id,
        "rubric_criteria": rubric.criteria[:200],
        "scale": rubric.scale,
        "match": verdict.match,
        "confidence": verdict.confidence,
        "justification": verdict.justification[:500],
        "model": verdict.model,
    }
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
