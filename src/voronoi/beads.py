"""Beads (bd) subprocess helpers — single source of truth.

Every module that calls ``bd`` should import from here instead of
duplicating subprocess boilerplate.
"""

from __future__ import annotations

import logging
import os
import subprocess

logger = logging.getLogger("voronoi.beads")


class BeadsError(Exception):
    """Raised when a bd command fails and the caller requested strict mode."""


def run_bd(*args: str, cwd: str | None = None,
           strict: bool = False) -> tuple[int, str]:
    """Run a bd (beads) command.

    Returns (exit_code, stdout).  Stderr is logged at DEBUG level so that
    JSON-producing commands (``bd list --json``) can be parsed safely,
    but failures are no longer silently lost.

    If *strict* is True, raises ``BeadsError`` on non-zero exit code.
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
        if result.stderr:
            logger.debug("bd %s stderr: %s", " ".join(args), result.stderr.strip())
        if result.returncode != 0:
            logger.warning("bd %s exited with code %d (stderr: %s)",
                           " ".join(args), result.returncode,
                           result.stderr.strip()[:200])
            if strict:
                raise BeadsError(
                    f"bd {' '.join(args)} failed (exit={result.returncode}): "
                    f"{result.stderr.strip()[:200]}"
                )
        return result.returncode, result.stdout.strip()
    except FileNotFoundError:
        logger.error("bd command not found — is beads installed?")
        if strict:
            raise BeadsError("bd command not found")
        return 1, ""
    except subprocess.TimeoutExpired:
        logger.error("bd %s timed out after 30s", " ".join(args))
        if strict:
            raise BeadsError(f"bd {' '.join(args)} timed out")
        return 1, ""


def run_bd_json(*args: str, cwd: str | None = None) -> tuple[int, list | dict | None]:
    """Run a bd command that returns JSON, with safe parsing.

    Returns (exit_code, parsed_data).  On parse failure, returns (exit_code, None)
    instead of silently returning an empty list — callers must handle None.
    """
    code, stdout = run_bd(*args, cwd=cwd)
    if code != 0:
        return code, None
    if not stdout:
        return code, None
    try:
        import json
        data = json.loads(stdout)
        return code, data
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("bd %s returned invalid JSON: %s (output: %.100s)",
                       " ".join(args), e, stdout)
        return code, None


def has_beads_dir(cwd: str | None) -> bool:
    """Return True if *cwd* has a ``.beads/`` directory or ``BEADS_DIR`` is set."""
    if "BEADS_DIR" in os.environ:
        return True
    if cwd:
        return os.path.isdir(os.path.join(cwd, ".beads"))
    return False


def add_dependency(child: str, parent: str, *,
                   cwd: str | None = None) -> tuple[int, str]:
    """Add a Beads dependency link: *child* is blocked by *parent*.

    Wraps ``bd dep add <child> <parent>``.
    """
    return run_bd("dep", "add", child, parent, cwd=cwd)


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
