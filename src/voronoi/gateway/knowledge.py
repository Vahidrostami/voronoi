"""Knowledge recall — search past findings and evidence.

Queries the Beads database and evidence store to answer questions like
"what did we learn about caching?" using hybrid BM25 keyword + weighted
scoring for better recall on exact tokens (task IDs, data hashes,
statistical values) alongside semantic relevance.
"""

from __future__ import annotations

import json
import re
import sqlite3
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
    """Markdown escaping for Telegram MarkdownV2."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


class KnowledgeStore:
    """Query interface for the evidence knowledge store.

    Searches Beads findings, journal entries, and belief maps.
    """

    def __init__(self, project_dir: str | Path):
        self.project_dir = str(project_dir)

    def search_findings(self, query: str, max_results: int = 10) -> list[Finding]:
        """Search findings with hybrid BM25 keyword + weighted scoring.

        Combines exact-token BM25 matching (good for IDs, hashes, stats)
        with the existing keyword relevance scoring (good for topics).
        """
        code, output = _run_bd("list", "--json", cwd=self.project_dir)
        if code != 0:
            return []

        try:
            tasks = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            return []

        if not tasks:
            return []

        # Build BM25 scores via in-memory FTS5
        bm25_scores = self._bm25_score(tasks, query)

        # Keyword relevance scoring (existing approach)
        query_words = set(query.lower().split())
        scored: list[tuple[float, dict]] = []

        for task in tasks:
            tid = task.get("id", "")
            title = task.get("title", "")
            notes_raw = task.get("notes", "")

            text_blob = f"{title} {notes_raw}".lower()
            keyword_score = sum(1 for w in query_words if w in text_blob)

            # BM25 score for this task (0.0 if not matched)
            bm25 = bm25_scores.get(tid, 0.0)

            # Must match on at least one signal
            if keyword_score == 0 and bm25 == 0.0:
                continue

            # Weighted combination: BM25 handles exact tokens, keyword handles topics
            score = float(keyword_score) * 0.6 + bm25 * 0.4

            # Boost findings and completed tasks
            if "FINDING" in title.upper() or "finding" in notes_raw.lower():
                score += 2
            if task.get("status") == "closed":
                score += 0.5
            if task.get("type") == "investigation":
                score += 1

            scored.append((score, task))

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

    @staticmethod
    def _bm25_score(tasks: list[dict], query: str) -> dict[str, float]:
        """Compute BM25 relevance scores using SQLite FTS5.

        Returns a dict mapping task ID → normalized BM25 score (0.0–1.0).
        Uses an in-memory SQLite database so there's no disk footprint.
        """
        if not tasks or not query.strip():
            return {}

        try:
            conn = sqlite3.connect(":memory:")
            try:
                conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS findings USING fts5(tid, content)")

                # Insert all tasks
                rows = []
                for task in tasks:
                    tid = task.get("id", "")
                    title = task.get("title", "")
                    notes = task.get("notes", "")
                    content = f"{tid} {title} {notes}"
                    rows.append((tid, content))
                conn.executemany("INSERT INTO findings(tid, content) VALUES (?, ?)", rows)

                # Escape query for FTS5 — strip double quotes, then wrap each word
                words = [w.replace('"', '') for w in query.split() if w.replace('"', '')]
                escaped_query = " ".join(f'"{w}"' for w in words)
                if not escaped_query:
                    return {}

                # Query with BM25 ranking — FTS5 bm25() returns negative values
                # where more negative = more relevant
                cursor = conn.execute(
                    "SELECT tid, bm25(findings) FROM findings WHERE findings MATCH ? "
                    "ORDER BY bm25(findings) LIMIT ?",
                    (escaped_query, len(tasks)),
                )
                raw_scores: dict[str, float] = {}
                for row in cursor:
                    # bm25 returns negative — negate so higher = better
                    raw_scores[row[0]] = -float(row[1])
            finally:
                conn.close()

            if not raw_scores:
                return {}

            # Normalize to 0.0–1.0
            max_score = max(raw_scores.values()) if raw_scores else 1.0
            if max_score <= 0:
                return {}
            return {tid: score / max_score for tid, score in raw_scores.items()}

        except Exception:
            # FTS5 not available or query syntax error — degrade gracefully
            return {}

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
