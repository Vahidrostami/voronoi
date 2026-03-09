"""Beads (bd) subprocess helpers — single source of truth.

Every module that calls ``bd`` should import from here instead of
duplicating subprocess boilerplate.
"""

from __future__ import annotations

import os
import subprocess


def run_bd(*args: str, cwd: str | None = None) -> tuple[int, str]:
    """Run a bd (beads) command.

    Returns (exit_code, stdout).  Stderr is discarded so that
    JSON-producing commands (``bd list --json``) can be parsed safely.
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
        return result.returncode, result.stdout.strip()
    except FileNotFoundError:
        return 1, ""
    except subprocess.TimeoutExpired:
        return 1, ""


def has_beads_dir(cwd: str | None) -> bool:
    """Return True if *cwd* has a ``.beads/`` directory or ``BEADS_DIR`` is set."""
    if "BEADS_DIR" in os.environ:
        return True
    if cwd:
        return os.path.isdir(os.path.join(cwd, ".beads"))
    return False


def run_cmd(cmd: list[str], cwd: str | None = None,
            timeout: int = 30) -> tuple[int, str]:
    """Run an arbitrary command with ``BEADS_DIR`` set if applicable.

    Returns (exit_code, combined_output).
    """
    env = os.environ.copy()
    if cwd and "BEADS_DIR" not in env:
        beads_dir = os.path.join(cwd, ".beads")
        if os.path.isdir(beads_dir):
            env["BEADS_DIR"] = beads_dir
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=cwd, env=env,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return 1, f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 1, "Command timed out"
