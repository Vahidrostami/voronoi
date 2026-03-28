"""Shared utilities used across Voronoi modules.

Canonical implementations of functions that were previously duplicated
across science.py, knowledge.py, and report.py.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def extract_field(notes: str, field_name: str) -> str:
    """Extract a field value from Beads notes string.

    Handles both ``KEY:value`` and ``KEY=value`` formats, as well as
    pipe-separated multi-key lines (``KEY1:val1 | KEY2:val2``).
    """
    pattern = rf"\b{re.escape(field_name)}\s*[:=]\s*([^\n|]+)"
    m = re.search(pattern, notes, re.I)
    return m.group(1).strip() if m else ""


def clean_finding_title(title: str) -> str:
    """Strip leading FINDING: prefix from a finding title."""
    for prefix in ("FINDING:", "FINDING"):
        if title.upper().startswith(prefix):
            title = title[len(prefix):]
            break
    return title.strip()


def parse_finding_notes(notes_str: str) -> dict:
    """Extract structured fields from Beads notes strings.

    Returns a dict with lowercase keys like 'effect_size', 'ci_95', etc.
    """
    fields: dict = {}
    for key in ("EFFECT_SIZE", "CI_95", "N", "STAT_TEST", "VALENCE",
                "CONFIDENCE", "DATA_FILE", "ROBUST", "TYPE", "SAMPLE_SIZE",
                "DATA_HASH", "P", "QUALITY"):
        val = extract_field(notes_str, key)
        if val:
            fields[key.lower()] = val
    return fields


def resolve_git_default_branch(repo_path: str | Path) -> str:
    """Resolve the repository's primary branch name."""
    cwd = str(repo_path)

    def _run(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    remote_head = _run("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if remote_head.startswith("origin/"):
        return remote_head.split("/", 1)[1]

    current = _run("rev-parse", "--abbrev-ref", "HEAD")
    if current and current != "HEAD":
        return current

    for candidate in ("main", "master"):
        try:
            result = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return candidate

    configured = _run("config", "--get", "init.defaultBranch")
    if configured:
        return configured

    return "main"


def git_init_main(repo_path: str | Path) -> None:
    """Initialize a git repository with ``main`` as the primary branch."""
    cwd = str(repo_path)
    result = subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return

    subprocess.run(["git", "init"], cwd=cwd, capture_output=True, text=True, check=False)
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
