#!/usr/bin/env python3
"""
telegram-bridge.py — Bridge between Telegram and Voronoi swarm

Listens for /voronoi commands on Telegram and translates them into
.swarm/inbox/ command files that the orchestrator can process.

Can also run bd (beads) commands directly.

Usage:
    python3 scripts/telegram-bridge.py [--config .swarm-config.json]

Telegram Commands:
    /voronoi status              — Get swarm status via Beads
    /voronoi investigate <question> — Launch scientific investigation
    /voronoi explore <question>  — Launch exploration/comparison
    /voronoi build <description> — Launch build workflow
    /voronoi experiment <hypothesis> — Launch experimental workflow (max rigor)
    /voronoi recall <query>      — Search knowledge store
    /voronoi belief              — Show current belief map
    /voronoi journal             — Show recent journal entries
    /voronoi finding <id>        — Show a specific finding
    /voronoi reprioritize <id> <priority> — Change task priority
    /voronoi pause <id>          — Pause/block a task
    /voronoi resume <id>         — Resume a paused task
    /voronoi add <title>         — Create a new task
    /voronoi abort               — Graceful swarm shutdown
    /voronoi pivot <message>     — Strategic pivot (creates new direction)
    /voronoi tasks               — List all open tasks
    /voronoi ready               — List ready (unblocked) tasks
    /voronoi guide <message>     — Free-form guidance note for agents

Free-text messages in group chats are classified for scientific intent.
If a scientific question is detected, Voronoi responds with a confirmation
and dispatches the appropriate workflow.

Configuration via .swarm-config.json:
    "notifications": {
        "telegram": {
            "bot_token": "...",
            "chat_id": "...",
            "bridge_enabled": true,
            "free_text_in_groups": true
        }
    }

Requirements:
    pip install python-telegram-bot
"""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Add the src directory to path so we can import voronoi.gateway modules
_src_dir = Path(__file__).resolve().parent.parent / "src"
if _src_dir.is_dir() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_dotenv(env_path: Path = None) -> None:
    """Load .env file into os.environ (only sets vars not already set)."""
    if env_path is None:
        # Try CWD first, then script parent
        for candidate in [Path.cwd() / ".env", Path(__file__).parent.parent / ".env"]:
            if candidate.exists():
                env_path = candidate
                break
    if env_path is None or not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove inline comments
                if "  #" in value:
                    value = value[:value.index("  #")].strip()
                elif "\t#" in value:
                    value = value[:value.index("\t#")].strip()
                if key not in os.environ:
                    os.environ[key] = value


def load_config(config_path: str = ".swarm-config.json") -> dict:
    """Load config from .env and optionally .swarm-config.json."""
    # Load .env first (checks CWD, then script parent, then ~/.voronoi/)
    load_dotenv()
    load_dotenv(Path.home() / ".voronoi" / ".env")

    path = Path(config_path)
    if not path.exists():
        # Try relative to script location
        path = Path(__file__).parent.parent / config_path
    if not path.exists():
        # Try server mode: ~/.voronoi/.swarm-config.json
        path = Path.home() / ".voronoi" / ".swarm-config.json"

    config = {}
    tg = {}
    if path.exists():
        with open(path) as f:
            config = json.load(f)
        tg = config.get("notifications", {}).get("telegram", {})

    # Parse user allowlist (comma-separated user IDs or usernames)
    raw_allowlist = os.environ.get("VORONOI_TG_USER_ALLOWLIST", tg.get("user_allowlist", ""))
    user_allowlist = [u.strip().lower() for u in raw_allowlist.split(",") if u.strip()] if raw_allowlist else []

    return {
        "bot_token": os.environ.get("VORONOI_TG_BOT_TOKEN", tg.get("bot_token", "")),
        "user_allowlist": user_allowlist,
        "bridge_enabled": tg.get("bridge_enabled", True),
        "project_dir": config.get("project_dir", os.getcwd()),
        "project_name": config.get("project_name", "voronoi"),
        "swarm_dir": config.get("swarm_dir", ""),
        "agent_command": os.environ.get(
            "VORONOI_AGENT_COMMAND", config.get("agent_command", "copilot"),
        ),
        "gh_token": os.environ.get("GH_TOKEN", ""),
    }


def save_chat_id(project_dir: str, chat_id: int | str) -> None:
    """Persist the active Telegram chat ID so notify-telegram.sh can read it.

    Written every time a user sends a /voronoi command so that outbound
    notifications are routed to whichever chat the user is interacting from.
    The .env VORONOI_TG_CHAT_ID serves as the fallback default.
    """
    chat_file = Path(project_dir) / ".telegram-chat-id"
    chat_file.write_text(str(chat_id).strip() + "\n")


# ---------------------------------------------------------------------------
# Inbox: write command files for autopilot to poll
# ---------------------------------------------------------------------------

INBOX_DIR = None  # Set after config load


def write_inbox_command(action: str, params: dict, message: str = "") -> str:
    """Write a command file to .swarm/inbox/ for autopilot to process."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    cmd_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    cmd = {
        "id": cmd_id,
        "action": action,
        "params": params,
        "message": message,
        "timestamp": time.time(),
        "source": "telegram",
    }

    cmd_file = INBOX_DIR / f"{cmd_id}.json"
    with open(cmd_file, "w") as f:
        json.dump(cmd, f, indent=2)

    return cmd_id


# ---------------------------------------------------------------------------
# bd (beads) helpers
# ---------------------------------------------------------------------------

def run_bd(*args, cwd=None) -> tuple[int, str]:
    """Run a bd command, return (exit_code, output).

    Sets BEADS_DIR so bd finds the database even when the subprocess
    inherits an environment without it (e.g. server started outside the
    project directory).
    """
    env = os.environ.copy()
    if cwd and "BEADS_DIR" not in env:
        beads_dir = os.path.join(cwd, ".beads")
        if os.path.isdir(beads_dir):
            env["BEADS_DIR"] = beads_dir
    try:
        result = subprocess.run(
            ["bd", *args],
            capture_output=True, text=True, timeout=30,
            cwd=cwd, env=env,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return 1, "bd (beads) not found"
    except subprocess.TimeoutExpired:
        return 1, "Command timed out"


def run_script(script: str, *args, cwd=None) -> tuple[int, str]:
    """Run a shell script, return (exit_code, output)."""
    try:
        result = subprocess.run(
            ["bash", script, *args],
            capture_output=True, text=True, timeout=60,
            cwd=cwd,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return 1, f"Script not found: {script}"
    except subprocess.TimeoutExpired:
        return 1, "Script timed out"


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def handle_status(config: dict) -> str:
    """Get swarm status."""
    # Use bd commands directly for status
    _, ready = run_bd("ready", "--json", cwd=config["project_dir"])
    _, open_tasks = run_bd("list", "--status", "open", "--json", cwd=config["project_dir"])

    try:
        ready_count = len(json.loads(ready))
    except Exception:
        ready_count = "?"
    try:
        open_count = len(json.loads(open_tasks))
    except Exception:
        open_count = "?"

    return f"📊 *Swarm Status*\nReady: {ready_count}\nOpen: {open_count}"


def handle_tasks(config: dict) -> str:
    """List open tasks."""
    code, output = run_bd("list", "--status", "open", "--json", cwd=config["project_dir"])
    if code != 0:
        return f"❌ Failed to list tasks: {output}"

    try:
        tasks = json.loads(output)
    except json.JSONDecodeError:
        return f"❌ Invalid JSON from bd: {output[:200]}"

    if not tasks:
        return "✅ No open tasks!"

    lines = ["📋 *Open Tasks*\n"]
    for t in tasks[:20]:  # Limit to 20
        tid = t.get("id", "?")
        title = t.get("title", "?")[:60]
        priority = t.get("priority", "?")
        status = t.get("status", "?")
        lines.append(f"• `{tid}` P{priority} [{status}] {title}")

    if len(tasks) > 20:
        lines.append(f"\n… and {len(tasks) - 20} more")

    return "\n".join(lines)


def handle_ready(config: dict) -> str:
    """List ready (unblocked) tasks."""
    code, output = run_bd("ready", "--json", cwd=config["project_dir"])
    if code != 0:
        return f"❌ Failed to get ready tasks: {output}"

    try:
        tasks = json.loads(output)
    except json.JSONDecodeError:
        return f"❌ Invalid JSON from bd: {output[:200]}"

    if not tasks:
        return "⏳ No unblocked tasks ready"

    lines = ["⚡ *Ready Tasks*\n"]
    for t in tasks[:15]:
        tid = t.get("id", "?")
        title = t.get("title", "?")[:60]
        priority = t.get("priority", "?")
        lines.append(f"• `{tid}` P{priority} {title}")

    return "\n".join(lines)


def handle_reprioritize(config: dict, task_id: str, priority: str) -> str:
    """Change task priority."""
    code, output = run_bd("update", task_id, "--priority", priority, cwd=config["project_dir"])
    if code != 0:
        return f"❌ Failed: {output}"

    write_inbox_command("reprioritize", {"target": task_id, "priority": int(priority)})
    return f"✅ Task `{task_id}` priority set to {priority}"


def handle_pause(config: dict, task_id: str) -> str:
    """Pause/block a task."""
    code, output = run_bd("update", task_id, "--notes", "BLOCKED: Paused by operator via Telegram", cwd=config["project_dir"])
    write_inbox_command("pause", {"target": task_id}, "Paused by operator")
    return f"⏸ Task `{task_id}` paused"


def handle_resume(config: dict, task_id: str) -> str:
    """Resume a paused task."""
    code, output = run_bd("update", task_id, "--status", "open", cwd=config["project_dir"])
    write_inbox_command("resume", {"target": task_id}, "Resumed by operator")
    return f"▶️ Task `{task_id}` resumed"


def handle_add(config: dict, title: str, description: str = "") -> str:
    """Create a new task."""
    args = ["create", title]
    if description:
        args += [f"--description={description}"]
    args += ["-t", "task", "-p", "1", "--json"]

    code, output = run_bd(*args, cwd=config["project_dir"])
    if code != 0:
        return f"❌ Failed to create task: {output}"

    try:
        result = json.loads(output)
        new_id = result.get("id", "?")
    except Exception:
        new_id = "?"

    write_inbox_command("add_task", {"title": title, "task_id": new_id}, description)
    return f"✅ Created task `{new_id}`: {title}"


def handle_abort(config: dict) -> str:
    """Request graceful swarm abort."""
    write_inbox_command("abort", {}, "Operator requested abort via Telegram")
    return "🛑 *Abort requested* — autopilot will shut down gracefully after current agents complete"


def handle_pivot(config: dict, message: str) -> str:
    """Strategic pivot — creates guidance note for agents."""
    write_inbox_command("pivot", {"message": message}, message)
    # Also write a strategic guidance file
    guidance_dir = Path(config["project_dir"]) / ".swarm"
    guidance_dir.mkdir(parents=True, exist_ok=True)
    guidance_file = guidance_dir / "operator-guidance.md"

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    with open(guidance_file, "a") as f:
        f.write(f"\n## Pivot — {timestamp}\n\n{message}\n")

    return f"🔀 *Pivot recorded*\n\nGuidance written to `.swarm/operator-guidance.md`\nAgents will read this on next dispatch."


def handle_guide(config: dict, message: str) -> str:
    """Free-form guidance note."""
    write_inbox_command("guide", {"message": message}, message)

    guidance_dir = Path(config["project_dir"]) / ".swarm"
    guidance_dir.mkdir(parents=True, exist_ok=True)
    guidance_file = guidance_dir / "operator-guidance.md"

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    with open(guidance_file, "a") as f:
        f.write(f"\n## Guidance — {timestamp}\n\n{message}\n")

    return f"📝 *Guidance noted*\n\n_{message}_"


# ---------------------------------------------------------------------------
# Science workflow handlers (NEW)
# ---------------------------------------------------------------------------

_MEMORY_INSTANCE = None
_KNOWLEDGE_INSTANCE = None


def _get_memory(config: dict):
    """Get or create the ConversationMemory singleton."""
    global _MEMORY_INSTANCE
    if _MEMORY_INSTANCE is None:
        try:
            from voronoi.gateway.memory import ConversationMemory
            db_path = Path(config["project_dir"]) / ".swarm" / "conversations.db"
            _MEMORY_INSTANCE = ConversationMemory(db_path)
        except ImportError:
            pass
    return _MEMORY_INSTANCE


def _get_knowledge(config: dict):
    """Get or create the KnowledgeStore singleton."""
    global _KNOWLEDGE_INSTANCE
    if _KNOWLEDGE_INSTANCE is None:
        try:
            from voronoi.gateway.knowledge import KnowledgeStore
            _KNOWLEDGE_INSTANCE = KnowledgeStore(config["project_dir"])
        except ImportError:
            pass
    return _KNOWLEDGE_INSTANCE


def _save_user_message(config: dict, chat_id: str, text: str, metadata: dict = None):
    """Save a user message to conversation memory."""
    mem = _get_memory(config)
    if mem is None:
        return
    try:
        from voronoi.gateway.memory import Message
        mem.save_message(Message(
            chat_id=str(chat_id),
            role="user",
            content=text,
            metadata=metadata or {},
        ))
    except Exception:
        pass  # Memory is best-effort


def _save_bot_reply(config: dict, chat_id: str, text: str, metadata: dict = None):
    """Save a bot reply to conversation memory."""
    mem = _get_memory(config)
    if mem is None:
        return
    try:
        from voronoi.gateway.memory import Message
        mem.save_message(Message(
            chat_id=str(chat_id),
            role="assistant",
            content=text,
            metadata=metadata or {},
        ))
    except Exception:
        pass


def handle_investigate(config: dict, question: str) -> str:
    """Launch a scientific investigation workflow."""
    try:
        from voronoi.gateway.progress import format_workflow_start
        start_msg = format_workflow_start("investigate", "scientific", question)
    except ImportError:
        start_msg = f"🔬 *INVESTIGATE* mode activated\n\n_{question}_\n\nDispatching agents..."

    cmd_id = write_inbox_command(
        "investigate",
        {"question": question, "mode": "investigate", "rigor": "scientific"},
        question,
    )
    return start_msg + f"\n\nWorkflow ID: `{cmd_id}`"


def handle_explore(config: dict, question: str) -> str:
    """Launch an exploration/comparison workflow."""
    try:
        from voronoi.gateway.progress import format_workflow_start
        start_msg = format_workflow_start("explore", "analytical", question)
    except ImportError:
        start_msg = f"🧭 *EXPLORE* mode activated\n\n_{question}_\n\nDispatching agents..."

    cmd_id = write_inbox_command(
        "explore",
        {"question": question, "mode": "explore", "rigor": "analytical"},
        question,
    )
    return start_msg + f"\n\nWorkflow ID: `{cmd_id}`"


def handle_build(config: dict, description: str) -> str:
    """Launch a build workflow."""
    try:
        from voronoi.gateway.progress import format_workflow_start
        start_msg = format_workflow_start("build", "standard", description)
    except ImportError:
        start_msg = f"🔨 *BUILD* mode activated\n\n_{description}_\n\nDispatching agents..."

    cmd_id = write_inbox_command(
        "build",
        {"description": description, "mode": "build", "rigor": "standard"},
        description,
    )
    return start_msg + f"\n\nWorkflow ID: `{cmd_id}`"


def handle_experiment(config: dict, hypothesis: str) -> str:
    """Launch an experimental workflow (highest rigor)."""
    try:
        from voronoi.gateway.progress import format_workflow_start
        start_msg = format_workflow_start("investigate", "experimental", hypothesis)
    except ImportError:
        start_msg = f"🔬 *EXPERIMENT* mode activated (max rigor)\n\n_{hypothesis}_\n\nDispatching agents..."

    cmd_id = write_inbox_command(
        "experiment",
        {"hypothesis": hypothesis, "mode": "investigate", "rigor": "experimental"},
        hypothesis,
    )
    return start_msg + f"\n\nWorkflow ID: `{cmd_id}`"


def handle_recall(config: dict, query: str) -> str:
    """Search the knowledge store for past findings."""
    ks = _get_knowledge(config)
    if ks is None:
        return "❌ Knowledge store not available (voronoi gateway not installed)"
    return ks.format_recall_response(query)


def handle_belief(config: dict) -> str:
    """Show the current belief map."""
    ks = _get_knowledge(config)
    if ks is None:
        return "❌ Knowledge store not available"
    belief = ks.get_belief_map()
    if belief is None:
        return "📊 No belief map found. Start an investigation to generate one."
    return f"📊 *Belief Map*\n\n{belief}"


def handle_journal(config: dict, max_lines: int = 30) -> str:
    """Show recent journal entries."""
    ks = _get_knowledge(config)
    if ks is None:
        return "❌ Knowledge store not available"
    journal = ks.get_journal(max_lines=max_lines)
    if journal is None:
        return "📓 No journal found. Start a workflow to begin recording."
    return f"📓 *Journal* (last {max_lines} lines)\n\n{journal}"


def handle_finding(config: dict, finding_id: str) -> str:
    """Show details of a specific finding."""
    code, output = run_bd("show", finding_id, "--json", cwd=config["project_dir"])
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


def _is_greeting_or_intro(text: str) -> bool:
    """Detect greetings or 'what can you do' type messages."""
    t = text.lower().strip().rstrip("?!.")
    greetings = {"hi", "hello", "hey", "yo", "sup", "hi there", "hello there", "hey there"}
    if t in greetings:
        return True
    intro_phrases = [
        "what can you do", "what do you do", "who are you",
        "how do you work", "how does this work", "what is voronoi",
        "what is this", "help", "help me", "what are you",
        "introduce yourself", "capabilities",
    ]
    return any(phrase in t for phrase in intro_phrases)


_INTRO_MESSAGE = (
    "🔬 *Voronoi — Ask a question. Get evidence.*\n\n"
    "I'm your personal research lab in a chat window. "
    "Drop me a question — anything from _\"why is our model degrading?\"_ "
    "to _\"does EWC beat replay for catastrophic forgetting?\"_ — and I'll "
    "dispatch a swarm of AI agents to investigate it.\n\n"
    "Hypotheses. Experiments. Statistical validation. Belief maps. "
    "Findings with effect sizes and confidence intervals. "
    "The whole scientific method, on autopilot. 🧪\n\n"
    "_Send_ `/voronoi` _for commands, or just ask me something._ 🧠"
)


def handle_free_text_science(config: dict, text: str, chat_id: str):
    """Classify free-text for scientific intent. Returns reply or None if not science."""
    # Handle greetings / "what can you do" questions
    if _is_greeting_or_intro(text):
        return _INTRO_MESSAGE

    try:
        from voronoi.gateway.intent import classify, WorkflowMode
    except ImportError:
        return None

    intent = classify(text)

    # Only trigger on science-related intents with reasonable confidence
    if intent.is_meta:
        if intent.mode == WorkflowMode.RECALL:
            return handle_recall(config, intent.summary)
        return None

    if intent.confidence < 0.5:
        return None

    if not intent.is_science and intent.mode != WorkflowMode.BUILD:
        return None

    # Save to memory
    _save_user_message(config, chat_id, text, {
        "intent": intent.mode.value,
        "rigor": intent.rigor.value,
        "confidence": intent.confidence,
    })

    # Dispatch based on classified intent
    if intent.mode == WorkflowMode.INVESTIGATE:
        return handle_investigate(config, intent.summary)
    elif intent.mode == WorkflowMode.EXPLORE:
        return handle_explore(config, intent.summary)
    elif intent.mode == WorkflowMode.BUILD:
        return handle_build(config, intent.summary)
    elif intent.mode == WorkflowMode.HYBRID:
        return handle_investigate(config, intent.summary)

    return None

def run_bot(config: dict):
    """Main bot loop using python-telegram-bot."""
    try:
        from telegram import Update
        from telegram.ext import (
            Application,
            CommandHandler,
            ContextTypes,
        )
    except ImportError:
        print("python-telegram-bot not installed. Run: pip install python-telegram-bot", file=sys.stderr)
        sys.exit(1)

    from telegram.ext import MessageHandler, filters

    bot_token = config["bot_token"]
    user_allowlist = config.get("user_allowlist", [])

    if not bot_token:
        print("No bot_token configured", file=sys.stderr)
        sys.exit(1)

    # Resolve bot username once at startup (used for @mention detection in groups)
    _bot_username = [None]  # mutable container for closure

    def is_user_allowed(update: Update) -> bool:
        """Check if the user is in the allowlist. No allowlist = open to all."""
        if not user_allowlist:
            return True
        user = update.effective_user
        if user is None:
            return False
        uid = str(user.id).lower()
        uname = (user.username or "").lower()
        return uid in user_allowlist or uname in user_allowlist

    def is_group_directed(update: Update) -> bool:
        """In groups, only respond if @mentioned or replied to."""
        msg = update.message
        if msg is None:
            return False
        # Check if user replied to one of our messages
        if msg.reply_to_message and msg.reply_to_message.from_user:
            if msg.reply_to_message.from_user.is_bot and _bot_username[0]:
                if msg.reply_to_message.from_user.username == _bot_username[0]:
                    return True
        # Check if bot is @mentioned in text
        text = msg.text or ""
        if _bot_username[0] and f"@{_bot_username[0]}" in text:
            return True
        return False

    async def cmd_voronoi(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /voronoi commands."""
        if not is_user_allowed(update):
            if update.message:
                await update.message.reply_text("You are not authorized to use this bot.")
            return

        # Persist the chat ID so outbound notifications target this chat
        if update.message and update.message.chat_id:
            save_chat_id(config["project_dir"], update.message.chat_id)

        args = context.args or []
        if not args:
            await update.message.reply_text(
                "� *Hey! I'm Voronoi.*\n\n"
                "I orchestrate AI agents to run scientific investigations, "
                "build software, and explore ideas — all from this chat.\n\n"
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
                "`/voronoi status` · `tasks` · `ready`\n\n"
                "🎛 *Control*\n"
                "`/voronoi guide <msg>` · `pivot <msg>` · `abort`\n\n"
                "_In groups, @mention me or reply to my messages._",
                parse_mode="Markdown",
            )
            return

        subcommand = args[0].lower()

        try:
            if subcommand in ("help", "hi", "hello", "hey"):
                # Re-trigger the intro message
                args.clear()
                await cmd_voronoi(update, context)
                return
            elif subcommand == "status":
                reply = handle_status(config)
            elif subcommand == "tasks":
                reply = handle_tasks(config)
            elif subcommand == "ready":
                reply = handle_ready(config)
            elif subcommand == "investigate" and len(args) >= 2:
                question = " ".join(args[1:])
                reply = handle_investigate(config, question)
            elif subcommand == "explore" and len(args) >= 2:
                question = " ".join(args[1:])
                reply = handle_explore(config, question)
            elif subcommand == "build" and len(args) >= 2:
                description = " ".join(args[1:])
                reply = handle_build(config, description)
            elif subcommand == "experiment" and len(args) >= 2:
                hypothesis = " ".join(args[1:])
                reply = handle_experiment(config, hypothesis)
            elif subcommand == "recall" and len(args) >= 2:
                query = " ".join(args[1:])
                reply = handle_recall(config, query)
            elif subcommand == "belief":
                reply = handle_belief(config)
            elif subcommand == "journal":
                reply = handle_journal(config)
            elif subcommand == "finding" and len(args) >= 2:
                reply = handle_finding(config, args[1])
            elif subcommand == "reprioritize" and len(args) >= 3:
                reply = handle_reprioritize(config, args[1], args[2])
            elif subcommand == "pause" and len(args) >= 2:
                reply = handle_pause(config, args[1])
            elif subcommand == "resume" and len(args) >= 2:
                reply = handle_resume(config, args[1])
            elif subcommand == "add" and len(args) >= 2:
                title = " ".join(args[1:])
                reply = handle_add(config, title)
            elif subcommand == "abort":
                reply = handle_abort(config)
            elif subcommand == "pivot" and len(args) >= 2:
                message = " ".join(args[1:])
                reply = handle_pivot(config, message)
            elif subcommand == "guide" and len(args) >= 2:
                message = " ".join(args[1:])
                reply = handle_guide(config, message)
            else:
                reply = f"❓ Unknown command: `{subcommand}`\nSend `/voronoi` for help."
        except Exception as e:
            reply = f"❌ Error: {e}"

        # Save conversation to memory
        _save_user_message(config, str(update.message.chat_id),
                           update.message.text or "", {"command": subcommand})
        _save_bot_reply(config, str(update.message.chat_id), reply)

        try:
            await update.message.reply_text(reply, parse_mode="Markdown")
        except Exception:
            # Fallback without Markdown
            await update.message.reply_text(reply)

    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle free-text messages.

        In private chats: treated as guidance notes (original behavior).
        In group chats: only responds if @mentioned or replied to.
        """
        if not is_user_allowed(update):
            return

        if update.message is None:
            return

        text = (update.message.text or "").strip()
        if not text:
            return

        chat_id = str(update.message.chat_id)
        is_private = update.message.chat.type == "private"
        is_group = update.message.chat.type in ("group", "supergroup")

        # In groups, only respond if @mentioned or replied to
        if is_group and not is_group_directed(update):
            return

        # Persist chat ID for outbound notifications
        save_chat_id(config["project_dir"], update.message.chat_id)

        # Strip @botname from text if present
        if _bot_username[0]:
            text = text.replace(f"@{_bot_username[0]}", "").strip()

        if is_private:
            # Private chats: check for greetings/intro first, then try science, then guidance
            if _is_greeting_or_intro(text):
                reply = _INTRO_MESSAGE
            else:
                reply = handle_free_text_science(config, text, chat_id)
                if reply is None:
                    reply = handle_guide(config, text)
        elif is_group:
            # Group chats: try scientific intent detection
            reply = handle_free_text_science(config, text, chat_id)
            if reply is None:
                reply = handle_guide(config, text)
        else:
            return

        # Save bot reply to memory
        _save_bot_reply(config, chat_id, reply)

        try:
            await update.message.reply_text(reply, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(reply)

    # Build and run the bot
    app = Application.builder().token(bot_token).build()

    # Resolve bot username for @mention detection
    async def _post_init(application):
        me = await application.bot.get_me()
        _bot_username[0] = me.username
        print(f"   Bot username: @{me.username}")

    app.post_init = _post_init
    app.add_handler(CommandHandler("voronoi", cmd_voronoi))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # ------------------------------------------------------------------
    # Investigation dispatcher — processes inbox, launches & monitors
    # ------------------------------------------------------------------
    _dispatcher = [None]  # mutable container for closure

    def _init_dispatcher():
        """Initialize the investigation dispatcher (lazy, best-effort)."""
        if _dispatcher[0] is not None:
            return _dispatcher[0]
        try:
            from voronoi.server.dispatcher import InvestigationDispatcher, DispatcherConfig
            from voronoi.server.runner import ServerConfig

            server_config = ServerConfig()
            dc = DispatcherConfig(
                base_dir=server_config.base_dir,
                max_concurrent=server_config.max_concurrent,
                max_agents=server_config.max_agents_per_investigation,
                agent_command=server_config.agent_command,
                agent_flags=server_config.agent_flags,
            )

            # The send_message callback — sends to the last active chat
            def _send_to_telegram(text: str):
                """Queue a message to send via the bot."""
                chat_id_file = Path(config["project_dir"]) / ".telegram-chat-id"
                if not chat_id_file.exists():
                    return
                chat_id = chat_id_file.read_text().strip()
                if not chat_id:
                    return
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(_async_send(chat_id, text))
                    else:
                        loop.run_until_complete(_async_send(chat_id, text))
                except Exception:
                    pass  # Best-effort

            async def _async_send(chat_id: str, text: str):
                try:
                    await app.bot.send_message(
                        chat_id=chat_id, text=text,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                    )
                except Exception:
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id, text=text,
                            disable_web_page_preview=True,
                        )
                    except Exception:
                        pass

            _dispatcher[0] = InvestigationDispatcher(dc, _send_to_telegram)
            print("   ✓ Investigation dispatcher initialized")
        except Exception as e:
            print(f"   ⚠ Dispatcher not available: {e}")
        return _dispatcher[0]

    async def _job_poll_inbox(context):
        """Periodic job: check inbox for new commands."""
        d = _init_dispatcher()
        if d:
            try:
                d.poll_inbox()
            except Exception as e:
                print(f"Inbox poll error: {e}")

    async def _job_poll_progress(context):
        """Periodic job: check progress of running investigations."""
        d = _init_dispatcher()
        if d:
            try:
                d.poll_progress()
            except Exception as e:
                print(f"Progress poll error: {e}")

    # Schedule periodic jobs (requires python-telegram-bot[job-queue])
    if app.job_queue is not None:
        app.job_queue.run_repeating(_job_poll_inbox, interval=10, first=5)
        app.job_queue.run_repeating(_job_poll_progress, interval=30, first=15)
    else:
        print("⚠️  JobQueue not available. Install with: pip install 'python-telegram-bot[job-queue]'")
        print("   Dispatcher inbox/progress polling disabled.")

    allowlist_str = ", ".join(user_allowlist) if user_allowlist else "any"
    print(f"🤖 Telegram bridge started for {config['project_name']}")
    print(f"   Allowed users: {allowlist_str}")
    print(f"   Inbox dir: {INBOX_DIR}")
    print(f"   Project: {config['project_dir']}")
    print(f"   /voronoi commands work everywhere")
    print(f"   In groups: responds to @mentions and replies")
    print(f"   Dispatcher: polling inbox every 10s, progress every 30s")
    # run_polling() is a synchronous convenience method that manages its own
    # event loop — it must NOT be awaited from inside an async context.
    app.run_polling(drop_pending_updates=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Voronoi ↔ Telegram bridge")
    parser.add_argument("--config", default=".swarm-config.json", help="Path to .swarm-config.json")
    args = parser.parse_args()

    config = load_config(args.config)

    global INBOX_DIR
    INBOX_DIR = Path(config["project_dir"]) / ".swarm" / "inbox"

    if not config["bot_token"]:
        print("Error: No Telegram bot token configured", file=sys.stderr)
        print("Set VORONOI_TG_BOT_TOKEN or add to .swarm-config.json notifications.telegram.bot_token",
              file=sys.stderr)
        sys.exit(1)

    run_bot(config)


if __name__ == "__main__":
    main()
