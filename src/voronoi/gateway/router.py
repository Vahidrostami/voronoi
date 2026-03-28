"""Command router — central dispatch for all Voronoi commands.

Every user action (Telegram command, free-text, CLI) flows through
the public functions in this module.  The Telegram bridge and any
future UI are thin I/O layers that call these functions and send
the result.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from voronoi.beads import run_bd, has_beads_dir
from voronoi.gateway.intent import ClassifiedIntent, WorkflowMode, classify
from voronoi.gateway.progress import (
    MODE_EMOJI, RIGOR_DESCRIPTIONS, MODE_VERB,
    build_digest_whatsup, build_digest, phase_description, format_duration,
    assess_track_status, _criteria_summary, _experiment_summary,
    progress_bar, _clean_question_preview,
)
from voronoi.server.queue import Investigation, InvestigationQueue
from voronoi.server.runner import make_slug
from voronoi.gateway.codename import codename_for_id

logger = logging.getLogger("voronoi.router")

# Re-export for tests
__all__ = [
    "CommandRouter",
    "handle_status", "handle_whatsup", "handle_howsitgoing",
    "handle_tasks", "handle_ready", "handle_health", "handle_board",
    "handle_reprioritize", "handle_pause", "handle_resume", "handle_add",
    "handle_resume_investigation",
    "handle_complete",
    "handle_abort", "handle_pivot", "handle_guide",
    "handle_discover", "handle_prove",
    "handle_recall", "handle_belief", "handle_journal", "handle_finding",
    "handle_results", "handle_demo", "handle_details",
]


# ---------------------------------------------------------------------------
# bd helper (thin wrapper that short-circuits when no .beads/ exists)
# ---------------------------------------------------------------------------

def _run_bd(*args: str, cwd: str | None = None) -> tuple[int, str]:
    if cwd and not has_beads_dir(cwd):
        return 1, ""
    return run_bd(*args, cwd=cwd)


# ---------------------------------------------------------------------------
# Conversation memory helpers (best-effort, created per call)
# ---------------------------------------------------------------------------

def _get_memory(project_dir: str):
    from voronoi.gateway.memory import ConversationMemory
    db = Path(project_dir) / ".swarm" / "conversations.db"
    return ConversationMemory(db)


def _get_knowledge(project_dir: str):
    from voronoi.gateway.knowledge import KnowledgeStore
    return KnowledgeStore(project_dir)


def _save_msg(project_dir: str, chat_id: str, role: str,
              text: str, metadata: dict | None = None):
    try:
        mem = _get_memory(project_dir)
        from voronoi.gateway.memory import Message
        mem.save_message(Message(
            chat_id=str(chat_id), role=role,
            content=text, metadata=metadata or {},
        ))
    except Exception:
        logger.debug("Failed to save message for chat %s", chat_id, exc_info=True)


# ---------------------------------------------------------------------------
# Queue helper
# ---------------------------------------------------------------------------

def _get_queue(project_dir: str) -> InvestigationQueue:
    # Always use ~/.voronoi/queue.db — the same database the dispatcher reads.
    # Using project_dir here would create a separate queue.db that the
    # dispatcher never sees, leading to orphaned or duplicate investigations.
    base = Path.home() / ".voronoi"
    return InvestigationQueue(base / "queue.db")


def _get_active_workspaces(project_dir: str) -> list[tuple[str, str]]:
    """Return (workspace_path, label) for all running investigations.

    Many commands (belief, journal, finding, guide, task mutations) need to
    operate on the *investigation workspace*, not the server's project_dir.
    Investigations are provisioned under ~/.voronoi/active/ and their paths
    are stored in the queue DB.
    """
    q = _get_queue(project_dir)
    results = []
    for inv in q.get_running():
        if inv.workspace_path:
            label = inv.codename or f"#{inv.id}"
            results.append((inv.workspace_path, label))
    return results


def _get_first_active_workspace(project_dir: str) -> Optional[str]:
    """Return the workspace path of the first running investigation, or None."""
    ws_list = _get_active_workspaces(project_dir)
    return ws_list[0][0] if ws_list else None


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
    # Fetch back to get the codename (may have been assigned in enqueue)
    stored = q.get(inv_id)
    codename = stored.codename if stored else codename_for_id(inv_id)
    queued = len(q.get_queued())
    running = len(q.get_running())
    logger.info("Enqueued investigation %s (#%d) mode=%s rigor=%s (queued=%d running=%d)",
                codename, inv_id, mode, rigor, queued, running)
    return inv_id, f"Queue: {queued} waiting · {running} running", codename


# ---------------------------------------------------------------------------
# Read-only handlers
# ---------------------------------------------------------------------------

def handle_status(project_dir: str) -> str:
    """Conversational status — buddy style."""
    return handle_whatsup(project_dir)


def handle_whatsup(project_dir: str) -> str:
    """Unified 'what's happening' response — replaces status+tasks+health."""
    q = _get_queue(project_dir)
    queued = len(q.get_queued())
    running_invs = q.get_running()

    inv_data: list[dict] = []
    for inv in running_invs:
        ws_path = inv.workspace_path
        if not ws_path:
            continue
        label = inv.codename or f"#{inv.id}"
        elapsed_sec = (time.time() - inv.started_at) if inv.started_at else 0
        question = inv.question or ""
        mode = inv.mode or "discover"

        # Get task counts
        total_tasks = 0
        closed_tasks = 0
        in_progress_tasks = 0
        ready_tasks = 0
        phase = ""
        try:
            code, output = _run_bd("list", "--json", cwd=ws_path)
            if code == 0 and output.strip():
                tasks = json.loads(output)
                if isinstance(tasks, list):
                    total_tasks = len(tasks)
                    closed_tasks = sum(1 for t in tasks if t.get("status") == "closed")
                    in_progress_tasks = sum(1 for t in tasks if t.get("status") == "in_progress")
            code2, ready_out = _run_bd("ready", "--json", cwd=ws_path)
            if code2 == 0 and ready_out.strip():
                ready_list = json.loads(ready_out)
                if isinstance(ready_list, list):
                    ready_tasks = len(ready_list)
        except Exception:
            pass

        # Detect phase from workspace files
        ws = Path(ws_path)
        if (ws / ".swarm" / "deliverable.md").exists():
            phase = "complete"
        elif (ws / ".swarm" / "convergence.json").exists():
            phase = "converging"
        elif (ws / ".swarm" / "belief-map.json").exists() and total_tasks > 5:
            phase = "investigating"
        elif (ws / ".swarm" / "scout-brief.md").exists():
            phase = "planning"
        elif total_tasks > 0:
            if in_progress_tasks > 0:
                phase = "investigating"
            else:
                phase = "planning"
        else:
            phase = "starting"

        inv_data.append({
            "label": label,
            "mode": mode,
            "elapsed_sec": elapsed_sec,
            "total_tasks": total_tasks,
            "closed_tasks": closed_tasks,
            "in_progress_tasks": in_progress_tasks,
            "ready_tasks": ready_tasks,
            "agents_healthy": in_progress_tasks,
            "agents_stuck": 0,
            "phase": phase,
            "question": question,
        })

    return build_digest_whatsup(
        running_investigations=inv_data,
        queued=queued,
    )


def handle_howsitgoing(project_dir: str) -> str:
    """Experiment-level progress — success criteria, belief map, experiments."""
    ws_list = _get_active_workspaces(project_dir)
    if not ws_list:
        return "Nothing running right now."

    all_lines: list[str] = []
    for ws_path, label in ws_list:
        ws = Path(ws_path)
        lines: list[str] = [f"*{label}*\n"]

        # Success criteria
        criteria = _criteria_summary(ws)
        if criteria:
            lines.append(criteria)
        else:
            lines.append("No success criteria defined yet.")

        # Experiments
        experiments = _experiment_summary(ws)
        if experiments:
            lines.append("\n" + experiments)

        # Belief map snippet
        for name in ("belief-map.md", "belief-map.json"):
            p = ws / ".swarm" / name
            if p.exists():
                content = p.read_text().strip()
                if name.endswith(".json"):
                    try:
                        data = json.loads(content)
                        if isinstance(data, dict):
                            hyps = data.get("hypotheses", [])
                            if isinstance(hyps, dict):
                                hyps = list(hyps.values())
                            if isinstance(hyps, list) and hyps:
                                lines.append("\nHypotheses:")
                                for h in hyps[:5]:
                                    if isinstance(h, dict):
                                        status = h.get('status', '?')
                                        lines.append(f"  {h.get('name', '?')}: P={h.get('prior', '?')} [{status}]")
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass
                else:
                    lines.append(f"\n{content[:300]}")
                break

        # Track assessment
        task_snapshot: dict = {}
        eval_score = 0.0
        total_tasks = 0
        closed_tasks = 0
        in_progress_tasks = 0
        try:
            code, output = _run_bd("list", "--json", cwd=ws_path)
            if code == 0 and output.strip():
                tasks = json.loads(output)
                if isinstance(tasks, list):
                    total_tasks = len(tasks)
                    for t in tasks:
                        tid = t.get("id", "")
                        st = t.get("status", "")
                        task_snapshot[tid] = {
                            "status": st,
                            "notes": t.get("notes", ""),
                        }
                        if st == "closed":
                            closed_tasks += 1
                        elif st == "in_progress":
                            in_progress_tasks += 1
        except Exception:
            pass

        # Progress bar with breakdown
        if total_tasks > 0:
            bar = progress_bar(closed_tasks, total_tasks)
            parts = [f"{closed_tasks} done"]
            if in_progress_tasks > 0:
                parts.append(f"{in_progress_tasks} active")
            remaining = total_tasks - closed_tasks - in_progress_tasks
            if remaining > 0:
                parts.append(f"{remaining} queued")
            lines.append(f"\n{bar}  ({' · '.join(parts)} of {total_tasks})")

        eval_path = ws / ".swarm" / "eval-score.json"
        if eval_path.exists():
            try:
                ed = json.loads(eval_path.read_text())
                eval_score = float(ed.get("score") or 0)
            except Exception:
                pass

        status, reason = assess_track_status(ws, task_snapshot, eval_score)
        if status == "on_track":
            lines.append(f"\nLooking good: {reason}")
        elif status == "watch":
            lines.append(f"\nHeads up: {reason}")
        else:
            lines.append(f"\n⚠️ {reason}")

        all_lines.append("\n".join(lines))

    return "\n\n".join(all_lines)


def handle_board(project_dir: str) -> str:
    """Kanban-style board snapshot for Telegram."""
    q = _get_queue(project_dir)
    running_invs = q.get_running()
    if not running_invs:
        return "\U0001f4ed No running investigations. Start one with `/voronoi discover <question>`."

    # Priority → icon (P0/P1 urgent, P2 normal, P3/P4 low)
    def _pri_icon(pri: int) -> str:
        if pri <= 1:
            return "\U0001f534"  # red circle
        if pri == 2:
            return "\U0001f7e1"  # yellow circle
        return "\u26aa"          # grey circle

    sections: list[str] = []
    for inv in running_invs:
        ws_path = inv.workspace_path
        if not ws_path:
            continue
        label = inv.codename or f"#{inv.id}"
        elapsed_sec = (time.time() - inv.started_at) if inv.started_at else 0
        elapsed = format_duration(elapsed_sec)
        preview = _clean_question_preview(inv.question or "", 80)

        code, output = _run_bd("list", "--json", cwd=ws_path)
        tasks: list[dict] = []
        if code == 0 and output.strip():
            try:
                tasks = json.loads(output)
            except json.JSONDecodeError:
                pass

        todo    = sorted([t for t in tasks if t.get("status") == "open"],     key=lambda x: x.get("priority", 2))
        blocked = sorted([t for t in tasks if t.get("status") == "blocked"],  key=lambda x: x.get("priority", 2))
        doing   = sorted([t for t in tasks if t.get("status") == "in_progress"], key=lambda x: x.get("priority", 2))
        done    =        [t for t in tasks if t.get("status") == "closed"]

        total = len(tasks)
        bar = progress_bar(len(done), total, width=16)
        sep = "\u2500" * 22

        lines: list[str] = []
        lines.append(f"\U0001f4cb *{label}* \u00b7 {elapsed}")
        if preview:
            lines.append(f"_{preview}_")
        lines.append(f"\n{bar}  {len(done)}/{total} tasks")

        # --- In Progress (most urgent, first) ---
        if doing:
            lines.append(f"\n{sep}")
            lines.append(f"\u25d0 *In Progress* ({len(doing)})")
            for t in doing:
                pri = t.get("priority", 2)
                title = t.get("title", "")[:50]
                lines.append(f"  {_pri_icon(pri)} {title}")

        # --- Blocked (if any) ---
        if blocked:
            lines.append(f"\n{sep}")
            lines.append(f"\U0001f6a7 *Blocked* ({len(blocked)})")
            for t in blocked:
                pri = t.get("priority", 2)
                title = t.get("title", "")[:50]
                lines.append(f"  {_pri_icon(pri)} {title}")

        # --- To Do (all items, no truncation) ---
        if todo:
            lines.append(f"\n{sep}")
            lines.append(f"\u25cb *To Do* ({len(todo)})")
            for t in todo:
                pri = t.get("priority", 2)
                title = t.get("title", "")[:50]
                lines.append(f"  {_pri_icon(pri)} {title}")

        # --- Done (compact, last) ---
        if done:
            lines.append(f"\n{sep}")
            if len(done) <= 4:
                lines.append(f"\u2713 *Done* ({len(done)})")
                for t in done[-4:]:
                    lines.append(f"  \u2713 {t.get('title', '')[:50]}")
            else:
                # Show just the count + last 2 completed
                lines.append(f"\u2713 *Done* ({len(done)}) \u2014 last completed:")
                for t in done[-2:]:
                    lines.append(f"  \u2713 {t.get('title', '')[:50]}")

        sections.append("\n".join(lines))

    return "\n".join(sections).strip() or "\U0001f4ed No tasks yet."


def handle_tasks(project_dir: str) -> str:
    q = _get_queue(project_dir)
    running_invs = q.get_running()
    all_lines = ["📋 *Open Tasks*\n"]
    found_any = False

    # Show tasks from active investigation workspaces
    for inv in running_invs:
        ws_path = inv.workspace_path
        if not ws_path:
            continue
        code, output = _run_bd("list", "--status", "open", "--json", cwd=ws_path)
        if code != 0:
            continue
        try:
            tasks = json.loads(output)
        except json.JSONDecodeError:
            continue
        if not tasks:
            continue
        found_any = True
        q_str = inv.question[:40] if inv.question else "?"
        label = inv.codename or f"#{inv.id}"
        all_lines.append(f"⚡ *{label}* _{q_str}_")
        for t in tasks[:10]:
            tid = t.get("id", "?")
            title = t.get("title", "?")[:60]
            priority = t.get("priority", "?")
            status = t.get("status", "?")
            all_lines.append(f"  • `{tid}` P{priority} [{status}] {title}")
        if len(tasks) > 10:
            all_lines.append(f"  … and {len(tasks) - 10} more")
        all_lines.append("")

    # No running investigations with tasks
    if not found_any:
        return "📭 No running investigations with open tasks"

    return "\n".join(all_lines)


def handle_health(project_dir: str) -> str:
    """Run the health-check script and format results for Telegram."""
    import subprocess
    script = Path(project_dir) / "scripts" / "health-check.sh"
    if not script.exists():
        # Try the package data directory
        script = Path(__file__).resolve().parent.parent / "data" / "scripts" / "health-check.sh"
    if not script.exists():
        return "❌ `health-check.sh` not found"
    try:
        result = subprocess.run(
            ["bash", str(script), "--json", "--no-notify"],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "⏱ Health check timed out"
    except FileNotFoundError:
        return "❌ bash not found"

    if result.returncode == 2:
        return "❌ No Voronoi sessions found. Is the pipeline running?"

    try:
        entries = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return f"❌ Health check failed:\n```\n{result.stderr[:300]}\n```"

    if not entries:
        return "✅ No sessions to check"

    # Build Telegram-friendly summary
    counts = {"healthy": 0, "stale": 0, "stuck": 0, "exited": 0}
    for e in entries:
        s = e.get("status", "healthy")
        counts[s] = counts.get(s, 0) + 1

    icon_map = {"healthy": "✅", "stale": "⚠️", "stuck": "🔴", "exited": "⚫"}

    # Summary line — only show non-zero counts
    summary_parts = []
    for key, icon in icon_map.items():
        if counts[key] > 0:
            summary_parts.append(f"{icon}{counts[key]}")
    lines = [
        "🩺 *Health Check*\n",
        f"{len(entries)} windows: {' '.join(summary_parts)}\n",
    ]

    # Partition entries by session
    sessions: dict[str, list[dict]] = {}
    for e in entries:
        sessions.setdefault(e.get("session", ""), []).append(e)

    for sess, sess_entries in sessions.items():
        lines.append(f"\n*{sess}*")

        # Separate active (healthy/stale/stuck) from exited
        active = [e for e in sess_entries if e.get("status") != "exited"]
        exited = [e for e in sess_entries if e.get("status") == "exited"]

        # Show active agents with detail
        for e in active:
            icon = icon_map.get(e["status"], "?")
            idle = e.get("pane_idle_secs", 0)
            idle_fmt = f"{idle // 60}m" if idle >= 60 else f"{idle}s"
            last = _truncate_word(e.get("last_output", ""), 80)
            line = f"  {icon} `{e['window']}` active {idle_fmt}"
            lines.append(line)
            if last:
                lines.append(f"    ↳ _{last}_")
            detail = e.get("detail", "")
            if detail and e["status"] != "healthy":
                lines.append(f"    ⚠ _{detail[:60]}_")

        # Collapse exited agents into one compact line
        if exited:
            names = [e["window"] for e in exited]
            if len(names) <= 3:
                names_str = ", ".join(f"`{n}`" for n in names)
            else:
                names_str = (
                    ", ".join(f"`{n}`" for n in names[:2])
                    + f" +{len(names) - 2} more"
                )
            lines.append(f"  ⚫ {len(exited)} exited: {names_str}")

    # Footer
    if counts["stuck"] > 0:
        lines.append(
            f"\n🔴 *{counts['stuck']} stuck* — "
            "no output or commits; may need restart"
        )
    elif counts["exited"] > 0 and counts["healthy"] > 0:
        lines.append(
            f"\n⚫ {counts['exited']} finished, "
            f"{counts['healthy']} still working"
        )
    elif counts["exited"] > 0:
        lines.append(f"\n⚫ All {counts['exited']} agents have exited")
    else:
        lines.append("\n✅ All agents running")

    return "\n".join(lines)


def _truncate_word(text: str, max_len: int) -> str:
    """Truncate *text* at a word boundary, appending '…' if shortened."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    # Cut at last space before max_len
    cut = text[:max_len].rfind(" ")
    if cut <= 0:
        cut = max_len
    return text[:cut] + "…"


def handle_ready(project_dir: str) -> str:
    q = _get_queue(project_dir)
    running_invs = q.get_running()
    all_lines = ["⚡ *Ready Tasks*\n"]
    found_any = False

    for inv in running_invs:
        ws_path = inv.workspace_path
        if not ws_path:
            continue
        code, output = _run_bd("ready", "--json", cwd=ws_path)
        if code != 0:
            continue
        try:
            tasks = json.loads(output)
        except json.JSONDecodeError:
            continue
        if not tasks:
            continue
        found_any = True
        label = inv.codename or f"#{inv.id}"
        all_lines.append(f"⚡ *{label}*")
        for t in tasks[:15]:
            tid = t.get("id", "?")
            title = t.get("title", "?")[:60]
            priority = t.get("priority", "?")
            all_lines.append(f"  • `{tid}` P{priority} {title}")
        all_lines.append("")

    if not found_any:
        return "⏳ No unblocked tasks ready"
    return "\n".join(all_lines)


# ---------------------------------------------------------------------------
# Mutation handlers
# ---------------------------------------------------------------------------

def handle_reprioritize(project_dir: str, task_id: str, priority: str) -> str:
    # Try running investigation workspaces first
    for ws_path, _ in _get_active_workspaces(project_dir):
        code, output = _run_bd("update", task_id, "--priority", priority, cwd=ws_path)
        if code == 0:
            return f"✅ Task `{task_id}` priority set to {priority}"
    code, output = _run_bd("update", task_id, "--priority", priority, cwd=project_dir)
    if code != 0:
        return f"❌ Failed: {output}"
    return f"✅ Task `{task_id}` priority set to {priority}"


def handle_pause(project_dir: str, task_id: str) -> str:
    # Try running investigation workspaces first
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
    """Resume a paused or failed investigation by ID or codename.

    The dispatcher's resume_investigation() is called via a lazy import
    to avoid circular dependencies.  If no dispatcher instance is
    running (CLI context), we fall back to updating the queue directly.
    """
    from voronoi.server.queue import InvestigationQueue

    db_path = Path.home() / ".voronoi" / "queue.db"
    if not db_path.exists():
        return "❌ No investigation queue found."

    queue = InvestigationQueue(db_path)

    # Resolve identifier → investigation ID
    inv = None
    # Try numeric ID first
    try:
        inv_id = int(identifier)
        inv = queue.get(inv_id)
    except (ValueError, TypeError):
        pass

    # Try codename match
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

    # Try to use an active dispatcher if one exists (server context)
    try:
        from voronoi.server.dispatcher import _active_dispatcher
        dispatcher = _active_dispatcher()
        if dispatcher is not None:
            return dispatcher.resume_investigation(inv.id)
    except (ImportError, Exception):
        pass

    # Fallback: update queue directly (no agent launch — just mark resumable)
    if not queue.resume(inv.id):
        return f"❌ Failed to resume #{inv.id}."
    label = inv.codename or f"#{inv.id}"
    return f"▶️ *{label}* marked as running — it will be picked up on next dispatch cycle."


def handle_add(project_dir: str, title: str) -> str:
    # Create task in the first running investigation workspace
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


def handle_abort(project_dir: str) -> str:
    # Cancel all queued investigations
    q = _get_queue(project_dir)
    cancelled = 0
    for inv in q.get_queued():
        if q.cancel(inv.id):
            cancelled += 1

    # Write abort signal to ALL running investigation workspaces AND the
    # global base dir so the dispatcher picks it up regardless of which
    # path it checks.
    for ws_path, _ in _get_active_workspaces(project_dir):
        signal_dir = Path(ws_path) / ".swarm"
        signal_dir.mkdir(parents=True, exist_ok=True)
        (signal_dir / "abort-signal").write_text("abort\n")
    # Also write to global fallback location
    global_signal = Path.home() / ".voronoi" / ".swarm"
    global_signal.mkdir(parents=True, exist_ok=True)
    (global_signal / "abort-signal").write_text("abort\n")

    parts = ["🛑 *Abort requested*"]
    if cancelled:
        parts.append(f"Cancelled {cancelled} queued investigation(s).")
    parts.append("Running investigations will be stopped on next progress check (~30s).")
    return "\n".join(parts)


def handle_pivot(project_dir: str, message: str) -> str:
    # Write guidance to ALL running investigation workspaces so agents see it
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
        # Fallback to project_dir if no running investigations
        guidance_dir = Path(project_dir) / ".swarm"
        guidance_dir.mkdir(parents=True, exist_ok=True)
        with open(guidance_dir / "operator-guidance.md", "a") as f:
            f.write(f"\n## Pivot — {ts}\n\n{message}\n")
    dest = ", ".join(written_to) if written_to else "project"
    return f"🔀 *Pivot recorded* ({dest})\n\n_{message}_\nAgents will read this on next dispatch."


def handle_guide(project_dir: str, message: str) -> str:
    # Write guidance to ALL running investigation workspaces so agents see it
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


# ---------------------------------------------------------------------------
# Science workflow handlers — enqueue directly to the investigation queue
# ---------------------------------------------------------------------------

def _workflow_response(mode: str, rigor: str, question: str,
                       inv_id: int, queue_status: str,
                       codename: str = "") -> str:
    emoji = MODE_EMOJI.get(mode, "🔷")
    rigor_desc = RIGOR_DESCRIPTIONS.get(rigor, rigor)
    verb = MODE_VERB.get(mode, mode)
    label = codename or f"#{inv_id}"
    return (
        f"⚡ *Voronoi · {label}* {emoji} LAUNCHED\n\n"
        f"_{question}_\n\n"
        f"  Mode     *{rigor}* {verb}\n"
        f"  Rigor    {rigor_desc}\n"
        f"  Queue    {queue_status}\n\n"
        f"Setting up workspace — I'll ping you when agents are live."
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
# Knowledge handlers
# ---------------------------------------------------------------------------

def handle_recall(project_dir: str, query: str) -> str:
    ks = _get_knowledge(project_dir)
    return ks.format_recall_response(query)


def handle_belief(project_dir: str) -> str:
    # Search running investigation workspaces, then fall back to project_dir
    search_dirs = [ws for ws, _ in _get_active_workspaces(project_dir)]
    search_dirs.append(project_dir)
    for base in search_dirs:
        swarm = Path(base) / ".swarm"
        for name in ("belief-map.md", "belief-map.json"):
            p = swarm / name
            if p.exists():
                content = p.read_text().strip()
                if name.endswith(".json"):
                    try:
                        data = json.loads(content)
                        lines = []
                        for h in data.get("hypotheses", []):
                            lines.append(f"- {h.get('name', '?')}: P={h.get('prior', '?')} [{h.get('status', '?')}]")
                        content = "\n".join(lines) if lines else content
                    except (json.JSONDecodeError, ValueError):
                        pass
                return f"📊 *Belief Map*\n\n{content}"
    return "📊 No belief map found. Start an investigation to generate one."


def handle_journal(project_dir: str, max_lines: int = 30) -> str:
    # Search running investigation workspaces, then fall back to project_dir
    search_dirs = [ws for ws, _ in _get_active_workspaces(project_dir)]
    search_dirs.append(project_dir)
    for base in search_dirs:
        journal_path = Path(base) / ".swarm" / "journal.md"
        if journal_path.exists():
            lines = journal_path.read_text().strip().split("\n")
            content = "\n".join(lines[-max_lines:])
            return f"📓 *Journal* (last {max_lines} lines)\n\n{content}"
    return "📓 No journal found. Start a workflow to begin recording."


def handle_finding(project_dir: str, finding_id: str) -> str:
    # Try running investigation workspaces first (tasks live there)
    search_dirs = [ws for ws, _ in _get_active_workspaces(project_dir)]
    search_dirs.append(project_dir)
    for base in search_dirs:
        code, output = _run_bd("show", finding_id, "--json", cwd=base)
        if code == 0 and output.strip():
            try:
                task = json.loads(output)
            except json.JSONDecodeError:
                continue
            title = task.get("title", "?")
            status = task.get("status", "?")
            notes = task.get("notes", "")
            priority = task.get("priority", "?")
            lines = [
                f"🔍 *{finding_id}*: {title}",
                f"Status: {status} | Priority: {priority}",
            ]
            if notes:
                lines.append(f"\nNotes:\n```\n{notes[:500]}\n```")
            return "\n".join(lines)
    return f"❌ Finding `{finding_id}` not found"


def handle_demo(project_dir: str, demo_name: str, chat_id: str = "") -> str:
    """Set up and enqueue a demo as an investigation.

    Mirrors the CLI ``voronoi demo run`` path:
    1. Locate the demo directory and its PROMPT.md
    2. Enqueue a build investigation whose question is the full PROMPT.md content
    3. Tag the investigation so the dispatcher copies demo files into the workspace
    """
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

    # Prevent duplicate: check if this demo is already queued or running
    slug = make_slug(demo_name)
    for inv in q.get_queued() + q.get_running():
        if inv.slug == slug:
            label = inv.codename or f"#{inv.id}"
            return (
                f"⚠️ Demo `{demo_name}` is already {inv.status} "
                f"as *{label}*.\n\n"
                f"Use `/voronoi status` to check progress."
            )

    # Detect rigor from PROMPT.md content — demos with experimental
    # designs, statistical tests, or multi-phase protocols need higher
    # rigor to prevent premature completion.
    from voronoi.gateway.intent import _determine_rigor, WorkflowMode, RigorLevel
    _RIGOR_ORDER = [RigorLevel.ADAPTIVE,
                    RigorLevel.SCIENTIFIC, RigorLevel.EXPERIMENTAL]
    detected_rigor = _determine_rigor(prompt_content, WorkflowMode.PROVE)
    # Floor at scientific — demos with detailed prompts are PROVE mode
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

    # Tag the investigation so the dispatcher knows to copy demo files
    q.set_demo_source(inv_id, demo_name, str(demo["path"]))

    queued = len(q.get_queued())
    running = len(q.get_running())
    logger.info("Enqueued demo %s as investigation %s (#%d)", demo_name, codename, inv_id)

    return (
        f"⚡ *Voronoi · {codename}* 🎮 DEMO LAUNCHED\n\n"
        f"Demo: *{demo_name}*\n"
        f"Queue: {queued} waiting · {running} running\n\n"
        f"Setting up workspace — I'll ping you when agents are live."
    )


def handle_details(project_dir: str) -> str:
    """Return a detailed (non-compact) progress view for the active investigation."""
    q = _get_queue(project_dir)
    running = q.get_running()
    if not running:
        return "No investigation is running right now."
    inv = running[0]
    ws = Path(inv.workspace_path) if inv.workspace_path else None
    if ws is None or not ws.exists():
        return f"Investigation {inv.codename or f'#{inv.id}'} has no accessible workspace."

    # Read task snapshot from bd
    task_snapshot: dict = {}
    if has_beads_dir(str(ws)):
        code, data = _run_bd("list", "--json", cwd=str(ws))
        if code == 0 and data:
            try:
                tasks = json.loads(data)
                if isinstance(tasks, list):
                    for t in tasks:
                        tid = t.get("id", "")
                        task_snapshot[tid] = {
                            "status": t.get("status", ""),
                            "title": t.get("title", ""),
                            "notes": t.get("notes", ""),
                        }
            except (json.JSONDecodeError, TypeError):
                pass

    elapsed_sec = (time.time() - (inv.started_at or time.time()))
    text, _ = build_digest(
        codename=inv.codename or f"#{inv.id}",
        mode=inv.mode or "discover",
        phase="investigating",
        elapsed_sec=elapsed_sec,
        task_snapshot=task_snapshot,
        workspace=ws,
        events_since_last=[],
        compact=False,
    )
    return text


def handle_results(project_dir: str, inv_id_str: str = "") -> str:
    """Look up a past investigation and return its teaser."""
    q = _get_queue(project_dir)
    if inv_id_str:
        try:
            inv = q.get(int(inv_id_str))
        except (ValueError, TypeError):
            return f"❌ Invalid investigation ID: {inv_id_str}"
        if inv is None:
            return f"❌ Investigation #{inv_id_str} not found"
        if inv.status not in ("complete", "failed"):
            return f"⏳ Investigation #{inv_id_str} is still {inv.status}"
        if not inv.workspace_path:
            return f"❌ No workspace for investigation #{inv_id_str}"
        from voronoi.gateway.report import ReportGenerator
        rg = ReportGenerator(
            Path(inv.workspace_path),
            mode=getattr(inv, "mode", None),
            rigor=getattr(inv, "rigor", None),
        )
        return rg.build_teaser(inv.id, inv.question, 0, 0, 0)
    # List recent investigations
    recent = q.get_recent(5)
    if not recent:
        return "📭 No investigations found"
    lines = ["📋 *Recent Investigations*\n"]
    for inv in recent:
        emoji = {"complete": "✅", "failed": "❌", "running": "⚡"}.get(inv.status, "⏳")
        lines.append(
            f"• {emoji} #{inv.id} [{inv.status}] _{inv.question[:50]}_"
        )
    lines.append("\nUse `/voronoi results <id>` to see details")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Free-text classification
# ---------------------------------------------------------------------------

_INTRO_MESSAGE = (
    "*Voronoi* — ask a question, get evidence.\n\n"
    "Drop me a question — anything from _\"why is our model degrading?\"_ "
    "to _\"does EWC beat replay for catastrophic forgetting?\"_ — and I'll "
    "dispatch a swarm of AI agents to discover the answer.\n\n"
    "Or send `/voronoi` for commands."
)

def _LOW_CONFIDENCE_MESSAGE(text: str, intent) -> str:
    """Return a helpful clarification prompt when intent confidence is low."""
    mode_label = intent.mode.value if intent.mode else "unknown"
    confidence_pct = int(intent.confidence * 100)
    return (
        f"I'm not quite sure what you'd like ({confidence_pct}% → _{mode_label}_).\n\n"
        f"Your message: _{text[:120]}_\n\n"
        "Try something like:\n"
        "  _Why is our model accuracy dropping?_ → discover\n"
        "  _Prove that EWC beats replay_ → prove\n\n"
        "Or use a command directly:\n"
        "`/voronoi discover <question>`\n"
        "`/voronoi prove <hypothesis>`"
    )


_HELP_MESSAGE = (
    "*Voronoi* — your AI research lab\n\n"
    "Just ask me anything:\n"
    "  → _Why is our model accuracy dropping?_\n"
    "  → _Prove that EWC beats replay for catastrophic forgetting_\n"
    "  → _Compare Redis vs Memcached_\n\n"
    "I'll figure out what to do — classify intent, pick the right "
    "rigor level, spawn parallel agents, and deliver findings.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "*Quick check-ins*\n"
    "`/voronoi status` — what's happening right now\n"
    "`/voronoi board` — Kanban snapshot (To Do / In Progress / Done)\n"
    "`/voronoi progress` — are we on track? metrics + criteria\n\n"
    "*Workflows*\n"
    "`/voronoi discover <question>`\n"
    "`/voronoi prove <hypothesis>`\n\n"
    "*Knowledge*\n"
    "`/voronoi belief` · `journal` · `finding <id>` · `recall <query>`\n\n"
    "*Control*\n"
    "`/voronoi guide <msg>` · `pivot <msg>` · `abort`\n\n"
    "_In groups, @mention me or reply to my messages._"
)


def _is_greeting(text: str) -> bool:
    t = text.lower().strip().rstrip("?!.")
    greetings = {"hi", "hello", "hey", "yo", "sup", "hi there", "hello there", "hey there"}
    if t in greetings:
        return True
    intro = [
        "what can you do", "what do you do", "who are you",
        "how do you work", "how does this work", "what is voronoi",
        "what is this", "help", "help me", "what are you",
        "introduce yourself", "capabilities",
    ]
    return any(p in t for p in intro)


# ---------------------------------------------------------------------------
# CommandRouter — high-level entry point
# ---------------------------------------------------------------------------

class CommandRouter:
    """Routes commands and free-text to the appropriate handler.

    Returns (text, document_path | None) tuples so the I/O layer
    can send both messages and file attachments.
    """

    def __init__(self, project_dir: str):
        self.project_dir = project_dir

    def _list_demos(self) -> str:
        """List available demos."""
        try:
            from voronoi.cli import find_data_dir, list_demos
            data = find_data_dir()
            demos = list_demos(data)
        except Exception:
            return "\u274c Could not list demos."
        if not demos:
            return "No demos available."
        lines = ["\ud83c\udfae *Available Demos*\n"]
        for d in demos:
            marker = "\u2713" if d["has_prompt"] else "\u25cb"
            lines.append(f"  {marker} `{d['name']}` \u2014 {d['description']}")
        lines.append("\nRun with: `/voronoi demo run <name>`")
        return "\n".join(lines)

    def route(self, command: str, args: list[str],
              chat_id: str) -> tuple[str, Optional[Path]]:
        """Dispatch a /voronoi <command> and return (text, document)."""
        if not command:
            return _HELP_MESSAGE, None

        sub = command.lower()
        logger.info("Routing command=%s args=%s chat=%s", sub, args, chat_id)

        try:
            if sub in ("help", "hi", "hello", "hey"):
                return _HELP_MESSAGE, None
            elif sub in ("status", "whatsup"):
                return handle_whatsup(self.project_dir), None
            elif sub in ("progress", "howsitgoing"):
                return handle_howsitgoing(self.project_dir), None
            elif sub == "board":
                return handle_board(self.project_dir), None
            elif sub == "tasks":
                return handle_tasks(self.project_dir), None
            elif sub == "ready":
                return handle_ready(self.project_dir), None
            elif sub == "health":
                return handle_health(self.project_dir), None
            elif sub == "discover" and args:
                txt = handle_discover(self.project_dir, " ".join(args), chat_id)
                return txt, None
            elif sub == "prove" and args:
                txt = handle_prove(self.project_dir, " ".join(args), chat_id)
                return txt, None
            elif sub == "demo" and args:
                demo_action = args[0].lower()
                if demo_action == "run" and len(args) >= 2:
                    txt = handle_demo(self.project_dir, args[1], chat_id)
                elif demo_action == "list":
                    txt = self._list_demos()
                else:
                    txt = "Usage: `/voronoi demo list` or `/voronoi demo run <name>`"
                return txt, None
            elif sub == "recall" and args:
                return handle_recall(self.project_dir, " ".join(args)), None
            elif sub == "belief":
                return handle_belief(self.project_dir), None
            elif sub == "journal":
                return handle_journal(self.project_dir), None
            elif sub == "finding" and args:
                return handle_finding(self.project_dir, args[0]), None
            elif sub == "results":
                inv_id = args[0] if args else ""
                return handle_results(self.project_dir, inv_id), None
            elif sub == "details":
                return handle_details(self.project_dir), None
            elif sub == "reprioritize" and len(args) >= 2:
                return handle_reprioritize(self.project_dir, args[0], args[1]), None
            elif sub == "pause" and args:
                return handle_pause(self.project_dir, args[0]), None
            elif sub == "resume" and args:
                # Detect investigation ID/codename vs task ID.
                # Beads task IDs look like "bd-123"; investigation IDs are
                # plain integers or codenames (single words, no hyphens
                # starting with "bd-").
                arg = args[0]
                is_beads_task = arg.startswith("bd-")
                if is_beads_task:
                    return handle_resume(self.project_dir, arg), None
                return handle_resume_investigation(self.project_dir, arg), None
            elif sub == "add" and args:
                return handle_add(self.project_dir, " ".join(args)), None
            elif sub == "complete" and args:
                reason = " ".join(args[1:]) if len(args) > 1 else "Completed"
                return handle_complete(self.project_dir, args[0], reason), None
            elif sub == "abort":
                return handle_abort(self.project_dir), None
            elif sub == "pivot" and args:
                return handle_pivot(self.project_dir, " ".join(args)), None
            elif sub == "guide" and args:
                return handle_guide(self.project_dir, " ".join(args)), None
            else:
                return f"❓ Unknown command: `{sub}`\nSend `/voronoi` for help.", None
        except Exception as e:
            logger.error("Command %s failed: %s", sub, e, exc_info=True)
            return f"❌ Error: {e}", None

    def handle_free_text(self, text: str, chat_id: str,
                         is_private: bool) -> tuple[str, Optional[Path]]:
        """Classify and handle free-text input.

        Returns (reply_text, document_path | None).
        """
        if _is_greeting(text):
            return _INTRO_MESSAGE, None

        intent = classify(text)
        logger.info("Classified intent: mode=%s rigor=%s confidence=%.2f",
                    intent.mode.value, intent.rigor.value, intent.confidence)

        # Meta intents
        if intent.is_meta:
            if intent.mode == WorkflowMode.RECALL:
                return handle_recall(self.project_dir, intent.summary), None
            if intent.mode == WorkflowMode.STATUS:
                return handle_status(self.project_dir), None
            # Save as guidance and acknowledge
            _save_msg(self.project_dir, chat_id, "user", text,
                      {"intent": "guide", "confidence": intent.confidence})
            return handle_guide(self.project_dir, text), None

        # Low confidence → ask the user to clarify instead of silently
        # writing guidance
        if intent.confidence < 0.5:
            _save_msg(self.project_dir, chat_id, "user", text,
                      {"intent": intent.mode.value, "confidence": intent.confidence})
            return _LOW_CONFIDENCE_MESSAGE(text, intent), None

        if not intent.is_science:
            _save_msg(self.project_dir, chat_id, "user", text,
                      {"intent": intent.mode.value, "confidence": intent.confidence})
            return _LOW_CONFIDENCE_MESSAGE(text, intent), None

        # Save to memory
        _save_msg(self.project_dir, chat_id, "user", text, {
            "intent": intent.mode.value,
            "rigor": intent.rigor.value,
            "confidence": intent.confidence,
        })

        # Dispatch workflow with full question text (not truncated summary)
        if intent.mode == WorkflowMode.PROVE:
            txt = handle_prove(self.project_dir, text, chat_id)
        elif intent.mode == WorkflowMode.DISCOVER:
            txt = handle_discover(self.project_dir, text, chat_id)
        else:
            txt = handle_guide(self.project_dir, text)

        # Prepend classification feedback so the user knows what Voronoi understood
        confidence_pct = int(intent.confidence * 100)
        mode_emoji = MODE_EMOJI.get(intent.mode.value, "🔷")
        feedback = (
            f"🧠 _Classified as *{intent.mode.value}* {mode_emoji} "
            f"(rigor: {intent.rigor.value} · {confidence_pct}% confidence)_\n\n"
        )
        return feedback + txt, None
