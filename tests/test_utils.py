"""Tests for voronoi.utils — shared field extraction, title cleaning, note parsing."""

import pytest

from voronoi.utils import clean_finding_title, extract_field, find_checkpoint, is_finding_title, parse_finding_notes


class TestIsFindingTitle:
    """Canonical FINDING-title detector — INV-47 / BUG-001 regression."""

    @pytest.mark.parametrize("title", [
        "FINDING: EWC beats replay",
        "finding: lowercase still counts",
        "  FINDING: leading whitespace ok",
        "FINDING - dash form",
        "FINDING \u2014 em-dash form",
    ])
    def test_canonical_prefixes_accepted(self, title):
        assert is_finding_title(title) is True

    @pytest.mark.parametrize("title", [
        "Analyze pricing dataset for five action-changing findings",
        "Investigate finding the cheapest path",
        "Findings summary",       # no separator
        "FINDING",                # bare, no separator
        "Some FINDING: in middle",
        "",
    ])
    def test_ghost_titles_rejected(self, title):
        assert is_finding_title(title) is False


class TestExtractField:
    def test_colon_separator(self):
        assert extract_field("EFFECT_SIZE:0.82", "EFFECT_SIZE") == "0.82"

    def test_equals_separator(self):
        assert extract_field("EFFECT_SIZE=0.82", "EFFECT_SIZE") == "0.82"

    def test_with_spaces(self):
        assert extract_field("EFFECT_SIZE : 0.82", "EFFECT_SIZE") == "0.82"

    def test_multiline(self):
        notes = "VALENCE:positive\nEFFECT_SIZE:0.82\nN:100"
        assert extract_field(notes, "VALENCE") == "positive"
        assert extract_field(notes, "EFFECT_SIZE") == "0.82"
        assert extract_field(notes, "N") == "100"

    def test_pipe_separated(self):
        notes = "TYPE:finding | VALENCE:positive | EFFECT_SIZE:0.82"
        assert extract_field(notes, "TYPE") == "finding"
        assert extract_field(notes, "VALENCE") == "positive"

    def test_missing_field(self):
        assert extract_field("EFFECT_SIZE:0.82", "VALENCE") == ""

    def test_empty_notes(self):
        assert extract_field("", "VALENCE") == ""

    def test_case_insensitive(self):
        assert extract_field("effect_size:0.82", "EFFECT_SIZE") == "0.82"

    def test_field_with_brackets(self):
        assert extract_field("CI_95:[0.61, 1.03]", "CI_95") == "[0.61, 1.03]"


class TestCleanFindingTitle:
    def test_strip_finding_colon(self):
        assert clean_finding_title("FINDING: EWC works") == "EWC works"

    def test_strip_finding_no_colon(self):
        assert clean_finding_title("FINDING EWC works") == "EWC works"

    def test_lowercase_finding(self):
        assert clean_finding_title("finding: lowercase") == "lowercase"

    def test_no_prefix(self):
        assert clean_finding_title("regular title") == "regular title"

    def test_preserves_inner_finding(self):
        assert clean_finding_title("FINDING: Replay FINDING rates improved") == "Replay FINDING rates improved"

    def test_empty(self):
        assert clean_finding_title("") == ""


class TestParseFindingNotes:
    def test_basic_extraction(self):
        notes = "EFFECT_SIZE:0.82\nCI_95:[0.61, 1.03]\nN:100\nVALENCE:positive"
        parsed = parse_finding_notes(notes)
        assert parsed["effect_size"] == "0.82"
        assert parsed["ci_95"] == "[0.61, 1.03]"
        assert parsed["n"] == "100"
        assert parsed["valence"] == "positive"

    def test_pipe_separated(self):
        notes = "EFFECT_SIZE:0.82 | CI_95:[0.61, 1.03] | N:100"
        parsed = parse_finding_notes(notes)
        assert parsed["effect_size"] == "0.82"

    def test_missing_fields(self):
        parsed = parse_finding_notes("EFFECT_SIZE:0.82")
        assert "effect_size" in parsed
        assert "valence" not in parsed

    def test_empty_notes(self):
        parsed = parse_finding_notes("")
        assert parsed == {}

    def test_additional_fields(self):
        notes = "DATA_FILE:data/raw/results.csv\nROBUST:yes\nSTAT_TEST:Welch t-test"
        parsed = parse_finding_notes(notes)
        assert parsed["data_file"] == "data/raw/results.csv"
        assert parsed["robust"] == "yes"
        assert parsed["stat_test"] == "Welch t-test"


class TestFindCheckpoint:
    """FIX-06: find_checkpoint should check both canonical and LLM-shortened names."""

    def test_canonical_name(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "orchestrator-checkpoint.json").write_text("{}")
        assert find_checkpoint(tmp_path) is not None
        assert find_checkpoint(tmp_path).name == "orchestrator-checkpoint.json"

    def test_shortened_name(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "checkpoint.json").write_text("{}")
        assert find_checkpoint(tmp_path) is not None
        assert find_checkpoint(tmp_path).name == "checkpoint.json"

    def test_canonical_preferred_over_shortened(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "orchestrator-checkpoint.json").write_text("{}")
        (tmp_path / ".swarm" / "checkpoint.json").write_text("{}")
        assert find_checkpoint(tmp_path).name == "orchestrator-checkpoint.json"

    def test_no_checkpoint(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        assert find_checkpoint(tmp_path) is None
