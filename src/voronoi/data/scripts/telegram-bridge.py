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
import logging.handlers
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Coroutine, TypeVar

logger = logging.getLogger("voronoi.bridge")

# Ensure src/ is importable when running from the repo checkout
_src_dir = Path(__file__).resolve().parent.parent / "src"
if _src_dir.is_dir() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from voronoi.gateway.config import load_config, save_chat_id  # noqa: E402
from voronoi.gateway.router import CommandRouter  # noqa: E402


_T = TypeVar("_T")


def _run_coro_threadsafe(
    loop: asyncio.AbstractEventLoop,
    coro: Coroutine[Any, Any, _T],
    *,
    timeout: float | None = None,
) -> _T | None:
    """Schedule a coroutine on the Telegram loop from any thread."""
    try:
        future = asyncio.run_coroutine_threadsafe(coro, loop)
    except Exception:
        coro.close()
        raise

    if timeout is None:
        return None

    return future.result(timeout=timeout)


def format_human_gate_command_reply(action: str, args: list[str], dispatcher) -> str:
    """Validate and route /approve and /revise commands."""
    verb = action.lower()
    if verb not in {"approve", "revise"}:
        return f"Unknown human-gate action: {action}"
    if not args:
        usage = "/approve <investigation-id>" if verb == "approve" else "/revise <investigation-id> <feedback>"
        return f"Usage: {usage}"
    try:
        investigation_id = int(args[0])
    except (TypeError, ValueError):
        return f"❌ Invalid investigation ID: {args[0]}"

    if dispatcher is None:
        return "❌ Dispatcher unavailable. Human-gate actions need the server dispatcher running."

    feedback = " ".join(args[1:]).strip()
    if verb == "revise" and not feedback:
        return "Usage: /revise <investigation-id> <feedback>"

    if verb == "approve":
        ok = dispatcher.approve_human_gate(investigation_id, feedback)
        return (
            f"✅ Approved human gate for investigation #{investigation_id}."
            if ok else
            f"❌ No pending human gate found for investigation #{investigation_id}."
        )

    ok = dispatcher.revise_human_gate(investigation_id, feedback)
    return (
        f"🔄 Requested revision for investigation #{investigation_id}."
        if ok else
        f"❌ No pending human gate found for investigation #{investigation_id}."
    )


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

    async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update):
            user = update.effective_user
            logger.warning("Unauthorized /approve from user=%s", user.id if user else "?")
            if update.message:
                await update.message.reply_text("You are not authorized to use this bot.")
            return
        if update.message and update.message.chat_id:
            save_chat_id(project_dir, update.message.chat_id)
        reply_text = format_human_gate_command_reply(
            "approve", context.args or [], _get_dispatcher()
        )
        await _reply(update, reply_text)

    async def cmd_revise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update):
            user = update.effective_user
            logger.warning("Unauthorized /revise from user=%s", user.id if user else "?")
            if update.message:
                await update.message.reply_text("You are not authorized to use this bot.")
            return
        if update.message and update.message.chat_id:
            save_chat_id(project_dir, update.message.chat_id)
        reply_text = format_human_gate_command_reply(
            "revise", context.args or [], _get_dispatcher()
        )
        await _reply(update, reply_text)

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
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("revise", cmd_revise))
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
        elif data == "progress":
            reply_text, _ = router.route("progress", [], chat_id)
        elif data == "details":
            reply_text, _ = router.route("details", [], chat_id)
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
                context_advisory_hours=sc.context_advisory_hours,
                context_warning_hours=sc.context_warning_hours,
                context_critical_hours=sc.context_critical_hours,
                compact_interval_hours=sc.compact_interval_hours,
            )

            chat_id_file = Path(project_dir) / ".telegram-chat-id"
            # Capture the main thread's event loop now so callbacks
            # running in executor threads can schedule coroutines safely.
            _main_loop = asyncio.get_running_loop()

            # ── Message ID tracking for edit-in-place ──
            # Stores the returned Telegram message_id from send_message()
            # so the dispatcher can pass it back via edit_message().
            _last_sent_msg_id: dict[str, int | None] = {"value": None}

            def _send(text: str) -> int | None:
                """Send a new Telegram message. Returns the message_id."""
                if not chat_id_file.exists():
                    return None
                cid = chat_id_file.read_text().strip()
                if not cid:
                    return None
                try:
                    msg_id = _run_coro_threadsafe(
                        _main_loop,
                        _async_send(cid, text),
                        timeout=10.0,
                    )
                except Exception:
                    logger.debug("Failed to schedule message send", exc_info=True)
                    return _last_sent_msg_id.get("value")
                _last_sent_msg_id["value"] = msg_id
                return msg_id

            def _edit(text: str, message_id: int) -> None:
                """Edit an existing Telegram message (silent, no notification)."""
                if not chat_id_file.exists():
                    return
                cid = chat_id_file.read_text().strip()
                if not cid:
                    return
                try:
                    _run_coro_threadsafe(_main_loop, _async_edit(cid, text, message_id))
                except Exception:
                    logger.debug("Failed to schedule message edit", exc_info=True)

            async def _async_send(cid: str, text: str) -> int | None:
                # Typing indicator before milestone messages
                is_milestone = any(marker in text for marker in ("★ ", "⚠ ", "is done", "failed"))
                if is_milestone:
                    try:
                        await app.bot.send_chat_action(chat_id=cid, action="typing")
                        await asyncio.sleep(1.0)
                    except Exception:
                        pass

                # Select inline buttons based on content
                reply_markup = None
                try:
                    if "is live" in text.lower():
                        reply_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📊 Status", callback_data="status"),
                             InlineKeyboardButton("🛑 Abort", callback_data="abort")],
                        ])
                    elif "★ " in text:
                        # Finding milestone
                        reply_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📋 Details", callback_data="details"),
                             InlineKeyboardButton("🧠 Belief Map", callback_data="belief")],
                        ])
                    elif any(k in text for k in ("tasks", "Phase ", "agents active", "criteria")):
                        # Status/digest update
                        reply_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📋 Details", callback_data="details"),
                             InlineKeyboardButton("💬 Guide", callback_data="guide_prompt"),
                             InlineKeyboardButton("🛑 Abort", callback_data="abort")],
                        ])
                    elif "is done" in text.lower():
                        reply_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📋 Details", callback_data="details"),
                             InlineKeyboardButton("🧠 Belief Map", callback_data="belief")],
                        ])
                    elif "failed" in text.lower():
                        reply_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📋 Details", callback_data="details"),
                             InlineKeyboardButton("🛑 Abort", callback_data="abort")],
                        ])
                except Exception:
                    pass  # buttons are best-effort

                msg_id = None
                try:
                    result = await app.bot.send_message(
                        chat_id=cid, text=text, parse_mode="Markdown",
                        disable_web_page_preview=True, reply_markup=reply_markup,
                        disable_notification=not is_milestone,
                    )
                    msg_id = result.message_id if result else None
                except Exception:
                    try:
                        result = await app.bot.send_message(
                            chat_id=cid, text=text,
                            disable_web_page_preview=True, reply_markup=reply_markup,
                        )
                        msg_id = result.message_id if result else None
                    except Exception:
                        pass

                return msg_id

            async def _async_edit(cid: str, text: str, message_id: int) -> None:
                """Edit an existing message — used for silent status updates."""
                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Details", callback_data="details"),
                     InlineKeyboardButton("💬 Guide", callback_data="guide_prompt"),
                     InlineKeyboardButton("🛑 Abort", callback_data="abort")],
                ])
                try:
                    await app.bot.edit_message_text(
                        chat_id=cid, message_id=message_id, text=text,
                        parse_mode="Markdown", disable_web_page_preview=True,
                        reply_markup=reply_markup,
                    )
                except Exception:
                    try:
                        await app.bot.edit_message_text(
                            chat_id=cid, message_id=message_id, text=text,
                            disable_web_page_preview=True, reply_markup=reply_markup,
                        )
                    except Exception:
                        pass  # edit failed — next poll will send a fresh message

            def _send_document(cid: str, file_path: Path, caption: str = "") -> None:
                try:
                    _run_coro_threadsafe(_main_loop, _async_send_doc(cid, file_path, caption))
                except Exception:
                    logger.debug("Failed to schedule document send", exc_info=True)

            async def _async_send_doc(cid: str, file_path: Path, caption: str) -> None:
                try:
                    with open(file_path, "rb") as f:
                        await app.bot.send_document(chat_id=cid, document=f, filename=file_path.name, caption=caption)
                except Exception:
                    pass

            _dispatcher_instance[0] = InvestigationDispatcher(dc, _send, _send_document, _edit)
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


def _is_fatal_bridge_error(exc: BaseException) -> bool:
    """Return True when restart loops would just mask a configuration error."""
    return exc.__class__.__name__ in {"InvalidToken", "Unauthorized"}


def run_bot_forever(config: dict, restart_delay: int = 5, max_delay: int = 60) -> None:
    """Keep the Telegram bridge alive across transient failures."""
    delay = max(1, restart_delay)
    ceiling = max(delay, max_delay)

    while True:
        try:
            run_bot(config)
            return
        except KeyboardInterrupt:
            logger.info("Telegram bridge stopped.")
            return
        except SystemExit:
            raise
        except Exception as exc:
            if _is_fatal_bridge_error(exc):
                logger.error("Fatal Telegram bridge error: %s", exc, exc_info=True)
                raise
            logger.error("Telegram bridge crashed: %s", exc, exc_info=True)
            logger.info("Restarting Telegram bridge in %ss", delay)
            time.sleep(delay)
            delay = min(delay * 2, ceiling)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Voronoi ↔ Telegram bridge")
    parser.add_argument("--config", default=".swarm-config.json", help="Path to .swarm-config.json")
    args = parser.parse_args()
    log_level = os.environ.get("VORONOI_LOG_LEVEL", "INFO").upper()
    log_fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (existing behaviour)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(log_fmt)

    # Rotating file handler: 3 × 5 MB = 15 MB max on disk
    log_dir = Path(os.environ.get("VORONOI_LOG_DIR", Path.home() / ".voronoi"))
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "bridge.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    file_handler.setFormatter(log_fmt)

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))
    root.addHandler(console)
    root.addHandler(file_handler)

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

    restart_delay = int(os.environ.get("VORONOI_BRIDGE_RESTART_DELAY_SECONDS", "5"))
    max_delay = int(os.environ.get("VORONOI_BRIDGE_MAX_RESTART_DELAY_SECONDS", "60"))
    run_bot_forever(config, restart_delay=restart_delay, max_delay=max_delay)


if __name__ == "__main__":
    main()
