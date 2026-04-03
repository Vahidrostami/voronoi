"""TMux session management for investigation agents.

Standalone functions extracted from InvestigationDispatcher.
Each function accepts explicit parameters instead of ``self``.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("voronoi.dispatcher")


def ensure_copilot_auth() -> None:
    """Verify Copilot/GitHub auth is valid before launching an agent.

    Raises RuntimeError if authentication is missing or expired.
    """
    for var in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            logger.debug("Auth: using %s environment variable", var)
            return

    if shutil.which("gh"):
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return

    raise RuntimeError(
        "GitHub/Copilot authentication expired. "
        "Re-authenticate on the server with 'copilot' → /login or 'gh auth login', "
        "or set GITHUB_TOKEN / COPILOT_GITHUB_TOKEN env var with a PAT for unattended use."
    )


# Rigor → Copilot CLI --effort mapping
EFFORT_BY_RIGOR: dict[str, str] = {
    "adaptive": "high",
    "scientific": "high",
    "experimental": "xhigh",
}


def launch_in_tmux(
    session: str,
    workspace_path: Path,
    agent_command: str,
    agent_flags: str,
    orchestrator_model: str = "",
    prompt_file: Path | None = None,
    rigor: str = "",
) -> None:
    """Launch an agent CLI inside a new tmux session.

    Parameters
    ----------
    session : str
        tmux session name (e.g. ``voronoi-inv-42``).
    workspace_path : Path
        Investigation workspace root.
    agent_command : str
        Agent CLI binary (e.g. ``copilot``).
    agent_flags : str
        Extra CLI flags (e.g. ``--allow-all``).
    orchestrator_model : str
        Model override for the orchestrator (``""`` = default).
    prompt_file : Path | None
        Prompt file to read. Defaults to
        ``<workspace>/.swarm/orchestrator-prompt.txt``.
    rigor : str
        Rigor level for effort mapping.
    """
    parts = agent_command.split()
    if not parts:
        raise RuntimeError(f"agent_command is empty: '{agent_command}'")
    agent_bin = parts[0]
    if not shutil.which(agent_bin):
        raise RuntimeError(f"Agent CLI not found: {agent_bin}")
    if agent_bin == "copilot":
        ensure_copilot_auth()

    model_flag = ""
    if orchestrator_model:
        model_flag = f" --model {shlex.quote(orchestrator_model)}"

    effort = EFFORT_BY_RIGOR.get(rigor, "medium")
    effort_flag = f" --effort {effort}"

    share_path = workspace_path / ".swarm" / "session.md"
    share_flag = f" --share {shlex.quote(str(share_path))}"

    log_path = workspace_path / ".swarm" / "agent.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if prompt_file is None:
        prompt_file = workspace_path / ".swarm" / "orchestrator-prompt.txt"

    # Kill stale session
    subprocess.run(
        ["tmux", "kill-session", "-t", session],
        capture_output=True, timeout=10,
    )

    result = subprocess.run(
        ["tmux", "new-session", "-d", "-s", session, "-c", str(workspace_path)],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create tmux session '{session}': "
            f"{result.stderr.decode(errors='replace').strip()}"
        )

    subprocess.run(
        ["tmux", "pipe-pane", "-t", session,
         f"cat >> {shlex.quote(str(log_path))}"],
        capture_output=True, timeout=10,
    )

    safe_ws = shlex.quote(str(workspace_path))
    safe_prompt = shlex.quote(str(prompt_file))

    # Inject auth/state env vars
    env_file = workspace_path / ".swarm" / ".tmux-env"
    env_lines: list[str] = []
    for var in (
        "GH_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN",
        "COPILOT_HOME", "GH_HOST", "TMPDIR", "TMP", "TEMP",
    ):
        val = os.environ.get(var)
        if val:
            env_lines.append(f"export {var}={shlex.quote(val)}")
            subprocess.run(
                ["tmux", "set-environment", "-t", session, var, val],
                capture_output=True, timeout=10,
            )
    if env_lines:
        fd = os.open(str(env_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, ("\n".join(env_lines) + "\n").encode())
        finally:
            os.close(fd)
        source_cmd = f"source {shlex.quote(str(env_file))} && "
    else:
        source_cmd = ""

    subprocess.run(
        ["tmux", "send-keys", "-t", session,
         f'cd {safe_ws} && {source_cmd}{agent_command} {agent_flags}{model_flag}'
         f'{effort_flag}{share_flag} '
         f'-p "$(cat {safe_prompt})" ; exit',
         "Enter"],
        capture_output=True, timeout=10,
    )


def cleanup_tmux(
    tmux_session: str,
    workspace_path: Path,
) -> None:
    """Kill all tmux sessions associated with an investigation.

    Uses multiple strategies to find sessions:
    1. The recorded tmux_session name
    2. Convention-based names ({workspace}-swarm, -workers)
    3. The tmux_session from .swarm-config.json
    4. Enumerate sessions and kill any whose pane cwd is inside the swarm dir
    """
    ws_name = workspace_path.name
    sessions_to_kill: set[str] = set()

    sessions_to_kill.add(tmux_session)

    for suffix in ["-swarm", "-workers"]:
        sessions_to_kill.add(f"{ws_name}{suffix}")

    config_path = workspace_path / ".swarm-config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            cfg_session = data.get("tmux_session", "")
            if cfg_session:
                sessions_to_kill.add(cfg_session)
        except (json.JSONDecodeError, OSError):
            pass

    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            slug_prefix = ws_name.split("-swarm")[0]
            for session_name in result.stdout.strip().splitlines():
                name = session_name.strip()
                if not name or name.isdigit():
                    continue
                if name in sessions_to_kill:
                    continue
                swarm_dir = workspace_path.parent / f"{slug_prefix}-swarm"
                if swarm_dir.exists():
                    try:
                        cwd_result = subprocess.run(
                            ["tmux", "display-message", "-t", name,
                             "-p", "#{pane_current_path}"],
                            capture_output=True, text=True, timeout=5,
                        )
                        if cwd_result.returncode == 0:
                            pane_cwd = cwd_result.stdout.strip()
                            if pane_cwd.startswith(str(swarm_dir)):
                                sessions_to_kill.add(name)
                    except (subprocess.TimeoutExpired, OSError):
                        pass
    except (subprocess.TimeoutExpired, OSError):
        pass

    for session in sessions_to_kill:
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", session],
                capture_output=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

    logger.info("Cleaned up tmux sessions for %s (killed %d)",
                workspace_path.name, len(sessions_to_kill))
