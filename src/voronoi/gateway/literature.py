"""External literature search — Semantic Scholar API integration.

Provides structured paper search for the Scout agent to ground
investigations in existing work before hypothesis generation.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("voronoi.literature")

_API_BASE = "https://api.semanticscholar.org/graph/v1"
_TIMEOUT = 15  # seconds


@dataclass
class Paper:
    """A paper from external literature search."""
    paper_id: str
    title: str
    abstract: str = ""
    year: Optional[int] = None
    citation_count: int = 0
    authors: list[str] = field(default_factory=list)
    url: str = ""

    def format_brief(self) -> str:
        """Format as a concise reference for scout briefs."""
        authors_str = ", ".join(self.authors[:3])
        if len(self.authors) > 3:
            authors_str += " et al."
        parts = [f"**{self.title}**"]
        if authors_str:
            parts.append(f"  {authors_str}")
        if self.year:
            parts.append(f"  ({self.year})")
        if self.citation_count:
            parts.append(f"  Citations: {self.citation_count}")
        if self.abstract:
            # First sentence only
            first_sentence = self.abstract.split(". ")[0]
            if len(first_sentence) > 200:
                first_sentence = first_sentence[:197] + "..."
            parts.append(f"  > {first_sentence}")
        return "\n".join(parts)


def search_papers(query: str, max_results: int = 5) -> list[Paper]:
    """Search Semantic Scholar for papers matching a query.

    Returns an empty list on any API failure (network, rate limit, etc.).
    """
    if not query.strip():
        return []

    params = urllib.parse.urlencode({
        "query": query,
        "limit": min(max_results, 20),
        "fields": "title,abstract,year,citationCount,authors,url",
    })
    url = f"{_API_BASE}/paper/search?{params}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Voronoi/0.4"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        logger.warning("Semantic Scholar search failed: %s", e)
        return []

    papers: list[Paper] = []
    for item in data.get("data", [])[:max_results]:
        if not isinstance(item, dict):
            continue
        authors = []
        for a in item.get("authors", []):
            if isinstance(a, dict) and a.get("name"):
                authors.append(a["name"])
        papers.append(Paper(
            paper_id=item.get("paperId", ""),
            title=item.get("title", ""),
            abstract=item.get("abstract") or "",
            year=item.get("year"),
            citation_count=item.get("citationCount", 0),
            authors=authors,
            url=item.get("url", ""),
        ))

    return papers


def format_literature_brief(papers: list[Paper]) -> str:
    """Format a list of papers into a scout-ready literature brief."""
    if not papers:
        return "No relevant papers found in external literature search."

    lines = [f"## Literature Survey ({len(papers)} papers)\n"]
    for i, p in enumerate(papers, 1):
        lines.append(f"### {i}. {p.format_brief()}\n")

    return "\n".join(lines)
