"""Shared utilities used across Voronoi modules.

Canonical implementations of functions that were previously duplicated
across science.py, knowledge.py, and report.py.
"""

from __future__ import annotations

import re


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
