"""Tests for voronoi.gateway.report — teaser + PDF generation."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from voronoi.gateway.report import ReportGenerator


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
        assert "12/12" in teaser
        assert "18min" in teaser
        assert "report attached" in teaser.lower()

    @patch("voronoi.gateway.report._run_bd")
    def test_teaser_no_findings(self, mock_bd, workspace):
        mock_bd.return_value = (0, json.dumps([]))

        rg = ReportGenerator(workspace)
        teaser = rg.build_teaser(1, "test question", 5, 3, 10)

        assert "COMPLETE" in teaser
        assert "3/5" in teaser
        assert "0 findings" in teaser

    @patch("voronoi.gateway.report._run_bd")
    def test_teaser_bd_failure(self, mock_bd, workspace):
        mock_bd.return_value = (1, "bd not found")

        rg = ReportGenerator(workspace)
        teaser = rg.build_teaser(1, "test", 0, 0, 0)

        assert "COMPLETE" in teaser


class TestMarkdown:
    @patch("voronoi.gateway.report._run_bd")
    def test_markdown_full_report(self, mock_bd, workspace):
        findings = [
            {"id": "bd-5", "title": "FINDING: EWC works",
             "notes": "EFFECT_SIZE:0.82\nCI_95:[0.61, 1.03]\nN:500\nSTAT_TEST:t-test\nVALENCE:positive"},
        ]
        mock_bd.return_value = (0, json.dumps(findings))

        rg = ReportGenerator(workspace)
        md = rg.build_markdown()

        assert "Investigation Report" in md
        assert "Question" in md
        assert "Findings" in md
        assert "EWC works" in md
        assert "Belief Map" in md
        assert "Journal" in md
        assert "Conclusion" in md

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
        # Remove the markdown version, add JSON
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


class TestPDF:
    @patch("voronoi.gateway.report._run_bd")
    def test_fallback_to_md(self, mock_bd, workspace):
        """When fpdf2 is not available, fall back to .md file."""
        mock_bd.return_value = (0, json.dumps([]))

        rg = ReportGenerator(workspace)
        # Simulate fpdf2 not available by patching import
        with patch.dict("sys.modules", {"fpdf": None}):
            path = rg.build_pdf()

        # Should produce either .pdf or .md file
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

        # Either PDF was generated or fallback to MD
        if path is not None:
            assert path.exists()


# ---------------------------------------------------------------------------
# Paper format detection + generation
# ---------------------------------------------------------------------------

class TestPaperDetection:
    def test_not_manuscript_without_deliverable(self, tmp_path):
        (tmp_path / ".swarm").mkdir()
        rg = ReportGenerator(tmp_path)
        assert rg.is_manuscript_format() is False

    def test_not_manuscript_with_report_deliverable(self, workspace):
        rg = ReportGenerator(workspace)
        assert rg.is_manuscript_format() is False

    def test_is_manuscript_with_academic_sections(self, tmp_path):
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
        rg = ReportGenerator(tmp_path)
        assert rg.is_manuscript_format() is True

    def test_not_manuscript_with_only_two_sections(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text(
            "## Abstract\n\nSomething\n\n## Results\n\nSomething else\n"
        )
        rg = ReportGenerator(tmp_path)
        assert rg.is_manuscript_format() is False


class TestPaperMarkdown:
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
             "notes": "EFFECT_SIZE:0.82\nVALENCE:positive"},
        ]))

        rg = ReportGenerator(tmp_path)
        md = rg.build_manuscript_markdown()

        assert "Forgetting Mitigation" in md
        assert "Abstract" in md
        assert "Appendix: Evidence Summary" in md
        assert "EWC works" in md

    @patch("voronoi.gateway.report._run_bd")
    def test_manuscript_skeleton_without_deliverable(self, mock_bd, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (tmp_path / "PROMPT.md").write_text("Study forgetting mitigation")
        (swarm / "journal.md").write_text("Ran 3 experiments")
        mock_bd.return_value = (0, json.dumps([
            {"id": "bd-1", "title": "FINDING: Replay helps",
             "notes": "EFFECT_SIZE:0.5\nP:<.01"},
        ]))

        rg = ReportGenerator(tmp_path)
        md = rg.build_manuscript_markdown()

        assert "Research Manuscript" in md
        assert "Abstract" in md
        assert "Results" in md
        assert "Replay helps" in md
        assert "Methods" in md

    @patch("voronoi.gateway.report._run_bd")
    def test_teaser_says_manuscript(self, mock_bd, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text(
            "## Abstract\n\nX\n## Introduction\n\nY\n"
            "## Methods\n\nZ\n## Results\n\nW\n## Discussion\n\nV\n"
        )
        mock_bd.return_value = (0, json.dumps([]))

        rg = ReportGenerator(tmp_path)
        teaser = rg.build_teaser(1, "test", 5, 5, 10)
        assert "manuscript" in teaser.lower()

    @patch("voronoi.gateway.report._run_bd")
    def test_teaser_says_report_when_not_manuscript(self, mock_bd, workspace):
        mock_bd.return_value = (0, json.dumps([]))
        rg = ReportGenerator(workspace)
        teaser = rg.build_teaser(1, "test", 5, 5, 10)
        assert "report" in teaser.lower()

    @patch("voronoi.gateway.report._run_bd")
    def test_pdf_named_manuscript(self, mock_bd, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir()
        (swarm / "deliverable.md").write_text(
            "## Abstract\n\nX\n## Introduction\n\nY\n"
            "## Methods\n\nZ\n## Results\n\nW\n## Discussion\n\nV\n"
        )
        mock_bd.return_value = (0, json.dumps([]))

        rg = ReportGenerator(tmp_path)
        path = rg.build_pdf()
        if path is not None:
            assert "manuscript" in path.name
