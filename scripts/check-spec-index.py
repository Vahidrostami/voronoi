#!/usr/bin/env python3
"""Validate that docs/SPEC-INDEX.md references match the actual filesystem.

Run from repo root:
    python scripts/check-spec-index.py

Exit 0 if everything matches, exit 1 with details on drift.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_INDEX = ROOT / "docs" / "SPEC-INDEX.md"
SRC = ROOT / "src" / "voronoi"
TESTS = ROOT / "tests"


def extract_source_files(text: str) -> set[str]:
    """Pull source-file paths from the Module → Spec → Test table."""
    return set(re.findall(r"`(src/voronoi/[^`*]+\.py)`", text))


def extract_test_files(text: str) -> set[str]:
    """Pull test-file names from the table's Test column."""
    return set(re.findall(r"`(test_[^`]+\.py)`", text))


def actual_source_files() -> set[str]:
    """All non-dunder .py source files."""
    return {
        str(p.relative_to(ROOT))
        for p in SRC.rglob("*.py")
        if not p.name.startswith("__")
    }


def actual_test_files() -> set[str]:
    """All test_*.py files."""
    return {p.name for p in TESTS.glob("test_*.py")}


def main() -> int:
    text = SPEC_INDEX.read_text()
    errors: list[str] = []

    # --- Source files ---
    spec_srcs = extract_source_files(text)
    actual_srcs = actual_source_files()

    missing_from_spec = actual_srcs - spec_srcs
    if missing_from_spec:
        errors.append(
            "Source files not in SPEC-INDEX:\n"
            + "\n".join(f"  + {f}" for f in sorted(missing_from_spec))
        )

    stale_in_spec = spec_srcs - actual_srcs
    if stale_in_spec:
        errors.append(
            "SPEC-INDEX references files that don't exist:\n"
            + "\n".join(f"  - {f}" for f in sorted(stale_in_spec))
        )

    # --- Test files ---
    spec_tests = extract_test_files(text)
    actual_tests = actual_test_files()

    stale_tests = spec_tests - actual_tests
    if stale_tests:
        errors.append(
            "SPEC-INDEX references test files that don't exist:\n"
            + "\n".join(f"  - {f}" for f in sorted(stale_tests))
        )

    if errors:
        print("SPEC-INDEX drift detected:\n")
        print("\n\n".join(errors))
        print("\nUpdate docs/SPEC-INDEX.md to match the filesystem.")
        return 1

    print(f"OK — {len(spec_srcs)} source files, {len(spec_tests)} test files verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
