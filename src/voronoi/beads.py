"""Beads (bd) subprocess helpers — single source of truth.

Every module that calls ``bd`` should import from here instead of
duplicating subprocess boilerplate.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time

logger = logging.getLogger("voronoi.beads")

# Retry settings for embedded Dolt exclusive lock contention (beads v1.0.0).
# With server mode (the default for Voronoi workspaces since April 2026)
# lock contention is rare, but we keep a short retry for robustness.
_LOCK_RETRIES = 2
_LOCK_INITIAL_WAIT = 0.2  # seconds
_LOCK_ERROR_FRAGMENT = "another process holds the exclusive lock"


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

    wait = _LOCK_INITIAL_WAIT
    for attempt in range(_LOCK_RETRIES + 1):
        try:
            result = subprocess.run(
                ["bd", *args],
                capture_output=True, text=True, timeout=30,
                cwd=cwd, env=env,
            )
            if result.stderr:
                logger.debug("bd %s stderr: %s", " ".join(args), result.stderr.strip())
            if result.returncode != 0:
                # Retry on embedded Dolt exclusive lock contention
                if (_LOCK_ERROR_FRAGMENT in result.stderr
                        and attempt < _LOCK_RETRIES):
                    logger.debug("bd %s: lock contention, retry %d/%d in %.1fs",
                                 " ".join(args), attempt + 1, _LOCK_RETRIES, wait)
                    time.sleep(wait)
                    wait = min(wait * 2, 2.0)
                    continue
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
    # Exhausted retries — return last result
    return result.returncode, result.stdout.strip()


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
