"""Mutation handlers for Voronoi commands.

Task and investigation state changes: reprioritize, pause, resume,
add, complete, abort, pivot, guide, approve/revise gates.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from voronoi.beads import has_beads_dir


def _run_bd(*args: str, cwd: str | None = None) -> tuple[int, str]:
    from voronoi.beads import run_bd
    if cwd and not has_beads_dir(cwd):
        return 1, ""
    return run_bd(*args, cwd=cwd)


def _get_queue(project_dir: str):
    from voronoi.server.queue import InvestigationQueue
    base = Path.home() / ".voronoi"
    return InvestigationQueue(base / "queue.db")


def _get_active_workspaces(project_dir: str) -> list[tuple[str, str]]:
    q = _get_queue(project_dir)
    results = []
    for inv in q.get_running():
        if inv.workspace_path:
            label = inv.codename or f"#{inv.id}"
            results.append((inv.workspace_path, label))
    return results


def _get_first_active_workspace(project_dir: str) -> Optional[str]:
    ws_list = _get_active_workspaces(project_dir)
    return ws_list[0][0] if ws_list else None


def handle_reprioritize(project_dir: str, task_id: str, priority: str) -> str:
    for ws_path, _ in _get_active_workspaces(project_dir):
        code, output = _run_bd("update", task_id, "--priority", priority, cwd=ws_path)
        if code == 0:
            return f"✅ Task `{task_id}` priority set to {priority}"
    code, output = _run_bd("update", task_id, "--priority", priority, cwd=project_dir)
    if code != 0:
        return f"❌ Failed: {output}"
    return f"✅ Task `{task_id}` priority set to {priority}"


def handle_pause(project_dir: str, task_id: str) -> str:
    for ws_path, _ in _get_active_workspaces(project_dir):
        code, _ = _run_bd("show", task_id, "--json", cwd=ws_path)
        if code == 0:
            _run_bd("update", task_id, "--notes",
                    "BLOCKED: Paused by operator via Telegram", cwd=ws_path)
            return f"⏸ Task `{task_id}` paused"
    _run_bd("update", task_id, "--notes",
            "BLOCKED: Paused by operator via Telegram", cwd=project_dir)
    return f"⏸ Task `{task_id}` paused"


def handle_resume(project_dir: str, task_id: str) -> str:
    for ws_path, _ in _get_active_workspaces(project_dir):
        code, _ = _run_bd("show", task_id, "--json", cwd=ws_path)
        if code == 0:
            _run_bd("update", task_id, "--status", "open", cwd=ws_path)
            return f"▶️ Task `{task_id}` resumed"
    _run_bd("update", task_id, "--status", "open", cwd=project_dir)
    return f"▶️ Task `{task_id}` resumed"


def handle_resume_investigation(project_dir: str, identifier: str) -> str:
    """Resume a paused or failed investigation by ID or codename."""
    from voronoi.server.queue import InvestigationQueue

    db_path = Path.home() / ".voronoi" / "queue.db"
    if not db_path.exists():
        return "❌ No investigation queue found."

    queue = InvestigationQueue(db_path)

    inv = None
    try:
        inv_id = int(identifier)
        inv = queue.get(inv_id)
    except (ValueError, TypeError):
        pass

    if inv is None:
        needle = identifier.lower().strip()
        for candidate in queue.get_recent(limit=50):
            if candidate.codename and candidate.codename.lower() == needle:
                inv = candidate
                break

    if inv is None:
        return f"❌ No investigation matching `{identifier}`."
    if inv.status not in ("paused", "failed"):
        return f"❌ *{inv.codename or f'#{inv.id}'}* is {inv.status} — can only resume paused or failed."

    try:
        from voronoi.server.dispatcher import _active_dispatcher
        dispatcher = _active_dispatcher()
        if dispatcher is not None:
            return dispatcher.resume_investigation(inv.id)
    except (ImportError, Exception):
        pass

    if not queue.resume(inv.id):
        return f"❌ Failed to resume #{inv.id}."
    label = inv.codename or f"#{inv.id}"
    return f"▶️ *{label}* marked as running — it will be picked up on next dispatch cycle."


def handle_add(project_dir: str, title: str) -> str:
    ws_path = _get_first_active_workspace(project_dir) or project_dir
    code, output = _run_bd(
        "create", title, "-t", "task", "-p", "1", "--json",
        cwd=ws_path,
    )
    if code != 0:
        return f"❌ Failed to create task: {output}"
    try:
        new_id = json.loads(output).get("id", "?")
    except Exception:
        new_id = "?"
    return f"✅ Created task `{new_id}`: {title}"


def handle_complete(project_dir: str, task_id: str, reason: str = "Completed") -> str:
    """Close a task via ``bd close``."""
    for ws_path, _ in _get_active_workspaces(project_dir):
        code, output = _run_bd("close", task_id, "--reason", reason, cwd=ws_path)
        if code == 0:
            return f"✅ Task `{task_id}` closed: {reason}"
    code, output = _run_bd("close", task_id, "--reason", reason, cwd=project_dir)
    if code != 0:
        return f"❌ Failed to close: {output}"
    return f"✅ Task `{task_id}` closed: {reason}"


def handle_complete_investigation(project_dir: str, identifier: str) -> str:
    """Accept and close an investigation that is in review status."""
    q = _get_queue(project_dir)
    inv = _find_investigation(q, identifier)
    if inv is None:
        return f"❌ Investigation *{identifier}* not found."

    label = inv.codename or f"#{inv.id}"

    if inv.status == "complete":
        return f"✅ *{label}* is already complete."

    if inv.status != "review":
        return (
            f"❌ *{label}* is {inv.status} — "
            f"can only accept from review."
        )

    ok = q.accept(inv.id)
    if not ok:
        return f"❌ Failed to close *{label}*."

    return f"✅ *{label}* accepted and closed."


def handle_review_investigation(project_dir: str, identifier: str) -> str:
    """Show the Claim Ledger for an investigation in review format."""
    q = _get_queue(project_dir)
    inv = _find_investigation(q, identifier)
    if inv is None:
        return f"❌ Investigation *{identifier}* not found."

    lineage_id = inv.lineage_id or inv.id
    from voronoi.science.claims import load_ledger
    base_dir = q.db_path.parent
    ledger = load_ledger(lineage_id, base_dir=base_dir)

    if not ledger.claims:
        return (
            f"🔬 *{inv.codename or f'#{inv.id}'}* — no claims recorded yet.\n"
            f"Status: {inv.status} | Mode: {inv.mode} | Round: {inv.cycle_number}"
        )

    header = (
        f"🔬 *{inv.codename or f'#{inv.id}'}* — "
        f"Round {inv.cycle_number} | {inv.status}\n\n"
    )
    return header + ledger.format_for_review()


def handle_continue_investigation(project_dir: str, identifier: str,
                                  feedback: str = "") -> str:
    """Continue an investigation with optional PI feedback."""
    q = _get_queue(project_dir)
    inv = _find_investigation(q, identifier)
    if inv is None:
        return f"❌ Investigation *{identifier}* not found."

    failed_partial = inv.status == "failed" and _has_partial_artifacts(inv)
    if inv.status not in ("review", "complete") and not failed_partial:
        return (
            f"❌ *{inv.codename or f'#{inv.id}'}* is {inv.status} — "
            f"can only continue from review, complete, or a diagnosed partial run. "
            f"Use `/voronoi resume {inv.codename or f'#{inv.id}'}` to retry."
        )

    lineage_id = inv.lineage_id or inv.id
    base_dir = q.db_path.parent

    # No-info guard (BUG-001 / BUG-007): refuse to start a new round when
    # there is nothing new to act on.  Without this, `voronoi continue`
    # against a fully-converged investigation re-runs the same finisher
    # chain indefinitely, burning tokens with zero belief-map delta.
    if not _has_continuation_signal(inv, feedback.strip(), lineage_id, base_dir):
        label = inv.codename or f"#{inv.id}"
        return (
            f"🛑 *{label}* has already converged with a manuscript and you "
            f"provided no new information.\n\n"
            f"Continuing now would re-run the same post-processing chain "
            f"on identical data — no new experiments, no belief-map delta.\n\n"
            f"To proceed, do one of:\n"
            f"• `/voronoi deliberate {label}` — discuss what to pivot to\n"
            f"• `/voronoi continue {label} challenge C<id>: <reason>` — "
            f"lodge a specific objection\n"
            f"• `/voronoi continue {label} <concrete new direction>` — "
            f"give a scope/direction change\n"
            f"• `/voronoi complete {label}` — accept the result as final"
        )

    if feedback:
        _process_feedback(lineage_id, feedback, base_dir)

    new_id = q.continue_investigation(inv.id, feedback)
    if new_id is None:
        return f"❌ Failed to continue *{inv.codename or f'#{inv.id}'}*."

    new_inv = q.get(new_id)
    label = inv.codename or f"#{inv.id}"
    round_num = new_inv.cycle_number if new_inv else "?"
    return (
        f"🔄 *{label}* — Round {round_num} queued.\n"
        + (f"Feedback recorded: _{feedback[:100]}_" if feedback else "No additional feedback.")
    )


def handle_abort(project_dir: str) -> str:
    q = _get_queue(project_dir)
    cancelled = 0
    for inv in q.get_queued():
        if q.cancel(inv.id):
            cancelled += 1

    for ws_path, _ in _get_active_workspaces(project_dir):
        signal_dir = Path(ws_path) / ".swarm"
        signal_dir.mkdir(parents=True, exist_ok=True)
        (signal_dir / "abort-signal").write_text("abort\n")
    global_signal = Path.home() / ".voronoi" / ".swarm"
    global_signal.mkdir(parents=True, exist_ok=True)
    (global_signal / "abort-signal").write_text("abort\n")

    parts = ["🛑 *Abort requested*"]
    if cancelled:
        parts.append(f"Cancelled {cancelled} queued investigation(s).")
    parts.append("Running investigations will be stopped on next progress check (~30s).")
    return "\n".join(parts)


def handle_pivot(project_dir: str, message: str) -> str:
    ws_list = _get_active_workspaces(project_dir)
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    written_to = []
    for ws_path, label in ws_list:
        guidance_dir = Path(ws_path) / ".swarm"
        guidance_dir.mkdir(parents=True, exist_ok=True)
        with open(guidance_dir / "operator-guidance.md", "a") as f:
            f.write(f"\n## Pivot — {ts}\n\n{message}\n")
        written_to.append(label)
    if not written_to:
        guidance_dir = Path(project_dir) / ".swarm"
        guidance_dir.mkdir(parents=True, exist_ok=True)
        with open(guidance_dir / "operator-guidance.md", "a") as f:
            f.write(f"\n## Pivot — {ts}\n\n{message}\n")
    dest = ", ".join(written_to) if written_to else "project"
    return f"🔀 *Pivot recorded* ({dest})\n\n_{message}_\nAgents will read this on next dispatch."


def handle_guide(project_dir: str, message: str) -> str:
    ws_list = _get_active_workspaces(project_dir)
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    written_to = []
    for ws_path, label in ws_list:
        guidance_dir = Path(ws_path) / ".swarm"
        guidance_dir.mkdir(parents=True, exist_ok=True)
        with open(guidance_dir / "operator-guidance.md", "a") as f:
            f.write(f"\n## Guidance — {ts}\n\n{message}\n")
        written_to.append(label)
    if not written_to:
        guidance_dir = Path(project_dir) / ".swarm"
        guidance_dir.mkdir(parents=True, exist_ok=True)
        with open(guidance_dir / "operator-guidance.md", "a") as f:
            f.write(f"\n## Guidance — {ts}\n\n{message}\n")
    dest = ", ".join(written_to) if written_to else "project"
    return f"📝 *Guidance noted* ({dest})\n\n_{message}_"


def handle_extend(
    project_dir: str, identifier: str, minutes_str: str = "",
) -> str:
    """Grant additional stall budget to a running investigation.

    Wired to ``/voronoi extend <codename> [minutes]`` — the strike-2
    Telegram notification prompts the PI with this exact command.
    Defaults to 60 minutes when ``minutes_str`` is empty. See SERVER.md §3.
    """
    identifier = (identifier or "").strip()
    if not identifier:
        return (
            "Usage: `/voronoi extend <codename> [minutes]`\n\n"
            "Example: `/voronoi extend Serotonin 60` — grants 60 extra "
            "minutes before partial review and clears the stall directive."
        )
    minutes = 60
    if minutes_str:
        try:
            minutes = int(minutes_str)
        except ValueError:
            return f"❌ `{minutes_str}` is not a valid integer number of minutes."
    if minutes <= 0 or minutes > 6 * 60:
        return "❌ `minutes` must be between 1 and 360."
    from voronoi.server.dispatcher import _active_dispatcher
    dispatcher = _active_dispatcher()
    if dispatcher is None:
        return (
            "❌ No active dispatcher — extend is only meaningful while a "
            "run is in progress. Is `voronoi server start` running?"
        )
    return dispatcher.extend_run(identifier, minutes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_continuation_signal(inv, feedback: str, lineage_id: int,
                              base_dir: Path) -> bool:
    """Decide whether a ``continue`` call carries any new information.

    Returns False only when ALL of the following hold:
      - the prior run converged with ``gate_passed=true``
      - a manuscript deliverable exists (``paper.tex`` or ``deliverable.md``)
      - feedback is empty
      - no unresolved (pending) objections exist on the ledger

    In every other case we allow continuation — free-text feedback, a
    pending objection, or an unconverged prior run all count as "there
    is something new to do".  Goal is narrow: block the zero-information
    rerun of an already-finished investigation that would otherwise just
    re-run the Scribe/Evaluator finisher chain on identical data.
    """
    if feedback:
        return True

    if _has_partial_artifacts(inv):
        return True

    try:
        from voronoi.science.claims import load_ledger
        ledger = load_ledger(lineage_id, base_dir=base_dir)
        if ledger.get_pending_objections():
            return True
    except Exception:  # pragma: no cover — ledger load should never block
        pass

    ws = getattr(inv, "workspace_path", None)
    if not ws:
        return True
    ws_path = Path(ws)
    try:
        conv = json.loads((ws_path / ".swarm" / "convergence.json").read_text())
        if not bool(conv.get("gate_passed")):
            return True
    except (OSError, json.JSONDecodeError):
        return True

    has_paper = any((ws_path / name).exists() for name in (
        "paper.tex", "deliverable.md",
    ))
    if not has_paper:
        has_paper = (ws_path / ".swarm" / "manuscript" / "paper.tex").exists()
    if not has_paper:
        return True

    return False


def _has_partial_artifacts(inv) -> bool:
    """Return True when prior run has durable partial-review context."""
    from voronoi.server.queue import has_partial_continuation_artifact
    return has_partial_continuation_artifact(inv)


def _find_investigation(q, identifier: str):
    """Find an investigation by ID or codename."""
    try:
        inv_id = int(identifier)
        return q.get(inv_id)
    except (ValueError, TypeError):
        pass
    recent = q.get_recent(limit=50)
    for inv in recent:
        if inv.codename and inv.codename.lower() == identifier.lower():
            return inv
    return None


def _process_feedback(lineage_id: int, feedback: str, base_dir: Path) -> None:
    """Parse natural-language feedback into claim ledger operations."""
    from voronoi.science.claims import load_ledger, save_ledger

    ledger = load_ledger(lineage_id, base_dir=base_dir)
    if not ledger.claims:
        return

    changed = False
    lines = feedback.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue

        lock_match = re.match(r"lock\s+(C\d+(?:\s+C\d+)*)", line, re.IGNORECASE)
        if lock_match:
            for cid in re.findall(r"C\d+", lock_match.group(1)):
                claim = ledger.get_claim(cid)
                if claim and claim.status in ("provisional", "asserted"):
                    try:
                        if claim.status == "provisional":
                            ledger.assert_claim(cid)
                        ledger.lock_claim(cid)
                        changed = True
                    except (ValueError, KeyError):
                        pass
            continue

        challenge_match = re.match(
            r"challenge\s+(C\d+)[:\s]+(.+)", line, re.IGNORECASE
        )
        if challenge_match:
            cid = challenge_match.group(1)
            reason = challenge_match.group(2).strip()
            claim = ledger.get_claim(cid)
            if claim and claim.status not in ("retired",):
                try:
                    ledger.challenge_claim(cid, reason, raised_by="PI")
                    changed = True
                except (ValueError, KeyError):
                    pass
            continue

    if changed:
        save_ledger(lineage_id, ledger, base_dir=base_dir)
