#!/usr/bin/env python3
"""telegram-bridge.py — Thin Telegram ↔ Voronoi I/O layer.

All business logic lives in ``voronoi.gateway.router``.  This script is
purely responsible for:

1. Setting up python-telegram-bot handlers
2. Routing incoming messages to ``CommandRouter``
3. Sending replies (text **and** file attachments) back to Telegram
4. Scheduling periodic dispatcher jobs (dispatch_next + poll_progress)

Usage:
    python3 scripts/telegram-bridge.py [--config .swarm-config.json]

Requirements:
    pip install 'python-telegram-bot[job-queue]'
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure src/ is importable when running from the repo checkout
_src_dir = Path(__file__).resolve().parent.parent / "src"
if _src_dir.is_dir() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from voronoi.gateway.config import load_config, save_chat_id  # noqa: E402
from voronoi.gateway.router import CommandRouter  # noqa: E402


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

def run_bot(config: dict) -> None:
    """Build and start the Telegram bot."""
    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
    except ImportError:
        print("python-telegram-bot not installed. Run: pip install 'python-telegram-bot[job-queue]'", file=sys.stderr)
        sys.exit(1)

    bot_token = config["bot_token"]
    user_allowlist = config.get("user_allowlist", [])
    project_dir = config["project_dir"]

    if not bot_token:
        print("No bot_token configured", file=sys.stderr)
        sys.exit(1)

    router = CommandRouter(project_dir)
    _bot_username: list[str | None] = [None]

    # -- helpers -----------------------------------------------------------

    def _is_allowed(update: Update) -> bool:
        if not user_allowlist:
            return True
        user = update.effective_user
        if user is None:
            return False
        uid = str(user.id).lower()
        uname = (user.username or "").lower()
        return uid in user_allowlist or uname in user_allowlist

    def _is_group_directed(update: Update) -> bool:
        msg = update.message
        if msg is None:
            return False
        if msg.reply_to_message and msg.reply_to_message.from_user:
            if msg.reply_to_message.from_user.is_bot and _bot_username[0]:
                if msg.reply_to_message.from_user.username == _bot_username[0]:
                    return True
        text = msg.text or ""
        if _bot_username[0] and f"@{_bot_username[0]}" in text:
            return True
        return False

    async def _reply(update: Update, text: str, file_path: Path | None = None) -> None:
        """Send a text reply, optionally followed by a document."""
        try:
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(text)
        if file_path and file_path.exists():
            try:
                with open(file_path, "rb") as f:
                    await update.message.reply_document(f, filename=file_path.name)
            except Exception:
                pass  # document send is best-effort

    # -- handlers ----------------------------------------------------------

    async def cmd_voronoi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update):
            if update.message:
                await update.message.reply_text("You are not authorized to use this bot.")
            return

        if update.message and update.message.chat_id:
            save_chat_id(project_dir, update.message.chat_id)

        args = context.args or []
        subcommand = args[0].lower() if args else ""
        sub_args = args[1:] if len(args) > 1 else []
        chat_id = str(update.message.chat_id) if update.message else "unknown"

        reply_text, reply_file = router.route(subcommand, sub_args, chat_id)
        await _reply(update, reply_text, reply_file)

    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update) or update.message is None:
            return

        text = (update.message.text or "").strip()
        if not text:
            return

        chat_id = str(update.message.chat_id)
        is_private = update.message.chat.type == "private"
        is_group = update.message.chat.type in ("group", "supergroup")

        if is_group and not _is_group_directed(update):
            return

        save_chat_id(project_dir, update.message.chat_id)

        # Strip @botname from text
        if _bot_username[0]:
            text = text.replace(f"@{_bot_username[0]}", "").strip()

        reply_text, reply_file = router.handle_free_text(text, chat_id, is_private)
        await _reply(update, reply_text, reply_file)

    # -- application -------------------------------------------------------

    app = Application.builder().token(bot_token).build()

    async def _post_init(application: Application) -> None:
        me = await application.bot.get_me()
        _bot_username[0] = me.username
        print(f"   Bot username: @{me.username}")

    app.post_init = _post_init
    app.add_handler(CommandHandler("voronoi", cmd_voronoi))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # -- dispatcher jobs ----------------------------------------------------

    _dispatcher_instance: list = [None]

    def _get_dispatcher():
        if _dispatcher_instance[0] is not None:
            return _dispatcher_instance[0]
        try:
            from voronoi.server.dispatcher import InvestigationDispatcher, DispatcherConfig
            from voronoi.server.runner import ServerConfig

            sc = ServerConfig()
            dc = DispatcherConfig(
                base_dir=sc.base_dir,
                max_concurrent=sc.max_concurrent,
                max_agents=sc.max_agents_per_investigation,
                agent_command=sc.agent_command,
                agent_flags=sc.agent_flags,
            )

            chat_id_file = Path(project_dir) / ".telegram-chat-id"

            def _send(text: str) -> None:
                if not chat_id_file.exists():
                    return
                cid = chat_id_file.read_text().strip()
                if not cid:
                    return
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(_async_send(cid, text))
                    else:
                        loop.run_until_complete(_async_send(cid, text))
                except Exception:
                    pass

            async def _async_send(cid: str, text: str) -> None:
                try:
                    await app.bot.send_message(chat_id=cid, text=text, parse_mode="Markdown", disable_web_page_preview=True)
                except Exception:
                    try:
                        await app.bot.send_message(chat_id=cid, text=text, disable_web_page_preview=True)
                    except Exception:
                        pass

            def _send_document(cid: str, file_path: Path, caption: str = "") -> None:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(_async_send_doc(cid, file_path, caption))
                except Exception:
                    pass

            async def _async_send_doc(cid: str, file_path: Path, caption: str) -> None:
                try:
                    with open(file_path, "rb") as f:
                        await app.bot.send_document(chat_id=cid, document=f, filename=file_path.name, caption=caption)
                except Exception:
                    pass

            _dispatcher_instance[0] = InvestigationDispatcher(dc, _send, _send_document)
            print("   ✓ Investigation dispatcher initialized")
        except Exception as e:
            print(f"   ⚠ Dispatcher not available: {e}")
        return _dispatcher_instance[0]

    async def _job_dispatch(context: ContextTypes.DEFAULT_TYPE) -> None:
        d = _get_dispatcher()
        if d:
            try:
                d.dispatch_next()
            except Exception as e:
                print(f"Dispatch error: {e}")

    async def _job_progress(context: ContextTypes.DEFAULT_TYPE) -> None:
        d = _get_dispatcher()
        if d:
            try:
                d.poll_progress()
            except Exception as e:
                print(f"Progress poll error: {e}")

    if app.job_queue is not None:
        app.job_queue.run_repeating(_job_dispatch, interval=10, first=5)
        app.job_queue.run_repeating(_job_progress, interval=30, first=15)
    else:
        print("⚠️  JobQueue not available — install 'python-telegram-bot[job-queue]'")

    # -- start -------------------------------------------------------------

    allowlist_str = ", ".join(user_allowlist) if user_allowlist else "any"
    print(f"🤖 Telegram bridge started for {config['project_name']}")
    print(f"   Allowed users: {allowlist_str}")
    print(f"   Project: {project_dir}")
    print(f"   Dispatcher: polling every 10s (dispatch) / 30s (progress)")
    app.run_polling(drop_pending_updates=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Voronoi ↔ Telegram bridge")
    parser.add_argument("--config", default=".swarm-config.json", help="Path to .swarm-config.json")
    args = parser.parse_args()

    config = load_config(args.config)

    if not config["bot_token"]:
        print("Error: No Telegram bot token configured", file=sys.stderr)
        print("Set VORONOI_TG_BOT_TOKEN or add to .swarm-config.json", file=sys.stderr)
        sys.exit(1)

    run_bot(config)


if __name__ == "__main__":
    main()
