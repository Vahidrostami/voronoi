"""Knowledge recall — search past findings and evidence.

Queries the Beads database and evidence store to answer questions like
"what did we learn about caching?" using keyword matching and metadata search.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from voronoi.beads import run_bd as _run_bd
from voronoi.utils import parse_finding_notes as _parse_finding_notes


@dataclass
class Finding:
    """A scientific finding from the evidence store."""
    id: str
    title: str
    status: str
    priority: int
    notes: list[str] = field(default_factory=list)
    # Extracted structured fields
    effect_size: Optional[str] = None
    confidence_interval: Optional[str] = None
    sample_size: Optional[str] = None
    stat_test: Optional[str] = None
    valence: Optional[str] = None         # positive, negative, inconclusive
    confidence: Optional[str] = None      # 0.X
    data_file: Optional[str] = None
    robust: Optional[str] = None          # yes, no

    def format_telegram(self) -> str:
        """Format this finding for Telegram display."""
        lines = [f"*{self.id}*: {_escape_md(self.title)}"]
        if self.effect_size:
            parts = [f"Effect: {self.effect_size}"]
            if self.confidence_interval:
                parts.append(f"CI: {self.confidence_interval}")
            if self.sample_size:
                parts.append(f"N={self.sample_size}")
            lines.append("  " + ", ".join(parts))
        if self.valence:
            emoji = {"positive": "✅", "negative": "❌", "inconclusive": "❓"}.get(self.valence, "•")
            lines.append(f"  {emoji} {self.valence.upper()}")
        if self.robust:
            lines.append(f"  Robust: {_escape_md(self.robust)}")
        if self.stat_test:
            lines.append(f"  Test: {_escape_md(self.stat_test)}")
        return "\n".join(lines)


def _escape_md(text: str) -> str:
    """Minimal Markdown escaping for Telegram."""
    return text.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")


class KnowledgeStore:
    """Query interface for the evidence knowledge store.

    Searches Beads findings, journal entries, and belief maps.
    """

    def __init__(self, project_dir: str | Path):
        self.project_dir = str(project_dir)

    def search_findings(self, query: str, max_results: int = 10) -> list[Finding]:
        """Search findings by keyword matching against titles and notes."""
        code, output = _run_bd("list", "--json", cwd=self.project_dir)
        if code != 0:
            return []

        try:
            tasks = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            return []

        # Filter to finding-like tasks
        query_words = set(query.lower().split())
        scored: list[tuple[float, dict]] = []

        for task in tasks:
            title = task.get("title", "")
            notes_raw = task.get("notes", "")
            task_type = task.get("type", "")

            # Score relevance — must have at least one keyword match
            text_blob = f"{title} {notes_raw}".lower()
            keyword_score = sum(1 for w in query_words if w in text_blob)

            if keyword_score == 0:
                continue  # No keyword match, skip entirely

            score = float(keyword_score)

            # Boost findings and completed tasks
            if "FINDING" in title.upper() or "finding" in notes_raw.lower():
                score += 2
            if task.get("status") == "closed":
                score += 0.5
            if task_type == "investigation":
                score += 1

            scored.append((score, task))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        findings = []
        for _, task in scored[:max_results]:
            notes_raw = task.get("notes", "")
            parsed = _parse_finding_notes(notes_raw)

            f = Finding(
                id=task.get("id", "?"),
                title=task.get("title", "?"),
                status=task.get("status", "?"),
                priority=task.get("priority", 9),
                notes=notes_raw.split("\n") if notes_raw else [],
                effect_size=parsed.get("effect_size"),
                confidence_interval=parsed.get("ci_95"),
                sample_size=parsed.get("n") or parsed.get("sample_size"),
                stat_test=parsed.get("stat_test"),
                valence=parsed.get("valence"),
                confidence=parsed.get("confidence"),
                data_file=parsed.get("data_file"),
                robust=parsed.get("robust"),
            )
            findings.append(f)

        return findings

    def get_journal(self, max_lines: int = 30) -> Optional[str]:
        """Read the latest journal entries."""
        journal = Path(self.project_dir) / ".swarm" / "journal.md"
        if not journal.exists():
            return None
        lines = journal.read_text().strip().split("\n")
        return "\n".join(lines[-max_lines:])

    def get_belief_map(self) -> Optional[str]:
        """Read the current belief map."""
        # Check for belief map in .swarm/
        belief_file = Path(self.project_dir) / ".swarm" / "belief-map.md"
        if belief_file.exists():
            return belief_file.read_text().strip()
        # Also check JSON variant
        belief_json = Path(self.project_dir) / ".swarm" / "belief-map.json"
        if belief_json.exists():
            try:
                data = json.loads(belief_json.read_text())
                lines = ["*Belief Map*\n"]
                for h in data.get("hypotheses", []):
                    name = h.get("name", "?")
                    prior = h.get("prior", "?")
                    status = h.get("status", "?")
                    lines.append(f"• {name}: P={prior} [{status}]")
                return "\n".join(lines)
            except (json.JSONDecodeError, ValueError):
                return belief_json.read_text().strip()
        return None

    def get_strategic_context(self) -> Optional[str]:
        """Read the strategic context document."""
        ctx_file = Path(self.project_dir) / ".swarm" / "strategic-context.md"
        if ctx_file.exists():
            return ctx_file.read_text().strip()
        return None

    def format_recall_response(self, query: str, max_results: int = 5) -> str:
        """Format a complete recall response for Telegram."""
        findings = self.search_findings(query, max_results=max_results)

        if not findings:
            return f"📚 No findings match: _{_escape_md(query)}_\n\nThe knowledge store is empty or no tasks match your query."

        lines = [f"📚 *{len(findings)} finding(s)* for: _{_escape_md(query)}_\n"]
        for i, f in enumerate(findings, 1):
            lines.append(f"{i}. {f.format_telegram()}")
            lines.append("")

        return "\n".join(lines)
