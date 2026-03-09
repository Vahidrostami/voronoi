"""Report generation \u2014 teaser, report PDF, and scientific manuscript PDF.

Collects deliverable, findings, belief map, and journal from a
workspace and assembles them into:
  1. A short Telegram teaser (3-5 bullet points)
  2. A full Markdown report (for standard/analytical investigations)
  3. A scientific manuscript (for scientific/experimental rigor)
  4. A PDF file (optional, requires fpdf2)

The output format is determined by the investigation's mode and rigor
level, which are set at classification time.  When mode/rigor are not
available (e.g. CLI path), a content-based fallback detects academic
headings in the deliverable.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from voronoi.beads import run_bd as _run_bd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _which(cmd: str) -> bool:
    """Check if a command is available on PATH."""
    return shutil.which(cmd) is not None


def _clean_finding_title(title: str) -> str:
    """Strip the leading *FINDING:* tag without damaging body text."""
    for prefix in ("FINDING:", "FINDING"):
        if title.upper().startswith(prefix):
            title = title[len(prefix):]
            break
    return title.strip()


def _parse_note_value(notes: str, key: str) -> str | None:
    """Extract a value for *key* from Beads-style notes.

    Handles both single-key lines (``KEY:value``) and pipe-separated
    multi-key lines (``KEY1:val1 | KEY2:val2``).
    """
    key_upper = key.upper()
    for line in notes.split("\n"):
        if key_upper not in line.upper():
            continue
        # Split on pipe first to handle multi-key lines
        for segment in line.split("|"):
            segment = segment.strip()
            if not segment.upper().startswith(key_upper):
                continue
            _, _, val = segment.partition(":")
            val = val.strip()
            if val:
                return val
    return None


def _latin1_safe(text: str) -> str:
    """Replace non-latin1 characters for built-in PDF fonts."""
    return (text
            .replace("\u2014", "-")
            .replace("\u2013", "-")
            .replace("\u2022", "*")
            .replace("\u2018", "'")
            .replace("\u2019", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2026", "...")
            .encode("latin-1", "replace").decode("latin-1"))


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Builds teasers, markdown reports, and PDFs from investigation workspaces.

    Parameters
    ----------
    workspace_path : Path
        Root of the investigation workspace.
    mode : str | None
        Investigation mode (investigate/explore/build/experiment).
        When provided, drives format selection directly.
    rigor : str | None
        Rigor level (standard/analytical/scientific/experimental).
        When provided, drives format selection directly.
    """

    _PAPER_SECTIONS = frozenset({
        "abstract", "introduction", "methods", "methodology",
        "results", "discussion", "conclusion", "related work",
        "references", "background",
    })

    def __init__(self, workspace_path: Path, *,
                 mode: str | None = None, rigor: str | None = None):
        self.ws = workspace_path
        self.swarm = workspace_path / ".swarm"
        self.mode = mode
        self.rigor = rigor
        self._findings_cache: list[dict] | None = None

    # ------------------------------------------------------------------
    # Format decision
    # ------------------------------------------------------------------

    @property
    def is_manuscript(self) -> bool:
        """Whether this investigation should produce a manuscript."""
        if self.rigor in ("scientific", "experimental"):
            return True
        if self.rigor is not None:
            return False
        # Fallback: content-based detection when metadata unavailable
        return self._detect_manuscript_fallback()

    @property
    def doc_type(self) -> str:
        """Human-readable document type label."""
        return "manuscript" if self.is_manuscript else "report"

    def _detect_manuscript_fallback(self) -> bool:
        """Content-based detection \u2014 only used when mode/rigor unknown."""
        deliverable = self._read_file(".swarm", "deliverable.md")
        if not deliverable:
            return False
        headings: set[str] = set()
        for line in deliverable.split("\n"):
            if not line.strip().startswith("#"):
                continue
            heading = line.strip().lstrip("#").strip().lower()
            if heading:
                headings.add(heading)
        return len(headings & self._PAPER_SECTIONS) >= 3

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
        """Extract FINDING tasks from Beads (cached per instance)."""
        if self._findings_cache is not None:
            return self._findings_cache

        code, stdout = _run_bd("list", "--json", cwd=str(self.ws))
        if code != 0:
            self._findings_cache = []
            return self._findings_cache
        try:
            tasks = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            self._findings_cache = []
            return self._findings_cache

        findings: list[dict] = []
        for t in tasks:
            title = t.get("title", "")
            if "FINDING" not in title.upper():
                continue
            notes = t.get("notes", "")
            f: dict = {"title": title, "id": t.get("id", "?")}
            for key in ("EFFECT_SIZE", "CI_95", "N", "STAT_TEST", "VALENCE", "P", "ROBUST"):
                val = _parse_note_value(notes, key)
                if val:
                    f[key.lower()] = val
            findings.append(f)

        self._findings_cache = findings
        return self._findings_cache

    # ------------------------------------------------------------------
    # Shared renderers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_findings_table(findings: list[dict], placeholder: str = "\u2014") -> list[str]:
        """Render a markdown findings table."""
        rows = ["| # | Finding | Effect | CI | N | Test | Verdict |",
                "|---|---------|--------|----|---|------|---------|"]
        for i, f in enumerate(findings, 1):
            title = _clean_finding_title(f["title"])
            effect = f.get("effect_size", placeholder)
            ci = f.get("ci_95", placeholder)
            n = f.get("n", placeholder)
            test = f.get("stat_test", placeholder)
            valence = f.get("valence", placeholder)
            rows.append(f"| {i} | {title} | {effect} | {ci} | {n} | {test} | {valence} |")
        return rows

    @staticmethod
    def _pick_headline(findings: list[dict]) -> dict:
        """Pick the finding with the largest numeric effect size."""
        best, best_val = None, -1.0
        for f in findings:
            es = f.get("effect_size", "")
            try:
                val = abs(float(es))
                if val > best_val:
                    best, best_val = f, val
            except (ValueError, TypeError):
                continue
        return best if best is not None else findings[0]

    @staticmethod
    def _valence_emoji(valence: str) -> str:
        return {"positive": "\u2705", "negative": "\u274c"}.get(valence.lower(), "\u2753")

    # ------------------------------------------------------------------
    # Belief map rendering
    # ------------------------------------------------------------------

    def _render_belief_map(self) -> str | None:
        """Return belief map as markdown, or None."""
        belief = self._read_file(".swarm", "belief-map.md")
        if belief:
            return belief

        belief_json = self._read_file(".swarm", "belief-map.json")
        if not belief_json:
            return None
        try:
            data = json.loads(belief_json)
        except (json.JSONDecodeError, ValueError):
            return None
        lines = []
        for h in data.get("hypotheses", []):
            lines.append(
                f"- **{h.get('name', '?')}**: P={h.get('prior', '?')} [{h.get('status', '?')}]"
            )
        return "\n".join(lines) if lines else None

    # ------------------------------------------------------------------
    # Teaser (Telegram message)
    # ------------------------------------------------------------------

    def build_teaser(self, investigation_id: int, question: str,
                     total_tasks: int, closed_tasks: int,
                     elapsed_min: float, *, mode: str = "investigate",
                     codename: str = "") -> str:
        """3-5 bullet point teaser for Telegram."""
        from voronoi.gateway.progress import MODE_EMOJI, progress_bar

        findings = self._get_findings()
        mode_emoji = MODE_EMOJI.get(mode, "\U0001f537")
        label = codename or f"#{investigation_id}"

        lines = [f"\U0001f3c1 *Voronoi \u00b7 {label}* {mode_emoji} COMPLETE \u00b7 {elapsed_min:.0f}min\n"]
        lines.append(f"_{question}_\n")

        if findings:
            headline = self._pick_headline(findings)

            title = _clean_finding_title(headline["title"])
            h_emoji = self._valence_emoji(headline.get("valence", ""))
            stat_parts = []
            if headline.get("effect_size"):
                stat_parts.append(f"d={headline['effect_size']}")
            if headline.get("ci_95"):
                stat_parts.append(f"CI {headline['ci_95']}")
            if headline.get("p"):
                stat_parts.append(f"p={headline['p']}")
            if headline.get("n"):
                stat_parts.append(f"N={headline['n']}")

            lines.append("\u2501" * 20)
            lines.append("\U0001f4a1 *HEADLINE*")
            lines.append(f"{h_emoji} {title}")
            if stat_parts:
                lines.append(" \u00b7 ".join(stat_parts))
            lines.append("\u2501" * 20 + "\n")

            # Remaining findings (skip headline)
            others = [f for f in findings if f["id"] != headline["id"]]
            if others:
                lines.append("*All findings:*")
                for f in others[:5]:
                    emoji = self._valence_emoji(f.get("valence", ""))
                    f_title = _clean_finding_title(f["title"])
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
        lines.append(f"{bar} \u00b7 {finding_count} finding{'s' if finding_count != 1 else ''}")

        lines.append(f"\n\U0001f4ce Full {self.doc_type} attached")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Unified Markdown entry point
    # ------------------------------------------------------------------

    def build_auto_markdown(self) -> str:
        """Build the appropriate markdown format based on mode/rigor."""
        if self.is_manuscript:
            return self.build_manuscript_markdown()
        return self.build_markdown()

    # ------------------------------------------------------------------
    # Full Markdown report
    # ------------------------------------------------------------------

    def build_markdown(self) -> str:
        """Assemble the full investigation report as Markdown."""
        sections: list[str] = []

        prompt = self._read_file("PROMPT.md")
        if prompt:
            sections.append("# Investigation Report\n")
            sections.append(f"## Question\n\n{prompt}\n")
        else:
            sections.append("# Investigation Report\n")

        findings = self._get_findings()
        if findings:
            sections.append("## Findings\n")
            sections.extend(self._render_findings_table(findings))
            sections.append("")

        belief = self._render_belief_map()
        if belief:
            sections.append(f"## Belief Map\n\n{belief}\n")

        journal = self._read_file(".swarm", "journal.md")
        if journal:
            sections.append(f"## Methodology & Journal\n\n{journal}\n")

        deliverable = self._read_file(".swarm", "deliverable.md")
        if deliverable:
            sections.append(f"## Conclusion\n\n{deliverable}\n")

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # Scientific manuscript Markdown
    # ------------------------------------------------------------------

    def build_manuscript_markdown(self) -> str:
        """Assemble a structured scientific manuscript from the deliverable + evidence."""
        sections: list[str] = []
        deliverable = self._read_file(".swarm", "deliverable.md") or ""
        prompt = self._read_file("PROMPT.md") or ""
        findings = self._get_findings()

        if deliverable:
            sections.append(deliverable)
            # Append findings table if not already embedded
            if findings and "finding" not in deliverable.lower():
                sections.append("\n## Appendix: Evidence Summary\n")
                sections.extend(self._render_findings_table(findings, placeholder="-"))
                sections.append("")
        else:
            sections.append("# Research Manuscript\n")
            if prompt:
                sections.append(f"## Abstract\n\n{prompt}\n")
            if findings:
                sections.append("## Results\n")
                for f in findings:
                    title = _clean_finding_title(f["title"])
                    stats = []
                    if f.get("effect_size"):
                        stats.append(f"d={f['effect_size']}")
                    if f.get("ci_95"):
                        stats.append(f"CI {f['ci_95']}")
                    if f.get("n"):
                        stats.append(f"N={f['n']}")
                    if f.get("p"):
                        stats.append(f"p={f['p']}")
                    line = f"**{title}**"
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
    # Pre-compiled PDF detection
    # ------------------------------------------------------------------

    def _find_precompiled_pdf(self) -> Path | None:
        """Find an agent-compiled PDF in the workspace."""
        canonical = self.swarm / "report.pdf"
        if canonical.exists() and canonical.stat().st_size > 1000:
            return canonical

        search_patterns = [
            "output/paper/*.pdf",
            "output/*.pdf",
            "demos/*/output/paper/*.pdf",
            "demos/*/output/*.pdf",
            "paper/*.pdf",
        ]
        for pattern in search_patterns:
            for pdf in self.ws.glob(pattern):
                if pdf.stat().st_size > 1000:
                    return pdf

        tex_main = self._find_latex_main()
        if tex_main:
            pdf_sibling = tex_main.with_suffix(".pdf")
            if pdf_sibling.exists() and pdf_sibling.stat().st_size > 1000:
                return pdf_sibling

        return None

    # ------------------------------------------------------------------
    # LaTeX detection & compilation
    # ------------------------------------------------------------------

    def _find_latex_main(self) -> Path | None:
        """Find the main LaTeX file in the workspace."""
        candidates = [
            self.ws / "main.tex",
            self.ws / "paper.tex",
            self.ws / "manuscript.tex",
        ]
        for d in self.ws.glob("demos/*/"):
            candidates.append(d / "main.tex")
            candidates.append(d / "paper.tex")
        for tex in self.ws.glob("*.tex"):
            if tex not in candidates:
                candidates.append(tex)
        for tex in self.ws.glob("*/*.tex"):
            if tex not in candidates:
                candidates.append(tex)

        for c in candidates:
            if c.exists():
                try:
                    content = c.read_text()
                    if r"\documentclass" in content or r"\begin{document}" in content:
                        return c
                except OSError:
                    continue
        return None

    def _compile_latex(self, tex_path: Path) -> Path | None:
        """Compile a LaTeX file to PDF using latexmk, pdflatex, tectonic, or pandoc."""
        tex_dir = tex_path.parent
        stem = tex_path.stem
        pdf_out = tex_dir / f"{stem}.pdf"

        for compiler in [
            ["latexmk", "-pdf", "-interaction=nonstopmode", str(tex_path)],
            ["pdflatex", "-interaction=nonstopmode", str(tex_path)],
            ["tectonic", str(tex_path)],
        ]:
            if not _which(compiler[0]):
                continue
            try:
                passes = 2 if compiler[0] == "pdflatex" else 1
                for _ in range(passes):
                    subprocess.run(
                        compiler, capture_output=True, timeout=120,
                        cwd=str(tex_dir),
                    )
                if pdf_out.exists():
                    return pdf_out
            except (subprocess.TimeoutExpired, OSError):
                continue

        pandoc_cmd = self._find_pandoc()
        if pandoc_cmd:
            for engine in ["tectonic", "pdflatex", "xelatex"]:
                if not _which(engine):
                    continue
                try:
                    subprocess.run(
                        [pandoc_cmd, str(tex_path), "-o", str(pdf_out),
                         f"--pdf-engine={engine}"],
                        capture_output=True, timeout=120, cwd=str(tex_dir),
                    )
                    if pdf_out.exists():
                        return pdf_out
                except (subprocess.TimeoutExpired, OSError):
                    continue

        return None

    @staticmethod
    def _find_pandoc() -> str | None:
        """Find pandoc \u2014 system binary or pypandoc_binary."""
        if _which("pandoc"):
            return "pandoc"
        try:
            import pypandoc  # type: ignore[import-untyped]
            return pypandoc.get_pandoc_path()
        except (ImportError, OSError):
            return None

    # ------------------------------------------------------------------
    # LaTeX \u2192 Markdown (best-effort for fpdf2 fallback)
    # ------------------------------------------------------------------

    def _latex_to_markdown(self, tex_main: Path) -> str | None:
        """Extract readable content from LaTeX files as markdown.

        Last-resort converter for when no LaTeX compiler or pandoc is
        available.
        """
        tex_dir = tex_main.parent
        ws_root = self.ws.resolve()

        def _read_tex(path: Path) -> str:
            try:
                return path.read_text()
            except OSError:
                return ""

        def _resolve_inputs(content: str, base: Path) -> str:
            r"""Inline \input{file} and \include{file} \u2014 with path-traversal guard."""
            def _replace(m: re.Match) -> str:
                name = m.group(1)
                if not name.endswith(".tex"):
                    name += ".tex"
                child = (base / name).resolve()
                # Block escape from workspace
                try:
                    child.relative_to(ws_root)
                except ValueError:
                    return ""
                if child.exists():
                    return _read_tex(child)
                return ""
            content = re.sub(r"\\input\{([^}]+)\}", _replace, content)
            content = re.sub(r"\\include\{([^}]+)\}", _replace, content)
            return content

        raw = _read_tex(tex_main)
        if not raw:
            return None

        raw = _resolve_inputs(raw, tex_dir)

        # Strip preamble
        match = re.search(r"\\begin\{document\}", raw)
        if match:
            raw = raw[match.end():]
        match = re.search(r"\\end\{document\}", raw)
        if match:
            raw = raw[:match.start()]

        lines: list[str] = []
        for line in raw.split("\n"):
            s = line.strip()
            if s.startswith("%"):
                continue
            s = re.sub(r"\\section\*?\{([^}]+)\}", r"# \1", s)
            s = re.sub(r"\\subsection\*?\{([^}]+)\}", r"## \1", s)
            s = re.sub(r"\\subsubsection\*?\{([^}]+)\}", r"### \1", s)
            s = re.sub(r"\\textbf\{([^}]+)\}", r"**\1**", s)
            s = re.sub(r"\\textit\{([^}]+)\}", r"*\1*", s)
            s = re.sub(r"\\emph\{([^}]+)\}", r"*\1*", s)
            s = re.sub(r"\\cite\{([^}]+)\}", r"[\1]", s)
            s = re.sub(r"\\ref\{([^}]+)\}", r"[\1]", s)
            s = re.sub(r"\\label\{[^}]+\}", "", s)
            s = re.sub(r"\\maketitle", "", s)
            s = re.sub(r"\\begin\{(abstract|itemize|enumerate|table|figure|center)\}", "", s)
            s = re.sub(r"\\end\{(abstract|itemize|enumerate|table|figure|center)\}", "", s)
            s = re.sub(r"\\item\s*", "- ", s)
            s = re.sub(r"\\caption\{([^}]+)\}", r"*\1*", s)
            s = re.sub(r"\$([^$]+)\$", r"\1", s)
            s = re.sub(r"\\[a-zA-Z]+\{[^}]*\}", "", s)
            s = re.sub(r"\\[a-zA-Z]+", "", s)
            s = s.replace("{", "").replace("}", "")
            s = s.strip()
            lines.append(s if s else "")

        content = "\n".join(lines).strip()
        return content if len(content) > 200 else None

    # ------------------------------------------------------------------
    # PDF \u2014 strategy chain
    # ------------------------------------------------------------------

    def _try_precompiled_pdf(self) -> Path | None:
        """Strategy 1: find and copy agent-compiled PDF."""
        pre_compiled = self._find_precompiled_pdf()
        if not pre_compiled:
            return None
        dest = self.swarm / "report.pdf"
        if pre_compiled == dest:
            return dest
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(pre_compiled), str(dest))
            return dest
        except OSError:
            return pre_compiled

    def _try_latex_compile(self) -> Path | None:
        """Strategy 2: compile LaTeX sources."""
        tex_main = self._find_latex_main()
        if not tex_main:
            return None
        compiled = self._compile_latex(tex_main)
        if not compiled:
            return None
        dest = self.swarm / "report.pdf"
        try:
            shutil.copy2(str(compiled), str(dest))
            return dest
        except OSError:
            return compiled

    def _try_pandoc_pdf(self, md: str, pdf_path: Path) -> Path | None:
        """Strategy 3: markdown \u2192 PDF via pandoc."""
        pandoc_cmd = self._find_pandoc()
        if not pandoc_cmd or not md:
            return None
        md_tmp = self.swarm / "_tmp_report.md"
        try:
            md_tmp.parent.mkdir(parents=True, exist_ok=True)
            md_tmp.write_text(md)
            for engine in ["tectonic", "pdflatex", "xelatex"]:
                if not _which(engine):
                    continue
                try:
                    subprocess.run(
                        [pandoc_cmd, str(md_tmp), "-o", str(pdf_path),
                         f"--pdf-engine={engine}",
                         "-V", "geometry:margin=1in"],
                        capture_output=True, timeout=120,
                        cwd=str(self.ws),
                    )
                    if pdf_path.exists():
                        return pdf_path
                except (subprocess.TimeoutExpired, OSError):
                    continue
        finally:
            md_tmp.unlink(missing_ok=True)
        return None

    def _try_fpdf2(self, md: str, pdf_path: Path) -> Path | None:
        """Strategy 4: markdown \u2192 PDF via fpdf2 (basic typesetting)."""
        try:
            from fpdf import FPDF  # type: ignore[import-untyped]
        except ImportError:
            return None

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
                safe = _latin1_safe(stripped)[:120]
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
            return None

    def _fallback_md_file(self, md: str, filename: str) -> Path | None:
        """Write markdown file as fallback when PDF generation fails."""
        md_path = self.swarm / filename
        try:
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(md)
            return md_path
        except OSError:
            return None

    def build_pdf(self) -> Path | None:
        """Generate a PDF.  Chains: pre-compiled \u2192 LaTeX \u2192 pandoc \u2192 fpdf2 \u2192 .md."""
        # 1. Agent-compiled PDF
        result = self._try_precompiled_pdf()
        if result:
            return result

        # 2. LaTeX compilation
        result = self._try_latex_compile()
        if result:
            return result

        # 3. Build markdown content for remaining strategies
        tex_main = self._find_latex_main()
        md_from_tex = self._latex_to_markdown(tex_main) if tex_main else None

        if md_from_tex:
            md = md_from_tex
        else:
            md = self.build_auto_markdown()

        filename = "manuscript" if self.is_manuscript else "report"
        pdf_path = self.swarm / f"{filename}.pdf"

        # 4. Pandoc
        result = self._try_pandoc_pdf(md, pdf_path)
        if result:
            return result

        # 5. fpdf2
        result = self._try_fpdf2(md, pdf_path)
        if result:
            return result

        # 6. Fallback to .md
        return self._fallback_md_file(md, f"{filename}.md")
