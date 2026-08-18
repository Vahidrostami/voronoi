"""Guards docs/SPEC-INDEX.md — the routing table agents use to find specs.

Wraps scripts/check-spec-index.py so index drift fails the suite instead of
relying on someone remembering to run the script.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-spec-index.py"


def _load_checker() -> ModuleType:
    # Hyphenated filename outside any package, so import it by path.
    spec = importlib.util.spec_from_file_location("check_spec_index", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves its module via sys.modules, so register before exec.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
INDEX_TEXT = checker.SPEC_INDEX.read_text()


def test_every_source_file_is_indexed() -> None:
    missing = checker.actual_source_files() - checker.extract_source_files(INDEX_TEXT)
    assert not missing, (
        "Source files missing from the SPEC-INDEX Module table: "
        f"{sorted(missing)}. Add a row so agents can find their spec."
    )


def test_no_stale_source_references() -> None:
    stale = checker.extract_source_files(INDEX_TEXT) - checker.actual_source_files()
    assert not stale, f"SPEC-INDEX references source files that no longer exist: {sorted(stale)}"


def test_no_stale_test_references() -> None:
    stale = checker.extract_test_files(INDEX_TEXT) - checker.actual_test_files()
    assert not stale, f"SPEC-INDEX references test files that no longer exist: {sorted(stale)}"


def test_every_test_file_is_indexed() -> None:
    unindexed = checker.actual_test_files() - checker.extract_test_files(INDEX_TEXT)
    assert not unindexed, (
        f"Test files missing from SPEC-INDEX: {sorted(unindexed)}. "
        "Add a module row, or a row under Cross-Cutting Tests if it spans several modules."
    )


def test_declared_line_ranges_stay_inside_their_sections() -> None:
    errors, _ = checker.check_line_ranges(INDEX_TEXT)
    assert not errors, (
        "SPEC-INDEX line ranges drifted from the docs they point at:\n"
        + "\n".join(f"  - {e}" for e in errors)
        + "\nRerun: python scripts/check-spec-index.py --print-ranges"
    )
