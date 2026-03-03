#!/usr/bin/env python3
"""
telegram-bridge.py — Bridge between Telegram and Voronoi swarm

Listens for /voronoi commands on Telegram and translates them into
.swarm/inbox/ command files that autopilot.sh polls and executes.

Can also run bd (beads) commands directly.

Usage:
    python3 scripts/telegram-bridge.py [--config .swarm-config.json]

Telegram Commands:
    /voronoi status              — Get swarm status (runs standup.sh)
    /voronoi reprioritize <id> <priority> — Change task priority
    /voronoi pause <id>          — Pause/block a task
    /voronoi resume <id>         — Resume a paused task
    /voronoi add <title>         — Create a new task
    /voronoi abort               — Graceful swarm shutdown
    /voronoi pivot <message>     — Strategic pivot (creates new direction)
    /voronoi tasks               — List all open tasks
    /voronoi ready               — List ready (unblocked) tasks
    /voronoi guide <message>     — Free-form guidance note for agents

Also responds to free-text messages in the configured chat with
context-aware replies about the swarm state.

Configuration via .swarm-config.json:
    "notifications": {
        "telegram": {
            "bot_token": "...",
            "chat_id": "...",
            "bridge_enabled": true
        }
    }

Requirements:
    pip install python-telegram-bot
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

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
    # Load .env first
    load_dotenv()

    path = Path(config_path)
    if not path.exists():
        # Try relative to script location
        path = Path(__file__).parent.parent / config_path

    config = {}
    tg = {}
    if path.exists():
        with open(path) as f:
            config = json.load(f)
        tg = config.get("notifications", {}).get("telegram", {})

    return {
        "bot_token": os.environ.get("VORONOI_TG_BOT_TOKEN", tg.get("bot_token", "")),
        "chat_id": os.environ.get("VORONOI_TG_CHAT_ID", tg.get("chat_id", "")),
        "bridge_enabled": tg.get("bridge_enabled", True),
        "project_dir": config.get("project_dir", os.getcwd()),
        "project_name": config.get("project_name", "voronoi"),
        "swarm_dir": config.get("swarm_dir", ""),
    }


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
    """Run a bd command, return (exit_code, output)."""
    try:
        result = subprocess.run(
            ["bd", *args],
            capture_output=True, text=True, timeout=30,
            cwd=cwd,
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

async def handle_status(config: dict) -> str:
    """Get swarm status."""
    standup = Path(config["project_dir"]) / "scripts" / "standup.sh"
    if standup.exists():
        code, output = run_script(str(standup), cwd=config["project_dir"])
        # Truncate for Telegram (max 4096 chars)
        if len(output) > 3500:
            output = output[:3500] + "\n\n… (truncated)"
        return f"📊 *Swarm Status*\n\n```\n{output}\n```"

    # Fallback: basic bd status
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


async def handle_tasks(config: dict) -> str:
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


async def handle_ready(config: dict) -> str:
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


async def handle_reprioritize(config: dict, task_id: str, priority: str) -> str:
    """Change task priority."""
    code, output = run_bd("update", task_id, "--priority", priority, cwd=config["project_dir"])
    if code != 0:
        return f"❌ Failed: {output}"

    write_inbox_command("reprioritize", {"target": task_id, "priority": int(priority)})
    return f"✅ Task `{task_id}` priority set to {priority}"


async def handle_pause(config: dict, task_id: str) -> str:
    """Pause/block a task."""
    code, output = run_bd("update", task_id, "--notes", "BLOCKED: Paused by operator via Telegram", cwd=config["project_dir"])
    write_inbox_command("pause", {"target": task_id}, "Paused by operator")
    return f"⏸ Task `{task_id}` paused"


async def handle_resume(config: dict, task_id: str) -> str:
    """Resume a paused task."""
    code, output = run_bd("update", task_id, "--status", "open", cwd=config["project_dir"])
    write_inbox_command("resume", {"target": task_id}, "Resumed by operator")
    return f"▶️ Task `{task_id}` resumed"


async def handle_add(config: dict, title: str, description: str = "") -> str:
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


async def handle_abort(config: dict) -> str:
    """Request graceful swarm abort."""
    write_inbox_command("abort", {}, "Operator requested abort via Telegram")
    return "🛑 *Abort requested* — autopilot will shut down gracefully after current agents complete"


async def handle_pivot(config: dict, message: str) -> str:
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


async def handle_guide(config: dict, message: str) -> str:
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
# Telegram bot
# ---------------------------------------------------------------------------

async def run_bot(config: dict):
    """Main bot loop using python-telegram-bot."""
    try:
        from telegram import Update
        from telegram.ext import (
            Application,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError:
        print("python-telegram-bot not installed. Run: pip install python-telegram-bot", file=sys.stderr)
        sys.exit(1)

    bot_token = config["bot_token"]
    allowed_chat = config["chat_id"]

    if not bot_token:
        print("No bot_token configured", file=sys.stderr)
        sys.exit(1)

    def is_allowed(update: Update) -> bool:
        """Check if the message is from the allowed chat."""
        if not allowed_chat:
            return True  # No restriction
        return str(update.effective_chat.id) == str(allowed_chat)

    async def cmd_voronoi(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /voronoi commands."""
        if not is_allowed(update):
            return

        args = context.args or []
        if not args:
            await update.message.reply_text(
                "🔷 *Voronoi Commands*\n\n"
                "`/voronoi status` — Swarm status\n"
                "`/voronoi tasks` — Open tasks\n"
                "`/voronoi ready` — Ready tasks\n"
                "`/voronoi reprioritize <id> <0-4>` — Change priority\n"
                "`/voronoi pause <id>` — Pause task\n"
                "`/voronoi resume <id>` — Resume task\n"
                "`/voronoi add <title>` — Add task\n"
                "`/voronoi guide <msg>` — Send guidance\n"
                "`/voronoi pivot <msg>` — Strategic pivot\n"
                "`/voronoi abort` — Graceful shutdown",
                parse_mode="Markdown",
            )
            return

        subcommand = args[0].lower()

        try:
            if subcommand == "status":
                reply = await handle_status(config)
            elif subcommand == "tasks":
                reply = await handle_tasks(config)
            elif subcommand == "ready":
                reply = await handle_ready(config)
            elif subcommand == "reprioritize" and len(args) >= 3:
                reply = await handle_reprioritize(config, args[1], args[2])
            elif subcommand == "pause" and len(args) >= 2:
                reply = await handle_pause(config, args[1])
            elif subcommand == "resume" and len(args) >= 2:
                reply = await handle_resume(config, args[1])
            elif subcommand == "add" and len(args) >= 2:
                title = " ".join(args[1:])
                reply = await handle_add(config, title)
            elif subcommand == "abort":
                reply = await handle_abort(config)
            elif subcommand == "pivot" and len(args) >= 2:
                message = " ".join(args[1:])
                reply = await handle_pivot(config, message)
            elif subcommand == "guide" and len(args) >= 2:
                message = " ".join(args[1:])
                reply = await handle_guide(config, message)
            else:
                reply = f"❓ Unknown command: `{subcommand}`\nSend `/voronoi` for help."
        except Exception as e:
            reply = f"❌ Error: {e}"

        try:
            await update.message.reply_text(reply, parse_mode="Markdown")
        except Exception:
            # Fallback without Markdown
            await update.message.reply_text(reply)

    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle free-text messages (treat as guidance)."""
        if not is_allowed(update):
            return

        text = update.message.text
        if not text:
            return

        # Only respond to messages that reference voronoi or the project
        keywords = ["voronoi", "swarm", "agent", "task", config["project_name"].lower()]
        if not any(kw in text.lower() for kw in keywords):
            return

        reply = await handle_guide(config, text)
        try:
            await update.message.reply_text(reply, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(reply)

    # Build and run the bot
    app = Application.builder().token(bot_token).build()
    app.add_handler(CommandHandler("voronoi", cmd_voronoi))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print(f"🤖 Telegram bridge started for {config['project_name']}")
    print(f"   Chat filter: {allowed_chat or 'any'}")
    print(f"   Inbox dir: {INBOX_DIR}")
    print(f"   Project: {config['project_dir']}")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # Keep running until interrupted
    stop_event = asyncio.Event()

    def signal_handler():
        stop_event.set()

    import signal
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    await stop_event.wait()

    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    print("\n🛑 Telegram bridge stopped")


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

    asyncio.run(run_bot(config))


if __name__ == "__main__":
    main()
