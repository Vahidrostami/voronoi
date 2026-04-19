"""Tests for voronoi.science.citation_coverage — manuscript citation integrity gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from voronoi.science import (  # re-exported via science/__init__.py
    CoverageResult,
    check_coverage,
    extract_cite_keys,
    fuzzy_match_title,
    write_coverage_audit,
)
from voronoi.science.citation_coverage import (
    DEFAULT_COVERAGE_TARGET,
    DEFAULT_TITLE_THRESHOLD,
)


# ---------------------------------------------------------------------------
# fuzzy_match_title
# ---------------------------------------------------------------------------

class TestFuzzyMatchTitle:

    def test_identical_titles_match(self):
        t = "Attention Is All You Need"
        assert fuzzy_match_title(t, t) is True

    def test_case_and_punctuation_differences_match(self):
        a = "Attention Is All You Need"
        b = "attention is all you need!"
        assert fuzzy_match_title(a, b) is True

    def test_trivial_spacing_match(self):
        a = "Attention   Is All-You Need"
        b = "Attention Is All You Need"
        assert fuzzy_match_title(a, b) is True

    def test_completely_different_titles_do_not_match(self):
        a = "Attention Is All You Need"
        b = "Optimising Compiler Phase Ordering with Reinforcement Learning"
        assert fuzzy_match_title(a, b) is False

    def test_minor_edit_still_matches_default_threshold(self):
        # Slightly different title — real-world Semantic Scholar normalisation case.
        a = "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding"
        b = "BERT Pre-training of Deep Bidirectional Transformers for Language Understanding."
        assert fuzzy_match_title(a, b) is True

    def test_empty_inputs_do_not_match(self):
        assert fuzzy_match_title("", "foo") is False
        assert fuzzy_match_title("foo", "") is False
        assert fuzzy_match_title("", "") is False

    def test_threshold_respected(self):
        a = "Foo Bar Baz"
        b = "Completely Different String"
        # At threshold 0.0 everything matches.
        assert fuzzy_match_title(a, b, threshold=0.0) is True
        # At threshold 1.0 only identical strings match.
        assert fuzzy_match_title(a, a, threshold=1.0) is True
        assert fuzzy_match_title(a, b, threshold=1.0) is False


# ---------------------------------------------------------------------------
# extract_cite_keys
# ---------------------------------------------------------------------------

class TestExtractCiteKeys:

    def test_single_cite(self):
        assert extract_cite_keys(r"Prior work~\cite{smith2024}") == {"smith2024"}

    def test_multi_key_cite(self):
        tex = r"See \cite{smith2024, doe2023,  lee2022}."
        assert extract_cite_keys(tex) == {"smith2024", "doe2023", "lee2022"}

    def test_citep_and_citet_variants(self):
        tex = r"\citep{a} and \citet{b} and \citeauthor{c}"
        assert extract_cite_keys(tex) == {"a", "b", "c"}

    def test_no_cites(self):
        assert extract_cite_keys("plain text no citations") == set()

    def test_ignores_commented_out_cite_key_text(self):
        # Commented-out \cite lines are stripped before extraction so they
        # don't produce false orphan reports in the coverage gate.
        tex = "% \\cite{hidden}\n\\cite{real}"
        assert extract_cite_keys(tex) == {"real"}

    def test_ignores_verbatim_environment(self):
        tex = ("\\begin{verbatim}\n\\cite{example}\n\\end{verbatim}\n"
               "\\cite{real}")
        assert extract_cite_keys(tex) == {"real"}

    def test_preserves_escaped_percent(self):
        # \\% is a literal percent sign in LaTeX, not a comment.
        tex = "10\\% improvement \\cite{real}"
        assert extract_cite_keys(tex) == {"real"}


# ---------------------------------------------------------------------------
# check_coverage — happy path + failures
# ---------------------------------------------------------------------------

def _write_ledger(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entries": entries}), encoding="utf-8")


class TestCheckCoverage:

    def test_all_integrated_passes(self, tmp_path: Path):
        ledger = tmp_path / "ledger.json"
        _write_ledger(ledger, [
            {"bibtex_key": "a2024", "verified": True, "title": "A"},
            {"bibtex_key": "b2023", "verified": True, "title": "B"},
            {"bibtex_key": "c2022", "verified": True, "title": "C"},
        ])
        tex = tmp_path / "paper.tex"
        tex.write_text(r"See \cite{a2024,b2023} and \cite{c2022}.", encoding="utf-8")

        r = check_coverage(ledger, tex)
        assert isinstance(r, CoverageResult)
        assert r.verified_count == 3
        assert r.integrated_count == 3
        assert r.integration_rate == 1.0
        assert r.unintegrated_keys == []
        assert r.orphan_cites == []
        assert r.passes is True

    def test_partial_integration_below_target_fails(self, tmp_path: Path):
        ledger = tmp_path / "ledger.json"
        _write_ledger(ledger, [
            {"bibtex_key": f"k{i}", "verified": True, "title": f"P{i}"} for i in range(10)
        ])
        tex = tmp_path / "paper.tex"
        # Only 8/10 cited → 0.80 < 0.90 target.
        tex.write_text(r"\cite{k0,k1,k2,k3,k4,k5,k6,k7}", encoding="utf-8")

        r = check_coverage(ledger, tex)
        assert r.integration_rate == 0.8
        assert r.passes is False
        assert set(r.unintegrated_keys) == {"k8", "k9"}
        assert r.orphan_cites == []

    def test_orphan_cite_is_hallucination_and_fails(self, tmp_path: Path):
        """A \\cite{} to a key absent from the ledger means a hallucinated reference."""
        ledger = tmp_path / "ledger.json"
        _write_ledger(ledger, [
            {"bibtex_key": "real2024", "verified": True, "title": "Real"},
        ])
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{real2024,hallucinated2024}", encoding="utf-8")

        r = check_coverage(ledger, tex)
        # Verified entry IS integrated, rate is 1.0, but there's an orphan —
        # so the gate still fails. The semantics are: zero
        # tolerance for hallucinated refs regardless of coverage rate.
        assert r.integration_rate == 1.0
        assert r.orphan_cites == ["hallucinated2024"]
        assert r.passes is False

    def test_unverified_entries_do_not_count(self, tmp_path: Path):
        """Entries with verified=false must be excluded from the denominator."""
        ledger = tmp_path / "ledger.json"
        _write_ledger(ledger, [
            {"bibtex_key": "ok", "verified": True, "title": "OK"},
            {"bibtex_key": "bad", "verified": False, "title": "Unverified"},
        ])
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{ok}", encoding="utf-8")

        r = check_coverage(ledger, tex)
        assert r.verified_count == 1
        assert r.integration_rate == 1.0
        assert r.passes is True

    def test_empty_ledger_returns_trivially_passing(self, tmp_path: Path):
        """A manuscript with nothing to cite is vacuously integrated."""
        ledger = tmp_path / "ledger.json"
        _write_ledger(ledger, [])
        tex = tmp_path / "paper.tex"
        tex.write_text("No citations here.", encoding="utf-8")

        r = check_coverage(ledger, tex)
        assert r.verified_count == 0
        assert r.integration_rate == 1.0
        assert r.passes is True

    def test_custom_target(self, tmp_path: Path):
        ledger = tmp_path / "ledger.json"
        _write_ledger(ledger, [
            {"bibtex_key": f"k{i}", "verified": True} for i in range(10)
        ])
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{k0,k1,k2,k3,k4,k5,k6,k7}", encoding="utf-8")

        strict = check_coverage(ledger, tex, target=0.95)
        assert strict.passes is False

        lenient = check_coverage(ledger, tex, target=0.75)
        assert lenient.passes is True

    def test_missing_ledger_raises(self, tmp_path: Path):
        tex = tmp_path / "paper.tex"
        tex.write_text("x", encoding="utf-8")
        with pytest.raises(FileNotFoundError):
            check_coverage(tmp_path / "missing.json", tex)

    def test_missing_tex_raises(self, tmp_path: Path):
        ledger = tmp_path / "ledger.json"
        _write_ledger(ledger, [])
        with pytest.raises(FileNotFoundError):
            check_coverage(ledger, tmp_path / "missing.tex")

    def test_malformed_ledger_raises(self, tmp_path: Path):
        ledger = tmp_path / "ledger.json"
        ledger.write_text("not json{{{", encoding="utf-8")
        tex = tmp_path / "paper.tex"
        tex.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError):
            check_coverage(ledger, tex)

    def test_ledger_without_entries_list_raises(self, tmp_path: Path):
        ledger = tmp_path / "ledger.json"
        ledger.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        tex = tmp_path / "paper.tex"
        tex.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError):
            check_coverage(ledger, tex)


class TestWriteCoverageAudit:

    def test_round_trip(self, tmp_path: Path):
        r = CoverageResult(
            integration_rate=0.95,
            verified_count=20,
            integrated_count=19,
            unintegrated_keys=["a"],
            orphan_cites=[],
            target=0.90,
        )
        out = tmp_path / ".swarm" / "manuscript" / "coverage-audit.json"
        result_path = write_coverage_audit(r, out)
        assert result_path == out
        data = json.loads(out.read_text())
        assert data["integration_rate"] == 0.95
        assert data["verified_count"] == 20
        assert data["unintegrated_keys"] == ["a"]
        assert data["passes"] is True
        assert data["target"] == 0.90


# ---------------------------------------------------------------------------
# Commented-out citations should not cause false orphan reports
# ---------------------------------------------------------------------------

class TestCommentedOutCitations:

    def test_commented_cite_not_counted_as_orphan(self, tmp_path: Path):
        """A %-commented \\cite should not appear as an orphan."""
        ledger = tmp_path / "ledger.json"
        _write_ledger(ledger, [
            {"bibtex_key": "real2024", "verified": True, "title": "Real"},
        ])
        tex = tmp_path / "paper.tex"
        tex.write_text("% \\cite{old_ref}\n\\cite{real2024}", encoding="utf-8")

        r = check_coverage(ledger, tex)
        assert r.orphan_cites == []
        assert r.passes is True

    def test_verbatim_cite_not_counted(self, tmp_path: Path):
        """Citations inside verbatim blocks should be ignored."""
        ledger = tmp_path / "ledger.json"
        _write_ledger(ledger, [
            {"bibtex_key": "real2024", "verified": True, "title": "Real"},
        ])
        tex = tmp_path / "paper.tex"
        tex.write_text(
            "\\begin{verbatim}\n\\cite{example}\n\\end{verbatim}\n"
            "\\cite{real2024}",
            encoding="utf-8",
        )

        r = check_coverage(ledger, tex)
        assert r.orphan_cites == []
        assert r.passes is True


# ---------------------------------------------------------------------------
# Defaults — contract check so the public values don't silently drift
# ---------------------------------------------------------------------------

def test_default_constants():
    assert DEFAULT_COVERAGE_TARGET == 0.90
    assert DEFAULT_TITLE_THRESHOLD == 0.70
