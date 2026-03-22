"""Configuration management for Voronoi.

Loads settings from .env files and .swarm-config.json, shared by
the Telegram bridge, CLI, and any future UI.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("voronoi.config")


def load_dotenv(env_path: Path | None = None) -> None:
    """Load .env file into os.environ (only sets vars not already set)."""
    if env_path is None:
        for candidate in [Path.cwd() / ".env", Path(__file__).parent.parent.parent.parent / ".env"]:
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
            if line.startswith("export "):
                line = line[7:]
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Strip surrounding quotes
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                else:
                    if "  #" in value:
                        value = value[: value.index("  #")].strip()
                    elif "\t#" in value:
                        value = value[: value.index("\t#")].strip()
                if key not in os.environ:
                    os.environ[key] = value


def load_config(config_path: str = ".swarm-config.json") -> dict:
    """Load config from .env files and optionally .swarm-config.json."""
    load_dotenv()
    load_dotenv(Path.home() / ".voronoi" / ".env")

    path = Path(config_path)
    if not path.exists():
        path = Path(__file__).parent.parent.parent.parent / config_path
    if not path.exists():
        path = Path.home() / ".voronoi" / ".swarm-config.json"

    config: dict = {}
    tg: dict = {}
    if path.exists():
        try:
            with open(path) as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to parse config %s: %s — using defaults", path, exc)
        tg = config.get("notifications", {}).get("telegram", {})

    raw_allowlist = os.environ.get(
        "VORONOI_TG_USER_ALLOWLIST", tg.get("user_allowlist", "")
    )
    user_allowlist = (
        [u.strip().lower() for u in raw_allowlist.split(",") if u.strip()]
        if raw_allowlist
        else []
    )

    return {
        "bot_token": os.environ.get("VORONOI_TG_BOT_TOKEN", tg.get("bot_token", "")),
        "user_allowlist": user_allowlist,
        "bridge_enabled": tg.get("bridge_enabled", True),
        "project_dir": config.get("project_dir", os.getcwd()),
        "project_name": config.get("project_name", "voronoi"),
        "swarm_dir": config.get("swarm_dir", ""),
        "agent_command": os.environ.get(
            "VORONOI_AGENT_COMMAND",
            config.get("agent_command", "copilot"),
        ),
        "orchestrator_model": os.environ.get(
            "VORONOI_ORCHESTRATOR_MODEL",
            config.get("orchestrator_model", ""),
        ),
        "worker_model": os.environ.get(
            "VORONOI_WORKER_MODEL",
            config.get("worker_model", ""),
        ),
        "gh_token": os.environ.get("GH_TOKEN", ""),
    }


def save_chat_id(project_dir: str, chat_id: int | str) -> None:
    """Persist the active Telegram chat ID for outbound notifications."""
    chat_file = Path(project_dir) / ".telegram-chat-id"
    try:
        chat_file.parent.mkdir(parents=True, exist_ok=True)
        chat_file.write_text(str(chat_id).strip() + "\n")
    except OSError:
        pass


def get_chat_id(project_dir: str) -> str | None:
    """Read the saved chat ID, or None."""
    chat_file = Path(project_dir) / ".telegram-chat-id"
    if not chat_file.exists():
        return None
    try:
        return chat_file.read_text().strip() or None
    except OSError:
        return None
