"""Tests for voronoi.gateway.report — teaser + PDF generation."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from voronoi.gateway.report import (
    ReportGenerator,
)
from voronoi.utils import (
    clean_finding_title as _clean_finding_title,
    extract_field as _parse_note_value,
)


@pytest.fixture
def workspace(tmp_path):
    """Create a minimal investigation workspace."""
    swarm = tmp_path / ".swarm"
    swarm.mkdir()
    (tmp_path / "PROMPT.md").write_text("# Question\n\nWhy is performance degrading?")
    (swarm / "deliverable.md").write_text("# Conclusion\n\nEWC+replay is best.")
    (swarm / "journal.md").write_text("## Round 1\nLaunched 3 agents\n## Round 2\nMerged results")
    (swarm / "belief-map.md").write_text("- H1: EWC works (P=0.8)\n- H2: Distillation works (P=0.2)")
    return tmp_path


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestCleanFindingTitle:
    def test_strips_prefix_colon(self):
        assert _clean_finding_title("FINDING: EWC works") == "EWC works"

    def test_strips_prefix_no_colon(self):
        assert _clean_finding_title("FINDING EWC works") == "EWC works"

    def test_preserves_finding_in_body(self):
        assert _clean_finding_title("FINDING: Replay FINDING rates improved") == "Replay FINDING rates improved"

    def test_case_insensitive_prefix(self):
        assert _clean_finding_title("finding: lowercase") == "lowercase"


class TestParseNoteValue:
    def test_single_key_line(self):
        notes = "EFFECT_SIZE:0.82\nCI_95:[0.61, 1.03]"
        assert _parse_note_value(notes, "EFFECT_SIZE") == "0.82"
        assert _parse_note_value(notes, "CI_95") == "[0.61, 1.03]"

    def test_pipe_separated_line(self):
        notes = "EFFECT_SIZE:0.82 | CI_95:[0.61, 1.03] | N:500"
        assert _parse_note_value(notes, "EFFECT_SIZE") == "0.82"
        assert _parse_note_value(notes, "CI_95") == "[0.61, 1.03]"
        assert _parse_note_value(notes, "N") == "500"

    def test_missing_key(self):
        assert _parse_note_value("EFFECT_SIZE:0.5", "VALENCE") == ""

    def test_mixed_format(self):
        notes = "SOURCE_TASK:bd-5 | EFFECT_SIZE:0.82\nVALENCE:positive"
        assert _parse_note_value(notes, "EFFECT_SIZE") == "0.82"
        assert _parse_note_value(notes, "VALENCE") == "positive"
        assert _parse_note_value(notes, "SOURCE_TASK") == "bd-5"


# ---------------------------------------------------------------------------
# Teaser tests
# ---------------------------------------------------------------------------

class TestTeaser:
    @patch("voronoi.gateway.report._run_bd")
    def test_teaser_with_findings(self, mock_bd, workspace):
        findings = [
            {"id": "bd-5", "title": "FINDING: EWC cuts forgetting 34%",
             "notes": "VALENCE:positive\nEFFECT_SIZE:0.82\nP:<.001"},
            {"id": "bd-6", "title": "FINDING: Distillation no effect",
             "notes": "VALENCE:negative\nEFFECT_SIZE:0.08"},
        ]
        mock_bd.return_value = (0, json.dumps(findings))

        rg = ReportGenerator(workspace)
        teaser = rg.build_teaser(7, "Why is performance degrading?", 12, 12, 18.5)

        assert "COMPLETE" in teaser
        assert "Voronoi" in teaser
        assert "EWC" in teaser
        assert "100%" in teaser
        assert "18min" in teaser
        assert "report attached" in teaser.lower()

    @patch("voronoi.gateway.report._run_bd")
    def test_teaser_no_findings(self, mock_bd, workspace):
        mock_bd.return_value = (0, json.dumps([]))

        rg = ReportGenerator(workspace)
        teaser = rg.build_teaser(1, "test question", 5, 3, 10)

        assert "COMPLETE" in teaser
        assert "60%" in teaser
        assert "0 findings" in teaser

    @patch("voronoi.gateway.report._run_bd")
    def test_teaser_bd_failure(self, mock_bd, workspace):
        mock_bd.return_value = (1, "")

        rg = ReportGenerator(workspace)
        teaser = rg.build_teaser(1, "test", 0, 0, 0)

        assert "COMPLETE" in teaser

    @patch("voronoi.gateway.report._run_bd")
    def test_headline_picks_largest_effect(self, mock_bd, workspace):
        findings = [
            {"id": "bd-1", "title": "FINDING: Small effect",
             "notes": "EFFECT_SIZE:0.08\nVALENCE:negative"},
            {"id": "bd-2", "title": "FINDING: Large effect",
             "notes": "EFFECT_SIZE:1.20\nVALENCE:positive"},
            {"id": "bd-3", "title": "FINDING: Medium effect",
             "notes": "EFFECT_SIZE:0.50\nVALENCE:positive"},
        ]
        mock_bd.return_value = (0, json.dumps(findings))

        rg = ReportGenerator(workspace)
        teaser = rg.build_teaser(1, "test", 5, 5, 10)

        # Headline should be "Large effect" (d=1.20), not first
        lines = teaser.split("\n")
        headline_idx = next(i for i, l in enumerate(lines) if "HEADLINE" in l)
        assert "Large effect" in lines[headline_idx + 1]

    @patch("voronoi.gateway.report._run_bd")
    def test_headline_not_duplicated_in_all_findings(self, mock_bd, workspace):
        findings = [
            {"id": "bd-1", "title": "FINDING: Alpha",
             "notes": "EFFECT_SIZE:0.5\nVALENCE:positive"},
            {"id": "bd-2", "title": "FINDING: Beta",
             "notes": "EFFECT_SIZE:0.3\nVALENCE:positive"},
        ]
        mock_bd.return_value = (0, json.dumps(findings))

        rg = ReportGenerator(workspace)
        teaser = rg.build_teaser(1, "test", 5, 5, 10)

        # "Alpha" is the headline; "All findings" should only list "Beta"
        all_findings_section = teaser.split("*All findings:*")
        if len(all_findings_section) > 1:
            remainder = all_findings_section[1]
            assert "Alpha" not in remainder
            assert "Beta" in remainder


# ---------------------------------------------------------------------------
# Markdown tests
# ---------------------------------------------------------------------------

class TestMarkdown:
    @patch("voronoi.gateway.report._run_bd")
    def test_markdown_full_report(self, mock_bd, workspace):
        findings = [
            {"id": "bd-5", "title": "FINDING: EWC works",
             "notes": "EFFECT_SIZE:0.82\nCI_95:[0.61, 1.03]\nN:500\nSTAT_TEST:t-test\nVALENCE:positive\nROBUST:yes\nSTAT_REVIEW: APPROVED"},
        ]
        mock_bd.return_value = (0, json.dumps(findings))

        rg = ReportGenerator(workspace)
        md = rg.build_markdown()

        assert "Investigation Report" in md
        assert "Question" in md
        assert "Findings" in md
        assert "EWC works" in md
        assert "Summary Table" in md
        # New structured sections
        assert "Detailed Conclusion" in md or "Conclusion" in md

    @patch("voronoi.gateway.report._run_bd")
    def test_markdown_has_interpretation(self, mock_bd, workspace):
        findings = [
            {"id": "bd-5", "title": "FINDING: EWC works",
             "notes": "EFFECT_SIZE:0.82\nCI_95:[0.61, 1.03]\nN:500\nSTAT_TEST:t-test\nVALENCE:positive\nROBUST:yes\nSTAT_REVIEW: APPROVED"},
        ]
        mock_bd.return_value = (0, json.dumps(findings))

        rg = ReportGenerator(workspace)
        md = rg.build_markdown()

        # Should include interpretation data
        assert "Finding 1" in md
        assert "Effect size" in md or "Verdict" in md

    @patch("voronoi.gateway.report._run_bd")
    def test_markdown_has_limitations_for_fragile(self, mock_bd, workspace):
        findings = [
            {"id": "bd-5", "title": "FINDING: Fragile result",
             "notes": "EFFECT_SIZE:0.3\nVALENCE:positive\nROBUST:no\nSTAT_REVIEW: APPROVED"},
        ]
        mock_bd.return_value = (0, json.dumps(findings))

        rg = ReportGenerator(workspace)
        md = rg.build_markdown()

        assert "Limitations" in md
        assert "Fragile" in md or "fragile" in md

    @patch("voronoi.gateway.report._run_bd")
    def test_markdown_has_negative_results(self, mock_bd, workspace):
        findings = [
            {"id": "bd-5", "title": "FINDING: Strategy A works",
             "notes": "EFFECT_SIZE:0.82\nVALENCE:positive"},
            {"id": "bd-6", "title": "FINDING: Strategy B fails",
             "notes": "EFFECT_SIZE:0.08\nVALENCE:negative"},
        ]
        mock_bd.return_value = (0, json.dumps(findings))

        rg = ReportGenerator(workspace)
        md = rg.build_markdown()

        assert "Negative" in md
        assert "Strategy B fails" in md

    @patch("voronoi.gateway.report._run_bd")
    def test_markdown_cross_finding_comparison(self, mock_bd, workspace):
        findings = [
            {"id": "bd-5", "title": "FINDING: Large effect",
             "notes": "EFFECT_SIZE:1.2\nVALENCE:positive"},
            {"id": "bd-6", "title": "FINDING: Small effect",
             "notes": "EFFECT_SIZE:0.2\nVALENCE:positive"},
        ]
        mock_bd.return_value = (0, json.dumps(findings))

        rg = ReportGenerator(workspace)
        md = rg.build_markdown()

        assert "Comparative" in md
        assert "strongest" in md.lower() or "larger" in md.lower()

    @patch("voronoi.gateway.report._run_bd")
    def test_markdown_minimal(self, mock_bd, tmp_path):
        """Workspace with no .swarm files."""
        (tmp_path / ".swarm").mkdir()
        mock_bd.return_value = (0, json.dumps([]))

        rg = ReportGenerator(tmp_path)
        md = rg.build_markdown()

        assert "Investigation Report" in md

    @patch("voronoi.gateway.report._run_bd")
    def test_markdown_belief_json(self, mock_bd, workspace):
        """Test belief map from JSON format."""
        (workspace / ".swarm" / "belief-map.md").unlink()
        (workspace / ".swarm" / "belief-map.json").write_text(json.dumps({
            "hypotheses": [
                {"name": "H1", "prior": 0.8, "status": "confirmed"},
            ]
        }))
        mock_bd.return_value = (0, json.dumps([]))

        rg = ReportGenerator(workspace)
        md = rg.build_markdown()

        assert "H1" in md
        assert "0.8" in md


# ---------------------------------------------------------------------------
# PDF tests
# ---------------------------------------------------------------------------

class TestPDF:
    @patch("voronoi.gateway.report._run_bd")
    def test_fallback_to_md(self, mock_bd, workspace):
        """When fpdf2 is not available, fall back to .md file."""
        mock_bd.return_value = (0, json.dumps([]))

        rg = ReportGenerator(workspace)
        with patch.dict("sys.modules", {"fpdf": None}):
            path = rg.build_pdf()

        if path is not None:
            assert path.exists()
            assert path.suffix in (".pdf", ".md")

    @patch("voronoi.gateway.report._run_bd")
    def test_pdf_generation(self, mock_bd, workspace):
        """Test PDF generation when fpdf2 is available."""
        mock_bd.return_value = (0, json.dumps([
            {"id": "bd-1", "title": "FINDING: Test result",
             "notes": "EFFECT_SIZE:0.5\nVALENCE:positive"},
        ]))

        rg = ReportGenerator(workspace)
        path = rg.build_pdf()

        if path is not None:
            assert path.exists()


# ---------------------------------------------------------------------------
# Format detection tests
# ---------------------------------------------------------------------------

class TestFormatDetection:
    def test_manuscript_from_rigor_scientific(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        rg = ReportGenerator(tmp_path, rigor="scientific")
        assert rg.is_manuscript is True
        assert rg.doc_type == "manuscript"

    def test_manuscript_from_rigor_experimental(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        rg = ReportGenerator(tmp_path, rigor="experimental")
        assert rg.is_manuscript is True

    def test_report_from_rigor_standard(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        rg = ReportGenerator(tmp_path, rigor="standard")
        assert rg.is_manuscript is False
        assert rg.doc_type == "report"

    def test_report_from_rigor_analytical(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        rg = ReportGenerator(tmp_path, rigor="analytical")
        assert rg.is_manuscript is False

    def test_fallback_detects_academic_headings(self, tmp_path):
        """When rigor not provided, fall back to content detection."""
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text(
            "# Paper Title\n\n"
            "## Abstract\n\nThis paper investigates...\n\n"
            "## Introduction\n\nCatastrophic forgetting is...\n\n"
            "## Methods\n\nWe trained models on...\n\n"
            "## Results\n\nEWC+replay outperformed...\n\n"
            "## Discussion\n\nThese results suggest...\n"
        )
        rg = ReportGenerator(tmp_path)  # no rigor
        assert rg.is_manuscript is True

    def test_fallback_rejects_non_heading_matches(self, tmp_path):
        """Content-based detection only matches headings, not body text."""
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text(
            "# Summary\n\n"
            "The abstract of the paper discusses methods.\n"
            "The results show that the introduction worked.\n"
            "discussion of findings follows.\n"
        )
        rg = ReportGenerator(tmp_path)  # no rigor
        assert rg.is_manuscript is False

    def test_fallback_without_deliverable(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        rg = ReportGenerator(tmp_path)
        assert rg.is_manuscript is False

    def test_fallback_with_only_two_sections(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text(
            "## Abstract\n\nSomething\n\n## Results\n\nSomething else\n"
        )
        rg = ReportGenerator(tmp_path)
        assert rg.is_manuscript is False

    def test_not_manuscript_with_report_deliverable(self, workspace):
        rg = ReportGenerator(workspace)
        assert rg.is_manuscript is False


# ---------------------------------------------------------------------------
# Manuscript markdown tests
# ---------------------------------------------------------------------------

class TestManuscriptMarkdown:
    @patch("voronoi.gateway.report._run_bd")
    def test_manuscript_uses_deliverable(self, mock_bd, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text(
            "# Forgetting Mitigation\n\n"
            "## Abstract\n\nWe investigate...\n\n"
            "## Introduction\n\nBackground...\n\n"
            "## Methods\n\nExperiments...\n\n"
            "## Results\n\nEWC works.\n\n"
            "## Discussion\n\nImplications...\n"
        )
        mock_bd.return_value = (0, json.dumps([
            {"id": "bd-1", "title": "FINDING: EWC works",
             "notes": "EFFECT_SIZE:0.82\nVALENCE:positive\nROBUST:yes\nSTAT_REVIEW: APPROVED"},
        ]))

        rg = ReportGenerator(tmp_path, rigor="scientific")
        md = rg.build_manuscript_markdown()

        assert "Forgetting Mitigation" in md
        assert "Abstract" in md
        assert "Appendix A: Evidence Summary" in md
        assert "EWC works" in md

    @patch("voronoi.gateway.report._run_bd")
    def test_manuscript_skeleton_without_deliverable(self, mock_bd, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (tmp_path / "PROMPT.md").write_text("Study forgetting mitigation")
        (swarm / "journal.md").write_text("Ran 3 experiments")
        mock_bd.return_value = (0, json.dumps([
            {"id": "bd-1", "title": "FINDING: Replay helps",
             "notes": "EFFECT_SIZE:0.5\nP:<.01\nVALENCE:positive"},
        ]))

        rg = ReportGenerator(tmp_path, rigor="scientific")
        md = rg.build_manuscript_markdown()

        assert "Research Manuscript" in md
        assert "Abstract" in md
        assert "Results" in md
        assert "Replay helps" in md
        assert "Methods" in md

    @patch("voronoi.gateway.report._run_bd")
    def test_teaser_says_manuscript_with_rigor(self, mock_bd, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text("Some deliverable")
        mock_bd.return_value = (0, json.dumps([]))

        rg = ReportGenerator(tmp_path, rigor="scientific")
        teaser = rg.build_teaser(1, "test", 5, 5, 10)
        assert "manuscript" in teaser.lower()

    @patch("voronoi.gateway.report._run_bd")
    def test_teaser_says_report_when_not_manuscript(self, mock_bd, workspace):
        mock_bd.return_value = (0, json.dumps([]))
        rg = ReportGenerator(workspace, rigor="standard")
        teaser = rg.build_teaser(1, "test", 5, 5, 10)
        assert "report" in teaser.lower()

    @patch("voronoi.gateway.report._run_bd")
    def test_pdf_named_manuscript(self, mock_bd, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text("Some content for the manuscript")
        mock_bd.return_value = (0, json.dumps([]))

        rg = ReportGenerator(tmp_path, rigor="scientific")
        path = rg.build_pdf()
        if path is not None:
            assert "manuscript" in path.name


# ---------------------------------------------------------------------------
# Auto-markdown tests
# ---------------------------------------------------------------------------

class TestAutoMarkdown:
    @patch("voronoi.gateway.report._run_bd")
    def test_auto_markdown_report(self, mock_bd, workspace):
        mock_bd.return_value = (0, json.dumps([]))
        rg = ReportGenerator(workspace, rigor="standard")
        md = rg.build_auto_markdown()
        assert "Investigation Report" in md

    @patch("voronoi.gateway.report._run_bd")
    def test_auto_markdown_manuscript(self, mock_bd, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text("# Paper\n\nContent")
        mock_bd.return_value = (0, json.dumps([]))
        rg = ReportGenerator(tmp_path, rigor="scientific")
        md = rg.build_auto_markdown()
        assert "Paper" in md


# ---------------------------------------------------------------------------
# Findings caching test
# ---------------------------------------------------------------------------

class TestFindingsCache:
    @patch("voronoi.gateway.report._run_bd")
    def test_findings_cached_across_calls(self, mock_bd, workspace):
        mock_bd.return_value = (0, json.dumps([
            {"id": "bd-1", "title": "FINDING: X", "notes": "VALENCE:positive"},
        ]))

        rg = ReportGenerator(workspace)
        rg._get_findings()
        rg._get_findings()
        rg._get_findings()

        # bd should only be called once
        assert mock_bd.call_count == 1


# ---------------------------------------------------------------------------
# Belief narrative tests
# ---------------------------------------------------------------------------

class TestBeliefNarrative:
    @patch("voronoi.gateway.report._run_bd")
    def test_belief_narrative_trajectory(self, mock_bd, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "belief-map.json").write_text(json.dumps({
            "hypotheses": [
                {"name": "EWC works", "prior": 0.5, "posterior": 0.9,
                 "status": "confirmed", "evidence": ["bd-1", "bd-3"]},
                {"name": "Distillation works", "prior": 0.6, "posterior": 0.2,
                 "status": "refuted", "evidence": ["bd-2"]},
                {"name": "Replay helps", "prior": 0.5, "posterior": 0.5,
                 "status": "inconclusive", "evidence": []},
            ]
        }))
        mock_bd.return_value = (0, json.dumps([]))

        rg = ReportGenerator(tmp_path)
        narrative = rg._render_belief_narrative()

        assert narrative is not None
        assert "EWC works" in narrative
        assert "confirmed" in narrative
        assert "refuted" in narrative
        # Should contain trajectory arrows
        assert "\u2191" in narrative or "\u2193" in narrative  # up or down arrow
        # Summary
        assert "1 confirmed" in narrative
        assert "1 refuted" in narrative
        assert "1 inconclusive" in narrative

    @patch("voronoi.gateway.report._run_bd")
    def test_belief_narrative_falls_back_to_md(self, mock_bd, workspace):
        """When belief-map.md exists, prefer it."""
        mock_bd.return_value = (0, json.dumps([]))
        rg = ReportGenerator(workspace)
        narrative = rg._render_belief_narrative()
        # Should contain content from belief-map.md
        assert narrative is not None
        assert "EWC" in narrative or "H1" in narrative


# ---------------------------------------------------------------------------
# Evidence chain tests
# ---------------------------------------------------------------------------

class TestEvidenceChain:
    @patch("voronoi.gateway.report._run_bd")
    def test_evidence_chain_rendering(self, mock_bd, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "claim-evidence.json").write_text(json.dumps({
            "claims": [
                {"claim_id": "C1", "claim_text": "Encoding outperforms baseline",
                 "finding_ids": ["bd-5"], "hypothesis_ids": ["H1"],
                 "strength": "robust",
                 "interpretation": "Large practical effect confirmed"},
                {"claim_id": "C2", "claim_text": "Pipeline scales to 1000+ levers",
                 "finding_ids": [], "hypothesis_ids": [],
                 "strength": "unsupported",
                 "interpretation": ""},
            ],
            "orphan_findings": ["bd-6"],
            "unsupported_claims": ["C2"],
            "coverage_score": 0.5,
        }))
        mock_bd.return_value = (0, json.dumps([]))

        rg = ReportGenerator(tmp_path)
        chain = rg._render_evidence_chain()

        assert chain is not None
        assert "Encoding outperforms baseline" in chain
        assert "robust" in chain
        assert "Unsupported claims" in chain
        assert "C2" in chain
        assert "not cited" in chain.lower() or "orphan" in chain.lower()
        assert "50%" in chain

    @patch("voronoi.gateway.report._run_bd")
    def test_evidence_chain_none_without_file(self, mock_bd, tmp_path):
        (tmp_path / ".swarm").mkdir()
        mock_bd.return_value = (0, json.dumps([]))
        rg = ReportGenerator(tmp_path)
        assert rg._render_evidence_chain() is None


# ---------------------------------------------------------------------------
# Limitations auto-generation tests
# ---------------------------------------------------------------------------

class TestLimitations:
    @patch("voronoi.gateway.report._run_bd")
    def test_limitations_from_fragile(self, mock_bd, workspace):
        mock_bd.return_value = (0, json.dumps([]))
        rg = ReportGenerator(workspace)
        findings = [
            {"title": "FINDING: EWC fragile", "robust": "no",
             "notes": "ROBUST:no"},
        ]
        lim = rg._render_limitations(findings)
        assert lim is not None
        assert "Fragile" in lim

    @patch("voronoi.gateway.report._run_bd")
    def test_limitations_from_wide_ci(self, mock_bd, workspace):
        mock_bd.return_value = (0, json.dumps([]))
        rg = ReportGenerator(workspace)
        findings = [
            {"title": "FINDING: Imprecise result",
             "ci_quality": "very wide", "notes": ""},
        ]
        lim = rg._render_limitations(findings)
        assert lim is not None
        assert "Imprecise" in lim

    @patch("voronoi.gateway.report._run_bd")
    def test_limitations_from_inconclusive_hypothesis(self, mock_bd, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "belief-map.json").write_text(json.dumps({
            "hypotheses": [
                {"name": "Untested H", "prior": 0.5, "status": "inconclusive"},
            ]
        }))
        mock_bd.return_value = (0, json.dumps([]))
        rg = ReportGenerator(tmp_path)
        findings = [{"title": "FINDING: test", "notes": ""}]
        lim = rg._render_limitations(findings)
        assert lim is not None
        assert "Inconclusive" in lim

    def test_no_limitations_when_all_robust(self):
        rg = ReportGenerator.__new__(ReportGenerator)
        rg.ws = Path("/tmp/fake")
        rg.swarm = Path("/tmp/fake/.swarm")
        findings = [
            {"title": "FINDING: Good result", "robust": "yes",
             "strength_label": "robust", "stat_review": "APPROVED",
             "notes": "STAT_REVIEW: APPROVED"},
        ]
        lim = rg._render_limitations(findings)
        assert lim is None


# ---------------------------------------------------------------------------
# Cross-finding comparison tests
# ---------------------------------------------------------------------------

class TestCrossFindingComparison:
    def test_comparison_two_findings(self):
        findings = [
            {"title": "FINDING: Large effect", "effect_size": "1.2",
             "valence": "positive", "practical_significance": "very large"},
            {"title": "FINDING: Small effect", "effect_size": "0.2",
             "valence": "positive", "practical_significance": "small"},
        ]
        result = ReportGenerator._render_cross_finding_comparison(findings)
        assert result is not None
        assert "Large effect" in result
        assert "6.0x" in result

    def test_comparison_with_mixed_valence(self):
        findings = [
            {"title": "FINDING: Positive", "effect_size": "0.8",
             "valence": "positive"},
            {"title": "FINDING: Negative", "effect_size": "0.5",
             "valence": "negative"},
        ]
        result = ReportGenerator._render_cross_finding_comparison(findings)
        assert result is not None
        assert "mixed" in result.lower()

    def test_comparison_single_finding(self):
        findings = [
            {"title": "FINDING: Only one", "effect_size": "0.5"},
        ]
        assert ReportGenerator._render_cross_finding_comparison(findings) is None

    def test_comparison_no_numeric_effects(self):
        findings = [
            {"title": "FINDING: One", "effect_size": "large"},
            {"title": "FINDING: Two", "effect_size": "small"},
        ]
        assert ReportGenerator._render_cross_finding_comparison(findings) is None


# ---------------------------------------------------------------------------
# Negative results tests
# ---------------------------------------------------------------------------

class TestNegativeResults:
    def test_renders_negative_findings(self):
        findings = [
            {"title": "FINDING: Strategy failed", "valence": "negative",
             "effect_size": "0.08", "p": "0.42"},
            {"title": "FINDING: Strategy works", "valence": "positive",
             "effect_size": "0.82"},
        ]
        result = ReportGenerator._render_negative_results(findings)
        assert result is not None
        assert "Strategy failed" in result
        assert "Strategy works" not in result
        assert "negative" in result.lower()

    def test_no_negative_results(self):
        findings = [
            {"title": "FINDING: All good", "valence": "positive"},
        ]
        assert ReportGenerator._render_negative_results(findings) is None

    def test_inconclusive_included(self):
        findings = [
            {"title": "FINDING: Unclear", "valence": "inconclusive"},
        ]
        result = ReportGenerator._render_negative_results(findings)
        assert result is not None
        assert "Unclear" in result
