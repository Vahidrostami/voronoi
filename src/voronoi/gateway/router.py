"""Command router — central dispatch for all Voronoi commands.

Every user action (Telegram command, free-text, CLI) flows through
the public functions in this module.  The Telegram bridge and any
future UI are thin I/O layers that call these functions and send
the result.

Handler implementations live in:
  - handlers_query.py   — read-only status/progress/knowledge queries
  - handlers_mutate.py  — task/investigation state changes
  - handlers_workflow.py — investigation enqueue (discover/prove/demo)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from voronoi.gateway.intent import ClassifiedIntent, WorkflowMode, classify, classify_for_new_investigation
from voronoi.gateway.progress import MODE_EMOJI

# --- Re-export all handlers so existing imports keep working ---
from voronoi.gateway.handlers_query import (  # noqa: F401
    handle_status,
    handle_whatsup,
    handle_howsitgoing,
    handle_board,
    handle_tasks,
    handle_health,
    handle_ready,
    handle_details,
    handle_results,
    handle_recall,
    handle_belief,
    handle_finding,
    handle_claims,
    handle_ask,
    handle_deliberate,
    handle_ops,
)
from voronoi.gateway.handlers_mutate import (  # noqa: F401
    handle_reprioritize,
    handle_pause,
    handle_resume,
    handle_resume_investigation,
    handle_add,
    handle_complete,
    handle_complete_investigation,
    handle_review_investigation,
    handle_continue_investigation,
    handle_abort,
    handle_pivot,
    handle_guide,
)
from voronoi.gateway.handlers_workflow import (  # noqa: F401
    handle_discover,
    handle_prove,
    handle_demo,
)

logger = logging.getLogger("voronoi.router")

__all__ = [
    "CommandRouter",
    "handle_status", "handle_whatsup", "handle_howsitgoing",
    "handle_tasks", "handle_ready", "handle_health", "handle_board",
    "handle_reprioritize", "handle_pause", "handle_resume", "handle_add",
    "handle_resume_investigation",
    "handle_complete",
    "handle_complete_investigation",
    "handle_review_investigation", "handle_continue_investigation", "handle_claims",
    "handle_abort", "handle_pivot", "handle_guide",
    "handle_discover", "handle_prove",
    "handle_recall", "handle_belief", "handle_finding", "handle_ops",
    "handle_results", "handle_demo", "handle_details",
    "handle_ask", "handle_deliberate",
]


# ---------------------------------------------------------------------------
# Conversation memory helpers (best-effort, created per call)
# ---------------------------------------------------------------------------

def _get_memory(project_dir: str):
    from voronoi.gateway.memory import ConversationMemory
    db = Path(project_dir) / ".swarm" / "conversations.db"
    return ConversationMemory(db)


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
# Free-text classification
# ---------------------------------------------------------------------------

_INTRO_MESSAGE = (
    "👋 *Voronoi* — ask a question, get evidence.\n\n"
    "Drop me a question — anything from _\"why is our model degrading?\"_ "
    "to _\"does EWC beat replay for catastrophic forgetting?\"_ — and I'll "
    "spin up a team of AI agents to find out.\n\n"
    "Or send `/voronoi` to see what I can do."
)

def _LOW_CONFIDENCE_MESSAGE(text: str, intent) -> str:
    """Return a helpful clarification prompt when intent confidence is low."""
    mode_label = intent.mode.value if intent.mode else "unknown"
    confidence_pct = int(intent.confidence * 100)
    return (
        f"Hmm, I'm only {confidence_pct}% sure what you're after (leaning toward _{mode_label}_).\n\n"
        f"Your message: _{text[:120]}_\n\n"
        "Try phrasing it like:\n"
        "  _Why is our model accuracy dropping?_ → discover\n"
        "  _Prove that EWC beats replay_ → prove\n\n"
        "Or go direct:\n"
        "`/voronoi discover <question>`\n"
        "`/voronoi prove <hypothesis>`"
    )


_HELP_MESSAGE = (
    "🧪 *Voronoi* — your AI research lab\n\n"
    "Just ask me anything:\n"
    "  → _Why is our model accuracy dropping?_\n"
    "  → _Prove that EWC beats replay for catastrophic forgetting_\n"
    "  → _Compare Redis vs Memcached_\n\n"
    "I'll figure out the rest — pick the right approach, "
    "spin up agents, and bring you findings.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "*Check in*\n"
    "`/voronoi status` — what's happening now\n"
    "`/voronoi board` — Kanban snapshot\n"
    "`/voronoi progress` — metrics + criteria\n\n"
    "*Investigate*\n"
    "`/voronoi discover <question>`\n"
    "`/voronoi prove <hypothesis>`\n\n"
    "*Knowledge*\n"
    "`/voronoi belief` · `finding <id>` · `recall <query>`\n"
    "`/voronoi ask <question>` — ask about a running investigation\n\n"
    "*Review*\n"
    "`/voronoi deliberate [codename]` — reason about results interactively\n\n"
    "*Steer*\n"
    "`/voronoi guide <msg>` · `pivot <msg>` · `abort`\n\n"
    "*Ops*\n"
    "`/voronoi ops` — server diagnostics (tmux, disk, logs)\n\n"
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
        lines = ["\U0001F3AE *Available Demos*\n"]
        for d in demos:
            marker = "\u2713" if d["has_prompt"] else "\u25cb"
            lines.append(f"  {marker} `{d['name']}` \u2014 {d['description']}")
        lines.append("\nRun with: `/voronoi demo run <name>`")
        return "\n".join(lines)

    def route(self, command: str, args: list[str],
              chat_id: str, *,
              ops_allowed: bool = True) -> tuple[str, Optional[Path]]:
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
            elif sub in ("task", "tasks"):
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
                arg = args[0]
                is_beads_task = arg.startswith("bd-")
                if is_beads_task:
                    return handle_resume(self.project_dir, arg), None
                return handle_resume_investigation(self.project_dir, arg), None
            elif sub == "add" and args:
                return handle_add(self.project_dir, " ".join(args)), None
            elif sub == "complete" and args:
                arg = args[0]
                is_beads_task = arg.startswith("bd-")
                if is_beads_task:
                    reason = " ".join(args[1:]) if len(args) > 1 else "Completed"
                    return handle_complete(self.project_dir, arg, reason), None
                return handle_complete_investigation(self.project_dir, arg), None
            elif sub == "abort":
                return handle_abort(self.project_dir), None
            elif sub == "pivot" and args:
                return handle_pivot(self.project_dir, " ".join(args)), None
            elif sub == "guide" and args:
                return handle_guide(self.project_dir, " ".join(args)), None
            elif sub == "review":
                arg = args[0] if args else ""
                return handle_review_investigation(self.project_dir, arg), None
            elif sub == "continue" and args:
                identifier = args[0]
                feedback = " ".join(args[1:]) if len(args) > 1 else ""
                return handle_continue_investigation(self.project_dir, identifier, feedback), None
            elif sub == "claims":
                arg = args[0] if args else ""
                return handle_claims(self.project_dir, arg), None
            elif sub == "ask" and args:
                return handle_ask(self.project_dir, " ".join(args)), None
            elif sub == "deliberate":
                codename = args[0] if args else ""
                return handle_deliberate(self.project_dir, codename), None
            elif sub == "ops":
                ops_sub = args[0] if args else ""
                return handle_ops(self.project_dir, ops_sub, ops_allowed=ops_allowed), None
            else:
                return f"❓ Unknown command: `{sub}`\nSend `/voronoi` for help.", None
        except Exception as e:
            logger.error("Command %s failed: %s", sub, e, exc_info=True)
            return f"❌ Error: {e}", None

    def _has_running_investigations(self) -> bool:
        """Check if any investigations are currently running."""
        try:
            from voronoi.server.queue import InvestigationQueue
            base = Path.home() / ".voronoi"
            q = InvestigationQueue(base / "queue.db")
            return len(q.get_running()) > 0
        except Exception:
            return False

    def handle_free_text(self, text: str, chat_id: str,
                         is_private: bool) -> tuple[str, Optional[Path]]:
        """State-aware routing for free-text input.

        The routing decision depends on whether an investigation is running:
        - Investigation running → ASK (send question + workspace data to LLM)
        - No investigation → classify DISCOVER vs PROVE and start one
        - Greeting/help → intro message

        Explicit /voronoi commands always override (handled by route()).
        """
        if _is_greeting(text):
            return _INTRO_MESSAGE, None

        # Check for DELIBERATE signals first — works regardless of running state
        intent_check = classify(text)
        if intent_check.mode == WorkflowMode.DELIBERATE:
            logger.info("Classified intent: mode=deliberate confidence=%.2f (free-text deliberation)",
                        intent_check.confidence)
            _save_msg(self.project_dir, chat_id, "user", text,
                      {"intent": "deliberate", "confidence": intent_check.confidence})
            return handle_deliberate(self.project_dir), None

        has_running = self._has_running_investigations()

        if has_running:
            # Investigation is running — treat all free text as ASK
            logger.info("Classified intent: mode=ask rigor=adaptive confidence=1.00 (state-aware: investigation running)")
            _save_msg(self.project_dir, chat_id, "user", text,
                      {"intent": "ask", "confidence": 1.0})
            return handle_ask(self.project_dir, text), None

        # No investigation running — classify for a new investigation
        intent = classify_for_new_investigation(text)
        logger.info("Classified intent: mode=%s rigor=%s confidence=%.2f (state-aware: no investigation running)",
                    intent.mode.value, intent.rigor.value, intent.confidence)

        # RECALL — search knowledge store
        if intent.mode == WorkflowMode.RECALL:
            return handle_recall(self.project_dir, intent.summary), None

        # Not enough signal to start an investigation → prompt the user
        if intent.confidence < 0.5:
            _save_msg(self.project_dir, chat_id, "user", text,
                      {"intent": intent.mode.value, "confidence": intent.confidence})
            return _LOW_CONFIDENCE_MESSAGE(text, intent), None

        # Save to memory and start investigation
        _save_msg(self.project_dir, chat_id, "user", text, {
            "intent": intent.mode.value,
            "rigor": intent.rigor.value,
            "confidence": intent.confidence,
        })

        if intent.mode == WorkflowMode.PROVE:
            txt = handle_prove(self.project_dir, text, chat_id)
        else:
            txt = handle_discover(self.project_dir, text, chat_id)

        # Prepend classification feedback
        confidence_pct = int(intent.confidence * 100)
        mode_emoji = MODE_EMOJI.get(intent.mode.value, "🔷")
        feedback = (
            f"🧠 _Classified as *{intent.mode.value}* {mode_emoji} "
            f"(rigor: {intent.rigor.value} · {confidence_pct}% confidence)_\n\n"
        )
        return feedback + txt, None
