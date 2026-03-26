"""Workspace state compaction — keeps state files lean for long-running investigations.

Called periodically by the dispatcher.  Archives old rows from experiments.tsv,
old events from events.jsonl, and writes a compact state-digest.md that the
orchestrator reads instead of querying individual files.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("voronoi.compact")

# How many recent experiment rows to keep in the active file
_EXPERIMENTS_KEEP = 20

# How many recent events to keep in the active log
_EVENTS_KEEP_HOURS = 2


def compact_workspace_state(workspace: Path) -> bool:
    """Run all compaction steps on a workspace.  Returns True if anything changed."""
    changed = False
    swarm = workspace / ".swarm"
    if not swarm.is_dir():
        return False

    changed |= _compact_experiments(swarm)
    changed |= _compact_events(swarm)
    changed |= _write_state_digest(workspace)
    return changed


# ------------------------------------------------------------------
# Experiments TSV rotation
# ------------------------------------------------------------------

def _compact_experiments(swarm: Path) -> bool:
    tsv = swarm / "experiments.tsv"
    if not tsv.exists():
        return False
    try:
        lines = tsv.read_text().splitlines()
    except OSError:
        return False
    if len(lines) <= _EXPERIMENTS_KEEP + 1:  # +1 for header
        return False

    header = lines[0]
    data_lines = lines[1:]
    archive = swarm / "experiments.archive.tsv"

    # Append old lines to archive
    old_lines = data_lines[:-_EXPERIMENTS_KEEP]
    try:
        with open(archive, "a") as f:
            if not archive.exists() or archive.stat().st_size == 0:
                f.write(header + "\n")
            for line in old_lines:
                f.write(line + "\n")
    except OSError as e:
        logger.warning("Failed to write experiments archive: %s", e)
        return False

    # Rewrite active file with header + recent rows
    recent = data_lines[-_EXPERIMENTS_KEEP:]
    try:
        tsv.write_text(header + "\n" + "\n".join(recent) + "\n")
    except OSError as e:
        logger.warning("Failed to compact experiments.tsv: %s", e)
        return False

    logger.info("Compacted experiments.tsv: archived %d rows, kept %d",
                len(old_lines), len(recent))
    return True


# ------------------------------------------------------------------
# Event log rotation
# ------------------------------------------------------------------

def _compact_events(swarm: Path) -> bool:
    events_file = swarm / "events.jsonl"
    if not events_file.exists():
        return False
    try:
        raw = events_file.read_text()
    except OSError:
        return False

    lines = [l for l in raw.strip().splitlines() if l.strip()]
    if len(lines) < 50:  # don't bother for small logs
        return False

    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - (_EVENTS_KEEP_HOURS * 3600)
    recent: list[str] = []
    old: list[str] = []

    for line in lines:
        try:
            event = json.loads(line)
            ts = event.get("ts", event.get("timestamp", 0))
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts).timestamp()
            else:
                ts = float(ts)
            if ts < cutoff:
                old.append(line)
            else:
                recent.append(line)
        except (json.JSONDecodeError, TypeError, ValueError):
            recent.append(line)  # keep unparseable lines

    if not old:
        return False

    archive = swarm / "events.archive.jsonl"
    try:
        with open(archive, "a") as f:
            for line in old:
                f.write(line + "\n")
    except OSError as e:
        logger.warning("Failed to write events archive: %s", e)
        return False

    try:
        events_file.write_text("\n".join(recent) + "\n" if recent else "")
    except OSError as e:
        logger.warning("Failed to compact events.jsonl: %s", e)
        return False

    logger.info("Compacted events.jsonl: archived %d events, kept %d",
                len(old), len(recent))
    return True


# ------------------------------------------------------------------
# State digest — compact summary for orchestrator OODA reads
# ------------------------------------------------------------------

def _write_state_digest(workspace: Path) -> bool:
    """Write .swarm/state-digest.md — a compact summary of investigation state."""
    swarm = workspace / ".swarm"
    lines: list[str] = ["# State Digest (auto-generated)\n"]

    # Success criteria
    sc_path = swarm / "success-criteria.json"
    if sc_path.exists():
        try:
            criteria = json.loads(sc_path.read_text())
            if isinstance(criteria, list) and criteria:
                met = sum(1 for c in criteria if c.get("met"))
                lines.append(f"## Success Criteria: {met}/{len(criteria)} met\n")
                for c in criteria:
                    status = "MET" if c.get("met") else "PENDING"
                    lines.append(f"- [{status}] {c.get('id', '?')}: {c.get('description', '')}")
                lines.append("")
        except (json.JSONDecodeError, OSError):
            pass

    # Experiment summary from TSV
    tsv = swarm / "experiments.tsv"
    if tsv.exists():
        try:
            rows = tsv.read_text().strip().splitlines()[1:]  # skip header
            total = len(rows)
            # Also count archived rows
            archive = swarm / "experiments.archive.tsv"
            if archive.exists():
                archive_rows = archive.read_text().strip().splitlines()[1:]
                total += len(archive_rows)
            keep = sum(1 for r in rows if "\tkeep\t" in r)
            crash = sum(1 for r in rows if "\tcrash\t" in r)
            discard = sum(1 for r in rows if "\tdiscard\t" in r)
            lines.append(f"## Experiments: {total} total ({keep} keep, {crash} crash, {discard} discard)\n")
        except OSError:
            pass

    # Active branches
    try:
        import subprocess
        result = subprocess.run(
            ["git", "branch", "--list", "agent-*"],
            capture_output=True, text=True, timeout=10,
            cwd=str(workspace),
        )
        if result.returncode == 0 and result.stdout.strip():
            branches = [b.strip().lstrip("* ") for b in result.stdout.strip().splitlines()]
            lines.append(f"## Active Branches: {len(branches)}\n")
            for b in branches[-10:]:  # last 10
                lines.append(f"- {b}")
            lines.append("")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Checkpoint summary
    cp_path = swarm / "orchestrator-checkpoint.json"
    if cp_path.exists():
        try:
            cp = json.loads(cp_path.read_text())
            if isinstance(cp, dict):
                lines.append(f"## Checkpoint: cycle {cp.get('cycle', 0)}, phase: {cp.get('phase', '?')}")
                lines.append(f"Tasks: {cp.get('closed_tasks', 0)}/{cp.get('total_tasks', 0)} done")
                dead = cp.get("dead_ends", [])
                if dead:
                    lines.append("\nDead ends (DO NOT re-explore):")
                    for d in dead:
                        lines.append(f"- {d}")
                lines.append("")
        except (json.JSONDecodeError, OSError):
            pass

    if len(lines) <= 1:  # nothing to summarize
        return False

    digest_path = swarm / "state-digest.md"
    try:
        digest_path.write_text("\n".join(lines) + "\n")
        logger.info("Wrote state-digest.md (%d lines)", len(lines))
        return True
    except OSError as e:
        logger.warning("Failed to write state-digest.md: %s", e)
        return False
