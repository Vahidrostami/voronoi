"""Tests for voronoi.utils — shared field extraction, title cleaning, note parsing."""

import pytest

from voronoi.utils import clean_finding_title, extract_field, parse_finding_notes


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
