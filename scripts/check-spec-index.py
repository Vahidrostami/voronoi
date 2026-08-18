#!/usr/bin/env python3
"""Validate that docs/SPEC-INDEX.md references match the actual filesystem.

Run from repo root:
    python scripts/check-spec-index.py
    python scripts/check-spec-index.py --print-ranges

Exit 0 if everything matches, exit 1 with details on drift.

Line-range drift is REPORTED but does not fail the build yet (first slice).
Flip ``LINE_RANGES_ARE_FATAL`` to True once the ranges have proven stable.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SPEC_INDEX = DOCS / "SPEC-INDEX.md"
SRC = ROOT / "src" / "voronoi"
TESTS = ROOT / "tests"

# Line-range checks start advisory so the column can land without gating CI.
LINE_RANGES_ARE_FATAL = False

SECTION_RE = re.compile(r"^##\s+(\d+[a-z]?)\.?\s+(.*)$")
DOC_RE = re.compile(r"\b([A-Z][A-Z0-9-]*\.md)\b")
SECTION_REF_RE = re.compile(r"§(\d+[a-z]?)(?:\s*-\s*(\d+[a-z]?))?")
LINE_RANGE_RE = re.compile(r"L(\d+)-L(\d+)")


@dataclass(frozen=True)
class Section:
    ident: str
    title: str
    start: int
    end: int


@dataclass(frozen=True)
class IndexRow:
    label: str
    docs: list[str]
    section_cell: str
    lines_cell: str


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


def parse_sections(lines: list[str], name: str) -> tuple[dict[str, Section], list[str]]:
    """Map ``## N.`` heading ids to their 1-based inclusive line spans."""
    found: list[tuple[str, str, int]] = []
    for lineno, line in enumerate(lines, start=1):
        match = SECTION_RE.match(line)
        if match:
            found.append((match.group(1), match.group(2).strip(), lineno))

    sections: dict[str, Section] = {}
    duplicates: list[str] = []
    for i, (ident, title, start) in enumerate(found):
        end = found[i + 1][2] - 1 if i + 1 < len(found) else len(lines)
        if ident in sections:
            duplicates.append(f"{name}: duplicate section id §{ident} ({title!r})")
            continue
        sections[ident] = Section(ident, title, start, end)
    return sections, duplicates


def all_sections() -> tuple[dict[str, dict[str, Section]], dict[str, int], list[str]]:
    """Parse every spec doc once, returning sections, line counts and duplicates."""
    parsed: dict[str, dict[str, Section]] = {}
    lengths: dict[str, int] = {}
    duplicates: list[str] = []
    for path in sorted(DOCS.glob("*.md")):
        lines = path.read_text().splitlines()
        sections, dupes = parse_sections(lines, path.name)
        parsed[path.name] = sections
        lengths[path.name] = len(lines)
        duplicates.extend(dupes)
    return parsed, lengths, duplicates


def parse_index_rows(text: str) -> list[IndexRow]:
    """Pull table rows that route to a spec doc and carry a Lines column.

    Both index tables put label/spec/section/lines in the first four columns.
    """
    rows: list[IndexRow] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or set(stripped) <= set("|-: "):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 4:
            continue
        # A markdown link repeats the filename in text and target — dedupe.
        docs = list(dict.fromkeys(DOC_RE.findall(cells[1])))
        rows.append(IndexRow(cells[0], docs, cells[2], cells[3]))
    return rows


def resolve_spans(
    sections: dict[str, Section], section_cell: str
) -> list[tuple[int, int]] | None:
    """One span per ``§`` reference; ``§N-M`` collapses to a single contiguous span.

    A declared range must fit inside one of these, so ``§2, §10`` cannot be
    satisfied by a range covering the gap between them.
    """
    spans: list[tuple[int, int]] = []
    for first, last in SECTION_REF_RE.findall(section_cell):
        start_section = sections.get(first)
        end_section = sections.get(last or first)
        if start_section is None or end_section is None:
            return None
        spans.append((start_section.start, end_section.end))
    return spans or None


def check_line_ranges(text: str) -> tuple[list[str], list[str]]:
    """Verify each declared Lines range still falls inside its named section.

    Returns ``(errors, notes)``; notes are informational and never fail a build.
    """
    parsed, lengths, duplicates = all_sections()
    errors: list[str] = []
    notes: list[str] = list(duplicates)

    for row in parse_index_rows(text):
        declared = [(int(a), int(b)) for a, b in LINE_RANGE_RE.findall(row.lines_cell)]
        if not declared:
            continue
        if len(row.docs) != 1:
            notes.append(
                f"{row.label!r}: {len(row.docs)} docs in one row — range not verified"
            )
            continue
        doc = row.docs[0]
        sections = parsed.get(doc)
        if sections is None:
            errors.append(f"{row.label!r}: unknown doc {doc}")
            continue

        doc_end = lengths[doc]
        spans = resolve_spans(sections, row.section_cell)
        for start, end in declared:
            if start > end or end > doc_end:
                errors.append(
                    f"{row.label!r}: L{start}-L{end} outside {doc} (1-{doc_end})"
                )
            elif spans and not any(lo <= start and end <= hi for lo, hi in spans):
                shown = ", ".join(f"L{lo}-L{hi}" for lo, hi in spans)
                errors.append(
                    f"{row.label!r}: L{start}-L{end} escapes {doc} "
                    f"{row.section_cell} ({shown})"
                )
    return errors, notes


def print_ranges() -> None:
    """Dump every section span — used to author the Lines column."""
    parsed, _, _ = all_sections()
    for doc, sections in parsed.items():
        print(f"\n## {doc}")
        for s in sections.values():
            size = s.end - s.start + 1
            print(f"  §{s.ident:<4} L{s.start}-L{s.end}  ({size:4d})  {s.title}")


def main() -> int:
    if "--print-ranges" in sys.argv:
        print_ranges()
        return 0

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

    unindexed_tests = actual_tests - spec_tests
    if unindexed_tests:
        errors.append(
            "Test files not in SPEC-INDEX (add a module row or a Cross-Cutting Tests row):\n"
            + "\n".join(f"  + {f}" for f in sorted(unindexed_tests))
        )

    # --- Line ranges ---
    range_errors, range_notes = check_line_ranges(text)
    if range_errors and LINE_RANGES_ARE_FATAL:
        errors.append(
            "Line-range drift:\n" + "\n".join(f"  ! {e}" for e in range_errors)
        )

    if errors:
        print("SPEC-INDEX drift detected:\n")
        print("\n\n".join(errors))
        print("\nUpdate docs/SPEC-INDEX.md to match the filesystem.")
        return 1

    for label, items in (("error", range_errors), ("note", range_notes)):
        for item in items:
            print(f"  {label}: {item}")

    print(f"OK — {len(spec_srcs)} source files, {len(spec_tests)} test files verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
