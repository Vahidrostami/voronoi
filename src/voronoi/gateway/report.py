"""Report generation — teaser, report PDF, and scientific manuscript PDF.

Collects deliverable, findings, belief map, and journal from a
workspace and assembles them into:
  1. A short Telegram teaser (3-5 bullet points)
  2. A full Markdown report (for investigations/explorations)
  3. A scientific manuscript (when deliverable has academic sections)
  4. A PDF file (optional, requires fpdf2)

The output format is auto-detected: if the deliverable contains
academic sections (Abstract, Introduction, Methods, Results, Discussion)
it renders as a manuscript. Otherwise it renders as a report.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional


def _run_bd(*args: str, cwd: str | None = None) -> tuple[int, str]:
    env = os.environ.copy()
    if cwd and "BEADS_DIR" not in env:
        beads_dir = os.path.join(cwd, ".beads")
        if os.path.isdir(beads_dir):
            env["BEADS_DIR"] = beads_dir
    try:
        result = subprocess.run(
            ["bd", *args],
            capture_output=True, text=True, timeout=30,
            cwd=cwd, env=env,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 1, ""


class ReportGenerator:
    """Builds teasers, markdown reports, and PDFs from investigation workspaces."""

    def __init__(self, workspace_path: Path):
        self.ws = workspace_path
        self.swarm = workspace_path / ".swarm"

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def _read_file(self, *parts: str) -> str | None:
        p = self.ws.joinpath(*parts)
        if p.exists():
            try:
                return p.read_text().strip()
            except OSError:
                pass
        return None

    def _get_findings(self) -> list[dict]:
        """Extract FINDING tasks from Beads."""
        code, output = _run_bd("list", "--json", cwd=str(self.ws))
        if code != 0:
            return []
        try:
            tasks = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            return []
        findings = []
        for t in tasks:
            title = t.get("title", "")
            if "FINDING" not in title.upper():
                continue
            notes = t.get("notes", "")
            f: dict = {"title": title, "id": t.get("id", "?")}
            for key in ("EFFECT_SIZE", "CI_95", "N", "STAT_TEST", "VALENCE", "P", "ROBUST"):
                for line in notes.split("\n"):
                    if key in line.upper():
                        _, _, val = line.partition(":")
                        if val.strip():
                            f[key.lower()] = val.strip().split("|")[0].strip()
                        break
            findings.append(f)
        return findings

    # ------------------------------------------------------------------
    # Teaser (Telegram message)
    # ------------------------------------------------------------------

    def build_teaser(self, investigation_id: int, question: str,
                     total_tasks: int, closed_tasks: int,
                     elapsed_min: float, *, mode: str = "investigate") -> str:
        """3-5 bullet point teaser for Telegram."""
        from voronoi.gateway.progress import MODE_EMOJI, progress_bar

        findings = self._get_findings()
        mode_emoji = MODE_EMOJI.get(mode, "🔷")

        lines = [f"🏁 *Voronoi #{investigation_id}* {mode_emoji} COMPLETE · {elapsed_min:.0f}min\n"]
        lines.append(f"_{question}_\n")

        # Headline finding — strongest effect gets a callout
        if findings:
            # Pick the finding with the largest numeric effect size
            headline = None
            for f in findings:
                es = f.get("effect_size", "")
                if es:
                    headline = f
                    break
            if headline is None:
                headline = findings[0]

            title = headline["title"].replace("FINDING:", "").replace("FINDING", "").strip()
            valence = headline.get("valence", "").lower()
            h_emoji = {"positive": "✅", "negative": "❌"}.get(valence, "❓")
            stat_parts = []
            if headline.get("effect_size"):
                stat_parts.append(f"d={headline['effect_size']}")
            if headline.get("ci_95"):
                stat_parts.append(f"CI {headline['ci_95']}")
            if headline.get("p"):
                stat_parts.append(f"p={headline['p']}")
            if headline.get("n"):
                stat_parts.append(f"N={headline['n']}")

            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"💡 *HEADLINE*")
            lines.append(f"{h_emoji} {title}")
            if stat_parts:
                lines.append(" · ".join(stat_parts))
            lines.append("━━━━━━━━━━━━━━━━━━━━\n")

            # Remaining findings
            if len(findings) > 1:
                lines.append("*All findings:*")
                for f in findings[:5]:
                    valence = f.get("valence", "").lower()
                    emoji = {"positive": "✅", "negative": "❌"}.get(valence, "❓")
                    f_title = f["title"].replace("FINDING:", "").replace("FINDING", "").strip()
                    effect = f.get("effect_size", "")
                    p_val = f.get("p", "")
                    entry = f"{emoji} {f_title}"
                    if effect:
                        entry += f" (d={effect}"
                        if p_val:
                            entry += f", p={p_val}"
                        entry += ")"
                    lines.append(f"  {entry}")
                lines.append("")

        finding_count = len(findings)
        bar = progress_bar(closed_tasks, total_tasks)
        lines.append(f"{bar} · {finding_count} finding{'s' if finding_count != 1 else ''}")

        doc_type = "manuscript" if self.is_manuscript_format() else "report"
        lines.append(f"\n📎 Full {doc_type} attached")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Full Markdown report
    # ------------------------------------------------------------------

    def build_markdown(self) -> str:
        """Assemble the full investigation report as Markdown."""
        sections: list[str] = []

        # Title
        prompt = self._read_file("PROMPT.md")
        if prompt:
            sections.append("# Investigation Report\n")
            sections.append(f"## Question\n\n{prompt}\n")
        else:
            sections.append("# Investigation Report\n")

        # Findings table
        findings = self._get_findings()
        if findings:
            sections.append("## Findings\n")
            sections.append("| # | Finding | Effect | CI | N | Test | Verdict |")
            sections.append("|---|---------|--------|----|---|------|---------|")
            for i, f in enumerate(findings, 1):
                title = f["title"].replace("FINDING:", "").replace("FINDING", "").strip()
                effect = f.get("effect_size", "—")
                ci = f.get("ci_95", "—")
                n = f.get("n", "—")
                test = f.get("stat_test", "—")
                valence = f.get("valence", "—")
                sections.append(f"| {i} | {title} | {effect} | {ci} | {n} | {test} | {valence} |")
            sections.append("")

        # Belief map
        belief = self._read_file(".swarm", "belief-map.md")
        if belief:
            sections.append(f"## Belief Map\n\n{belief}\n")
        else:
            belief_json = self._read_file(".swarm", "belief-map.json")
            if belief_json:
                try:
                    data = json.loads(belief_json)
                    lines = []
                    for h in data.get("hypotheses", []):
                        lines.append(
                            f"- **{h.get('name', '?')}**: P={h.get('prior', '?')} [{h.get('status', '?')}]"
                        )
                    if lines:
                        sections.append("## Belief Map\n\n" + "\n".join(lines) + "\n")
                except (json.JSONDecodeError, ValueError):
                    pass

        # Methodology / journal
        journal = self._read_file(".swarm", "journal.md")
        if journal:
            sections.append(f"## Methodology & Journal\n\n{journal}\n")

        # Conclusion / deliverable
        deliverable = self._read_file(".swarm", "deliverable.md")
        if deliverable:
            sections.append(f"## Conclusion\n\n{deliverable}\n")

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # Manuscript detection
    # ------------------------------------------------------------------

    _PAPER_SECTIONS = {"abstract", "introduction", "methods", "methodology",
                       "results", "discussion", "conclusion", "related work",
                       "references", "background"}

    def is_manuscript_format(self) -> bool:
        """Check if the deliverable has academic manuscript structure."""
        deliverable = self._read_file(".swarm", "deliverable.md")
        if not deliverable:
            return False
        headings = set()
        for line in deliverable.split("\n"):
            stripped = line.strip().lstrip("#").strip().lower()
            if stripped:
                headings.add(stripped)
        # Manuscript if it has at least 3 academic section headings
        return len(headings & self._PAPER_SECTIONS) >= 3

    # ------------------------------------------------------------------
    # Scientific manuscript Markdown
    # ------------------------------------------------------------------

    def build_manuscript_markdown(self) -> str:
        """Assemble a structured scientific manuscript from the deliverable + evidence."""
        sections: list[str] = []
        deliverable = self._read_file(".swarm", "deliverable.md") or ""
        prompt = self._read_file("PROMPT.md") or ""
        findings = self._get_findings()

        # If the deliverable already has manuscript structure, use it as the base
        # and inject evidence tables where appropriate
        if deliverable:
            sections.append(deliverable)

            # Append findings table if not already embedded
            if findings and "finding" not in deliverable.lower():
                sections.append("\n## Appendix: Evidence Summary\n")
                sections.append("| # | Finding | Effect | CI | N | Test | Verdict |")
                sections.append("|---|---------|--------|----|---|------|---------|")
                for i, f in enumerate(findings, 1):
                    title = f["title"].replace("FINDING:", "").replace("FINDING", "").strip()
                    effect = f.get("effect_size", "-")
                    ci = f.get("ci_95", "-")
                    n = f.get("n", "-")
                    test = f.get("stat_test", "-")
                    valence = f.get("valence", "-")
                    sections.append(f"| {i} | {title} | {effect} | {ci} | {n} | {test} | {valence} |")
                sections.append("")
        else:
            # Build manuscript skeleton from available data
            sections.append("# Research Manuscript\n")
            if prompt:
                sections.append(f"## Abstract\n\n{prompt}\n")
            if findings:
                sections.append("## Results\n")
                for f in findings:
                    title = f["title"].replace("FINDING:", "").replace("FINDING", "").strip()
                    effect = f.get("effect_size", "")
                    ci = f.get("ci_95", "")
                    n = f.get("n", "")
                    p_val = f.get("p", "")
                    line = f"**{title}**"
                    stats = []
                    if effect:
                        stats.append(f"d={effect}")
                    if ci:
                        stats.append(f"CI {ci}")
                    if n:
                        stats.append(f"N={n}")
                    if p_val:
                        stats.append(f"p={p_val}")
                    if stats:
                        line += f" ({', '.join(stats)})"
                    sections.append(f"\n{line}\n")

            journal = self._read_file(".swarm", "journal.md")
            if journal:
                sections.append(f"## Methods\n\n{journal}\n")

            belief = self._read_file(".swarm", "belief-map.md")
            if belief:
                sections.append(f"## Discussion\n\n{belief}\n")

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # PDF (auto-detects report vs manuscript)
    # ------------------------------------------------------------------

    def build_pdf(self) -> Path | None:
        """Generate a PDF. Auto-detects report vs manuscript format."""
        is_manuscript = self.is_manuscript_format()
        md = self.build_manuscript_markdown() if is_manuscript else self.build_markdown()
        filename = "manuscript.pdf" if is_manuscript else "report.pdf"
        pdf_path = self.swarm / filename

        md_fallback = "manuscript.md" if is_manuscript else "report.md"

        try:
            from fpdf import FPDF  # type: ignore[import-untyped]
        except ImportError:
            return self._fallback_md_file(md, md_fallback)

        def _latin1_safe(text: str) -> str:
            """Replace non-latin1 characters for built-in PDF fonts."""
            return (text
                    .replace("\u2014", "-")   # em-dash
                    .replace("\u2013", "-")   # en-dash
                    .replace("\u2022", "*")   # bullet
                    .replace("\u2018", "'")   # left single quote
                    .replace("\u2019", "'")   # right single quote
                    .replace("\u201c", '"')   # left double quote
                    .replace("\u201d", '"')   # right double quote
                    .replace("\u2026", "...")  # ellipsis
                    .encode("latin-1", "replace").decode("latin-1"))

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        for line in md.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# "):
                pdf.set_font("Helvetica", "B", 18)
                pdf.cell(0, 12, _latin1_safe(stripped.lstrip("# ")), new_x="LMARGIN", new_y="NEXT")
            elif stripped.startswith("## "):
                pdf.set_font("Helvetica", "B", 14)
                pdf.cell(0, 10, _latin1_safe(stripped.lstrip("# ")), new_x="LMARGIN", new_y="NEXT")
            elif stripped.startswith("|"):
                pdf.set_font("Courier", "", 7)
                safe = _latin1_safe(stripped)[:120]  # truncate long table rows
                pdf.cell(0, 5, safe, new_x="LMARGIN", new_y="NEXT")
            elif stripped.startswith("- ") or stripped.startswith("* "):
                pdf.set_font("Helvetica", "", 10)
                safe = _latin1_safe(f"  * {stripped.lstrip('-* ')}")
                try:
                    pdf.multi_cell(0, 6, safe)
                except Exception:
                    pdf.cell(0, 6, safe[:90], new_x="LMARGIN", new_y="NEXT")
            elif stripped:
                pdf.set_font("Helvetica", "", 10)
                try:
                    pdf.multi_cell(0, 6, _latin1_safe(stripped))
                except Exception:
                    pdf.cell(0, 6, _latin1_safe(stripped)[:90], new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.ln(4)

        try:
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf.output(str(pdf_path))
            return pdf_path
        except Exception:
            return self._fallback_md_file(md, md_fallback)

    def _fallback_md_file(self, md: str, filename: str = "report.md") -> Path | None:
        """Write markdown file as fallback when PDF generation fails."""
        md_path = self.swarm / filename
        try:
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(md)
            return md_path
        except OSError:
            return None
