"""Tests for voronoi.gateway.literature — external literature search."""

import json
from unittest.mock import patch, MagicMock

import pytest

from voronoi.gateway.literature import (
    Paper,
    format_literature_brief,
    search_papers,
)


# ---------------------------------------------------------------------------
# Paper formatting
# ---------------------------------------------------------------------------

class TestPaper:
    def test_format_brief_basic(self):
        p = Paper(paper_id="abc", title="Test Paper", year=2024,
                  citation_count=42, authors=["Smith, J."])
        text = p.format_brief()
        assert "Test Paper" in text
        assert "Smith, J." in text
        assert "2024" in text
        assert "42" in text

    def test_format_brief_many_authors(self):
        p = Paper(paper_id="abc", title="Test",
                  authors=["A", "B", "C", "D", "E"])
        text = p.format_brief()
        assert "et al." in text

    def test_format_brief_with_abstract(self):
        p = Paper(paper_id="abc", title="Test",
                  abstract="This is the first sentence. And a second one.")
        text = p.format_brief()
        assert "first sentence" in text

    def test_format_brief_long_abstract_truncated(self):
        p = Paper(paper_id="abc", title="Test",
                  abstract="X" * 300)
        text = p.format_brief()
        assert len(text) < 500


# ---------------------------------------------------------------------------
# Literature brief formatting
# ---------------------------------------------------------------------------

class TestFormatLiteratureBrief:
    def test_no_papers(self):
        text = format_literature_brief([])
        assert "No relevant papers" in text

    def test_with_papers(self):
        papers = [
            Paper(paper_id="1", title="Paper One", year=2023),
            Paper(paper_id="2", title="Paper Two", year=2024),
        ]
        text = format_literature_brief(papers)
        assert "2 papers" in text
        assert "Paper One" in text
        assert "Paper Two" in text


# ---------------------------------------------------------------------------
# Search (mocked HTTP)
# ---------------------------------------------------------------------------

class TestSearchPapers:
    def test_empty_query(self):
        assert search_papers("") == []
        assert search_papers("  ") == []

    @patch("voronoi.gateway.literature.urllib.request.urlopen")
    def test_search_success(self, mock_urlopen):
        response_data = {
            "data": [
                {
                    "paperId": "abc123",
                    "title": "Multi-Agent Reasoning",
                    "abstract": "We study agents",
                    "year": 2024,
                    "citationCount": 10,
                    "authors": [{"name": "Smith, J."}, {"name": "Doe, A."}],
                    "url": "https://example.com/paper",
                },
            ],
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        papers = search_papers("multi-agent reasoning")
        assert len(papers) == 1
        assert papers[0].title == "Multi-Agent Reasoning"
        assert papers[0].year == 2024
        assert papers[0].authors == ["Smith, J.", "Doe, A."]

    @patch("voronoi.gateway.literature.urllib.request.urlopen")
    def test_search_api_failure(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("timeout")
        papers = search_papers("anything")
        assert papers == []

    @patch("voronoi.gateway.literature.urllib.request.urlopen")
    def test_search_respects_max_results(self, mock_urlopen):
        response_data = {
            "data": [
                {"paperId": f"p{i}", "title": f"Paper {i}", "authors": []}
                for i in range(10)
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        papers = search_papers("test", max_results=3)
        assert len(papers) == 3
