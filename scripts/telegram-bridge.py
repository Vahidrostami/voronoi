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
import logging
import socket
import sys
from pathlib import Path

logger = logging.getLogger("voronoi.bridge")

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
        from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
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

    async def _reply(update: Update, text: str, file_path: Path | None = None,
                     buttons: list[list[tuple[str, str]]] | None = None) -> None:
        """Send a text reply, optionally with inline buttons and/or a document."""
        reply_markup = None
        if buttons:
            keyboard = [
                [InlineKeyboardButton(label, callback_data=data) for label, data in row]
                for row in buttons
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        except Exception:
            await update.message.reply_text(text, reply_markup=reply_markup)
        if file_path and file_path.exists():
            try:
                with open(file_path, "rb") as f:
                    await update.message.reply_document(f, filename=file_path.name)
            except Exception:
                pass  # document send is best-effort

    # -- handlers ----------------------------------------------------------

    async def cmd_voronoi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update):
            user = update.effective_user
            logger.warning("Unauthorized /voronoi from user=%s", user.id if user else "?")
            if update.message:
                await update.message.reply_text("You are not authorized to use this bot.")
            return

        if update.message and update.message.chat_id:
            save_chat_id(project_dir, update.message.chat_id)

        args = context.args or []
        subcommand = args[0].lower() if args else ""
        sub_args = args[1:] if len(args) > 1 else []
        chat_id = str(update.message.chat_id) if update.message else "unknown"

        logger.info("CMD /voronoi %s %s (chat=%s)", subcommand, " ".join(sub_args), chat_id)
        reply_text, reply_file = router.route(subcommand, sub_args, chat_id)
        logger.debug("Reply: %s", reply_text[:120])

        # Contextual inline buttons for command responses
        buttons = None
        if subcommand in ("investigate", "explore", "build", "experiment") and sub_args:
            buttons = [[("📊 Status", "status"), ("🛑 Abort", "abort")]]
        elif subcommand == "status":
            buttons = [[("📋 Tasks", "tasks"), ("⚡ Ready", "status"), ("🩺 Health", "health")]]

        await _reply(update, reply_text, reply_file, buttons=buttons)

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

        logger.info("MSG from chat=%s: %.80s", chat_id, text)
        reply_text, reply_file = router.handle_free_text(text, chat_id, is_private)
        logger.debug("Reply: %s", reply_text[:120])
        await _reply(update, reply_text, reply_file)

    # -- application -------------------------------------------------------

    app = Application.builder().token(bot_token).build()

    async def _post_init(application: Application) -> None:
        # Clear any stale polling sessions from a previous unclean shutdown.
        await application.bot.delete_webhook(drop_pending_updates=True)
        me = await application.bot.get_me()
        _bot_username[0] = me.username
        logger.info("Bot username: @%s", me.username)

    app.post_init = _post_init
    app.add_handler(CommandHandler("voronoi", cmd_voronoi))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # -- inline button callback handler ------------------------------------

    async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline keyboard button presses."""
        query = update.callback_query
        if query is None:
            return
        try:
            await query.answer()
        except Exception:
            pass  # query expired — still process the button action
        data = query.data or ""
        chat_id = str(query.message.chat_id) if query.message else "unknown"

        # Route button presses through the same command router
        if data == "status":
            reply_text, _ = router.route("status", [], chat_id)
        elif data == "health":
            reply_text, _ = router.route("health", [], chat_id)
        elif data == "tasks":
            reply_text, _ = router.route("tasks", [], chat_id)
        elif data == "abort":
            reply_text, _ = router.route("abort", [], chat_id)
        elif data == "belief":
            reply_text, _ = router.route("belief", [], chat_id)
        elif data.startswith("results_"):
            inv_id = data.split("_", 1)[1]
            reply_text, _ = router.route("results", [inv_id], chat_id)
        elif data == "guide_prompt":
            reply_text = "_Send a message and I'll record it as guidance for the agents._"
        else:
            reply_text = f"Unknown action: {data}"

        try:
            await query.message.reply_text(reply_text, parse_mode="Markdown")
        except Exception:
            await query.message.reply_text(reply_text)

    app.add_handler(CallbackQueryHandler(handle_callback))

    # -- error handler -----------------------------------------------------

    async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log errors from the telegram bot without crashing."""
        logger.error("Telegram error: %s", context.error, exc_info=context.error)

    app.add_error_handler(_error_handler)

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
                orchestrator_model=sc.orchestrator_model,
                worker_model=sc.worker_model,
            )

            chat_id_file = Path(project_dir) / ".telegram-chat-id"
            # Capture the main thread's event loop now so callbacks
            # running in executor threads can schedule coroutines safely.
            _main_loop = asyncio.get_event_loop()

            def _send(text: str) -> None:
                if not chat_id_file.exists():
                    return
                cid = chat_id_file.read_text().strip()
                if not cid:
                    return
                try:
                    _main_loop.call_soon_threadsafe(
                        asyncio.ensure_future, _async_send(cid, text)
                    )
                except Exception:
                    logger.debug("Failed to schedule message send", exc_info=True)

            async def _async_send(cid: str, text: str) -> None:
                # Add contextual inline buttons based on message content
                reply_markup = None
                try:
                    if "is LIVE" in text:
                        reply_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📊 Status", callback_data="status"),
                             InlineKeyboardButton("🛑 Abort", callback_data="abort")],
                        ])
                    elif "📡" in text:  # progress update
                        reply_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📋 Tasks", callback_data="tasks"),
                             InlineKeyboardButton("📝 Guide", callback_data="guide_prompt"),
                             InlineKeyboardButton("🛑 Abort", callback_data="abort")],
                        ])
                    elif "COMPLETE" in text:
                        reply_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📊 Findings", callback_data="status"),
                             InlineKeyboardButton("🧠 Belief Map", callback_data="belief")],
                        ])
                except Exception:
                    pass  # buttons are best-effort

                try:
                    await app.bot.send_message(chat_id=cid, text=text, parse_mode="Markdown",
                                               disable_web_page_preview=True, reply_markup=reply_markup)
                except Exception:
                    try:
                        await app.bot.send_message(chat_id=cid, text=text,
                                                   disable_web_page_preview=True, reply_markup=reply_markup)
                    except Exception:
                        pass

            def _send_document(cid: str, file_path: Path, caption: str = "") -> None:
                try:
                    _main_loop.call_soon_threadsafe(
                        asyncio.ensure_future, _async_send_doc(cid, file_path, caption)
                    )
                except Exception:
                    logger.debug("Failed to schedule document send", exc_info=True)

            async def _async_send_doc(cid: str, file_path: Path, caption: str) -> None:
                try:
                    with open(file_path, "rb") as f:
                        await app.bot.send_document(chat_id=cid, document=f, filename=file_path.name, caption=caption)
                except Exception:
                    pass

            _dispatcher_instance[0] = InvestigationDispatcher(dc, _send, _send_document)
            logger.info("Investigation dispatcher initialized")
        except Exception as e:
            logger.warning("Dispatcher not available: %s", e)
        return _dispatcher_instance[0]

    async def _job_dispatch(context: ContextTypes.DEFAULT_TYPE) -> None:
        d = _get_dispatcher()
        if d:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, d.dispatch_next)
            except Exception as e:
                logger.error("Dispatch error: %s", e, exc_info=True)

    async def _job_progress(context: ContextTypes.DEFAULT_TYPE) -> None:
        d = _get_dispatcher()
        if d:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, d.poll_progress)
            except Exception as e:
                logger.error("Progress poll error: %s", e, exc_info=True)

    if app.job_queue is not None:
        app.job_queue.run_repeating(_job_dispatch, interval=10, first=5)
        app.job_queue.run_repeating(_job_progress, interval=30, first=15)
    else:
        logger.warning("JobQueue not available — install 'python-telegram-bot[job-queue]'")

    # -- start -------------------------------------------------------------

    allowlist_str = ", ".join(user_allowlist) if user_allowlist else "any"
    logger.info("Telegram bridge started for %s", config['project_name'])
    logger.info("  Allowed users: %s", allowlist_str)
    logger.info("  Project: %s", project_dir)
    logger.info("  Dispatcher: polling every 10s (dispatch) / 30s (progress)")
    app.run_polling(drop_pending_updates=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Voronoi ↔ Telegram bridge")
    parser.add_argument("--config", default=".swarm-config.json", help="Path to .swarm-config.json")
    args = parser.parse_args()
    import os
    log_level = os.environ.get("VORONOI_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Keep noisy libs at WARNING
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    config = load_config(args.config)

    if not config["bot_token"]:
        print("Error: No Telegram bot token configured", file=sys.stderr)
        print("Set VORONOI_TG_BOT_TOKEN or add to .swarm-config.json", file=sys.stderr)
        sys.exit(1)

    # Prevent two instances from polling the same bot token simultaneously.
    # Use a TCP socket bound to a localhost port (derived from the token hash)
    # as a singleton lock.  This is OS-enforced, works on NFS, and auto-releases
    # when the process exits — no stale lock files to clean up.
    import hashlib
    token_hash = hashlib.sha256(config["bot_token"].encode()).hexdigest()[:12]
    lock_port = 49152 + int(token_hash, 16) % 16384  # ephemeral range
    _lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock_sock.bind(("127.0.0.1", lock_port))
    except OSError:
        print("Error: Another telegram-bridge instance is already running "
              f"for this bot token (lock port: {lock_port})", file=sys.stderr)
        sys.exit(1)

    run_bot(config)


if __name__ == "__main__":
    main()
