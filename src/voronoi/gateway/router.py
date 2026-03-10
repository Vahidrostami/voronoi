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
from voronoi.gateway.progress import MODE_EMOJI, RIGOR_DESCRIPTIONS, MODE_VERB
from voronoi.server.queue import Investigation, InvestigationQueue
from voronoi.server.runner import make_slug
from voronoi.gateway.codename import codename_for_id

logger = logging.getLogger("voronoi.router")

# Re-export for tests
__all__ = [
    "CommandRouter",
    "handle_status", "handle_tasks", "handle_ready", "handle_health",
    "handle_reprioritize", "handle_pause", "handle_resume", "handle_add",
    "handle_abort", "handle_pivot", "handle_guide",
    "handle_investigate", "handle_explore", "handle_build", "handle_experiment",
    "handle_recall", "handle_belief", "handle_journal", "handle_finding",
    "handle_results", "handle_demo",
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
    try:
        from voronoi.gateway.memory import ConversationMemory
        db = Path(project_dir) / ".swarm" / "conversations.db"
        return ConversationMemory(db)
    except ImportError:
        return None


def _get_knowledge(project_dir: str):
    try:
        from voronoi.gateway.knowledge import KnowledgeStore
        return KnowledgeStore(project_dir)
    except ImportError:
        return None


def _save_msg(project_dir: str, chat_id: str, role: str,
              text: str, metadata: dict | None = None):
    mem = _get_memory(project_dir)
    if mem is None:
        return
    try:
        from voronoi.gateway.memory import Message
        mem.save_message(Message(
            chat_id=str(chat_id), role=role,
            content=text, metadata=metadata or {},
        ))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Queue helper
# ---------------------------------------------------------------------------

def _get_queue(project_dir: str) -> InvestigationQueue:
    # Always use ~/.voronoi/queue.db — the same database the dispatcher reads.
    # Using project_dir here would create a separate queue.db that the
    # dispatcher never sees, leading to orphaned or duplicate investigations.
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
    q = _get_queue(project_dir)
    queued = len(q.get_queued())
    running_invs = q.get_running()
    running_count = len(running_invs)
    recent = q.get_recent(5)
    completed = sum(1 for inv in recent if inv.status == "complete")

    lines = ["📊 *Swarm Status*\n"]
    lines.append(f"Queued: {queued} · Running: {running_count} · Recent completed: {completed}")

    # Show tasks from active investigation workspaces
    if running_invs:
        for inv in running_invs:
            ws_path = inv.workspace_path
            if ws_path:
                _, ready = _run_bd("ready", "--json", cwd=ws_path)
                _, open_tasks = _run_bd("list", "--status", "open", "--json", cwd=ws_path)
                try:
                    ready_count = len(json.loads(ready))
                except Exception:
                    ready_count = "?"
                try:
                    open_count = len(json.loads(open_tasks))
                except Exception:
                    open_count = "?"
                q_str = inv.question[:50] if inv.question else "?"
                label = inv.codename or f"#{inv.id}"
                lines.append(f"\n⚡ *{label}* _{q_str}_")
                lines.append(f"   Tasks: {open_count} open · {ready_count} ready")
    else:
        # No running investigations — task counts aren't meaningful
        # since tasks live in investigation workspaces, not the server dir.
        pass

    return "\n".join(lines)


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
        # Try the repo checkout layout (project_dir may be a workspace)
        script = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "health-check.sh"
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
    lines = [
        "🩺 *Health Check*\n",
        f"Windows: {len(entries)}  "
        f"✅{counts['healthy']} ⚠️{counts['stale']} 🔴{counts['stuck']} ⚫{counts['exited']}\n",
    ]

    current_session = None
    for e in entries:
        sess = e.get("session", "")
        if sess != current_session:
            current_session = sess
            lines.append(f"\n*{sess}*")
        icon = icon_map.get(e["status"], "?")
        role = e.get("role", "")
        idle = e.get("pane_idle_secs", 0)
        idle_fmt = f"{idle // 60}m" if idle >= 60 else f"{idle}s"
        proc = "🟢" if e.get("has_process") else "⚫"
        detail = e.get("detail", "")
        line = f"  {icon} `{e['window']}` {role} idle:{idle_fmt} {proc}"
        if detail:
            line += f"  _{detail[:60]}_"
        lines.append(line)

    if counts["stuck"] > 0:
        lines.append("\n🔴 *Action needed* — stuck agents detected")
    elif counts["exited"] > 0:
        lines.append("\n⚫ Some agent processes have exited")
    else:
        lines.append("\n✅ All processes running normally")

    return "\n".join(lines)


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
    code, output = _run_bd("update", task_id, "--priority", priority, cwd=project_dir)
    if code != 0:
        return f"❌ Failed: {output}"
    return f"✅ Task `{task_id}` priority set to {priority}"


def handle_pause(project_dir: str, task_id: str) -> str:
    _run_bd("update", task_id, "--notes",
            "BLOCKED: Paused by operator via Telegram", cwd=project_dir)
    return f"⏸ Task `{task_id}` paused"


def handle_resume(project_dir: str, task_id: str) -> str:
    _run_bd("update", task_id, "--status", "open", cwd=project_dir)
    return f"▶️ Task `{task_id}` resumed"


def handle_add(project_dir: str, title: str) -> str:
    code, output = _run_bd(
        "create", title, "-t", "task", "-p", "1", "--json",
        cwd=project_dir,
    )
    if code != 0:
        return f"❌ Failed to create task: {output}"
    try:
        new_id = json.loads(output).get("id", "?")
    except Exception:
        new_id = "?"
    return f"✅ Created task `{new_id}`: {title}"


def handle_abort(project_dir: str) -> str:
    # Cancel all queued investigations
    q = _get_queue(project_dir)
    cancelled = 0
    for inv in q.get_queued():
        if q.cancel(inv.id):
            cancelled += 1

    # Write abort signal file for the dispatcher to pick up.
    # The dispatcher's poll_progress reads this and kills running tmux sessions.
    signal_dir = Path(project_dir) / ".swarm"
    signal_dir.mkdir(parents=True, exist_ok=True)
    (signal_dir / "abort-signal").write_text("abort\n")

    parts = ["🛑 *Abort requested*"]
    if cancelled:
        parts.append(f"Cancelled {cancelled} queued investigation(s).")
    parts.append("Running investigations will be stopped on next progress check (~30s).")
    return "\n".join(parts)


def handle_pivot(project_dir: str, message: str) -> str:
    guidance_dir = Path(project_dir) / ".swarm"
    guidance_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    with open(guidance_dir / "operator-guidance.md", "a") as f:
        f.write(f"\n## Pivot — {ts}\n\n{message}\n")
    return f"🔀 *Pivot recorded*\n\nGuidance written to `.swarm/operator-guidance.md`\nAgents will read this on next dispatch."


def handle_guide(project_dir: str, message: str) -> str:
    guidance_dir = Path(project_dir) / ".swarm"
    guidance_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    with open(guidance_dir / "operator-guidance.md", "a") as f:
        f.write(f"\n## Guidance — {ts}\n\n{message}\n")
    return f"📝 *Guidance noted*\n\n_{message}_"


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


def handle_investigate(project_dir: str, question: str, chat_id: str = "") -> str:
    inv_id, qs, cn = _enqueue(project_dir, question, "investigate", "scientific", chat_id)
    return _workflow_response("investigate", "scientific", question, inv_id, qs, cn)


def handle_explore(project_dir: str, question: str, chat_id: str = "") -> str:
    inv_id, qs, cn = _enqueue(project_dir, question, "explore", "analytical", chat_id)
    return _workflow_response("explore", "analytical", question, inv_id, qs, cn)


def handle_build(project_dir: str, description: str, chat_id: str = "") -> str:
    inv_id, qs, cn = _enqueue(project_dir, description, "build", "standard", chat_id)
    return _workflow_response("build", "standard", description, inv_id, qs, cn)


def handle_experiment(project_dir: str, hypothesis: str, chat_id: str = "") -> str:
    inv_id, qs, cn = _enqueue(project_dir, hypothesis, "investigate", "experimental", chat_id)
    return _workflow_response("investigate", "experimental", hypothesis, inv_id, qs, cn)


# ---------------------------------------------------------------------------
# Knowledge handlers
# ---------------------------------------------------------------------------

def handle_recall(project_dir: str, query: str) -> str:
    ks = _get_knowledge(project_dir)
    if ks is None:
        return "❌ Knowledge store not available"
    return ks.format_recall_response(query)


def handle_belief(project_dir: str) -> str:
    swarm = Path(project_dir) / ".swarm"
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
    journal_path = Path(project_dir) / ".swarm" / "journal.md"
    if not journal_path.exists():
        return "📓 No journal found. Start a workflow to begin recording."
    lines = journal_path.read_text().strip().split("\n")
    content = "\n".join(lines[-max_lines:])
    return f"📓 *Journal* (last {max_lines} lines)\n\n{content}"


def handle_finding(project_dir: str, finding_id: str) -> str:
    code, output = _run_bd("show", finding_id, "--json", cwd=project_dir)
    if code != 0:
        return f"❌ Finding `{finding_id}` not found: {output}"
    try:
        task = json.loads(output)
    except json.JSONDecodeError:
        return f"❌ Invalid data for `{finding_id}`"
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


def handle_demo(project_dir: str, demo_name: str, chat_id: str = "") -> str:
    """Set up and enqueue a demo as an investigation.

    Mirrors the CLI ``voronoi demo run`` path:
    1. Locate the demo directory and its PROMPT.md
    2. Enqueue a build investigation whose question is the full PROMPT.md content
    3. Tag the investigation so the dispatcher copies demo files into the workspace
    """
    from voronoi.cli import _find_data_dir, _list_demos

    data = _find_data_dir()
    demos = _list_demos(data)
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

    inv = Investigation(
        chat_id=chat_id,
        question=prompt_content,
        slug=make_slug(demo_name),
        mode="build",
        rigor="standard",
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
    "� *Voronoi — Ask a question. Get evidence.*\n\n"
    "Drop me a question — anything from _\"why is our model degrading?\"_ "
    "to _\"does EWC beat replay for catastrophic forgetting?\"_ — and I'll "
    "dispatch a swarm of AI agents to investigate, explore, or build it.\n\n"
    "Hypotheses · experiments · statistical validation · belief maps · "
    "findings with effect sizes and confidence intervals — "
    "on autopilot. 🧪\n\n"
    "_Send_ `/voronoi` _for commands, or just ask me something._"
)

def _LOW_CONFIDENCE_MESSAGE(text: str, intent) -> str:
    """Return a helpful clarification prompt when intent confidence is low."""
    mode_label = intent.mode.value if intent.mode else "unknown"
    confidence_pct = int(intent.confidence * 100)
    return (
        f"🤔 I'm not sure what you'd like me to do ({confidence_pct}% confident → _{mode_label}_).\n\n"
        f"Your message: _{text[:120]}_\n\n"
        "Try one of these:\n"
        "  🔬 _Why is our model accuracy dropping?_ → investigate\n"
        "  🧭 _Compare Redis vs Memcached_ → explore\n"
        "  🔨 _Build a REST API with auth_ → build\n\n"
        "Or use a command directly:\n"
        "`/voronoi investigate <question>`\n"
        "`/voronoi explore <question>`\n"
        "`/voronoi build <description>`\n\n"
        "_Send_ `/voronoi` _for all commands._"
    )


_HELP_MESSAGE = (
    "� *Voronoi* — your AI research lab\n\n"
    "I orchestrate AI agent swarms to investigate, explore, "
    "and build — all from this chat.\n\n"
    "*Just ask me anything:*\n"
    "  → _Why is our model accuracy dropping?_\n"
    "  → _Compare Redis vs Memcached for our workload_\n"
    "  → _Build a REST API with auth and billing_\n\n"
    "I'll figure out what to do — classify intent, pick the right "
    "rigor level, spawn parallel agents, and deliver findings with "
    "effect sizes and confidence intervals.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "*Or use commands:*\n\n"
    "🧪 *Workflows*\n"
    "`/voronoi investigate <question>`\n"
    "`/voronoi explore <question>`\n"
    "`/voronoi build <description>`\n"
    "`/voronoi experiment <hypothesis>`\n\n"
    "📚 *Knowledge*\n"
    "`/voronoi recall <query>` · `belief` · `journal` · `finding <id>`\n\n"
    "📋 *Tasks*\n"
    "`/voronoi status` · `tasks` · `ready` · `health` · `results [id]`\n\n"
    "🎛 *Control*\n"
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
            from voronoi.cli import _find_data_dir, _list_demos
            data = _find_data_dir()
            demos = _list_demos(data)
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
            elif sub == "status":
                return handle_status(self.project_dir), None
            elif sub == "tasks":
                return handle_tasks(self.project_dir), None
            elif sub == "ready":
                return handle_ready(self.project_dir), None
            elif sub == "health":
                return handle_health(self.project_dir), None
            elif sub == "investigate" and args:
                txt = handle_investigate(self.project_dir, " ".join(args), chat_id)
                return txt, None
            elif sub == "explore" and args:
                txt = handle_explore(self.project_dir, " ".join(args), chat_id)
                return txt, None
            elif sub == "build" and args:
                txt = handle_build(self.project_dir, " ".join(args), chat_id)
                return txt, None
            elif sub == "experiment" and args:
                txt = handle_experiment(self.project_dir, " ".join(args), chat_id)
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
            elif sub == "reprioritize" and len(args) >= 2:
                return handle_reprioritize(self.project_dir, args[0], args[1]), None
            elif sub == "pause" and args:
                return handle_pause(self.project_dir, args[0]), None
            elif sub == "resume" and args:
                return handle_resume(self.project_dir, args[0]), None
            elif sub == "add" and args:
                return handle_add(self.project_dir, " ".join(args)), None
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

        if not intent.is_science and intent.mode != WorkflowMode.BUILD:
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
        if intent.mode == WorkflowMode.INVESTIGATE:
            txt = handle_investigate(self.project_dir, text, chat_id)
        elif intent.mode == WorkflowMode.EXPLORE:
            txt = handle_explore(self.project_dir, text, chat_id)
        elif intent.mode == WorkflowMode.BUILD:
            txt = handle_build(self.project_dir, text, chat_id)
        elif intent.mode == WorkflowMode.HYBRID:
            txt = handle_investigate(self.project_dir, text, chat_id)
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
