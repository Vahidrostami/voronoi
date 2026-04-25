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
import shutil
from pathlib import Path

from voronoi.utils import clean_finding_title as _clean_finding_title
from voronoi.gateway.evidence import (
    get_findings,
    render_findings_table,
    render_findings_interpreted,
    pick_headline,
    valence_emoji,
    render_evidence_chain,
    render_limitations,
    render_cross_finding_comparison,
    render_negative_results,
    humanize_stats,
)
from voronoi.gateway.pdf import (
    find_precompiled_pdf,
    find_latex_main,
    compile_latex,
    find_pandoc,
    latex_to_markdown,
    try_pandoc_pdf,
    try_fpdf2,
)


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
        Investigation mode (discover/prove).
        When provided, drives format selection directly.
    rigor : str | None
        Rigor level (adaptive/scientific/experimental).
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
        """Delegate to evidence module with caching."""
        if self._findings_cache is not None:
            return self._findings_cache
        self._findings_cache = get_findings(self.ws)
        return self._findings_cache

    # ------------------------------------------------------------------
    # Shared renderers — delegate to evidence module
    # ------------------------------------------------------------------

    @staticmethod
    def _render_findings_table(findings: list[dict], placeholder: str = "\u2014") -> list[str]:
        return render_findings_table(findings, placeholder)

    @staticmethod
    def _render_findings_interpreted(findings: list[dict]) -> list[str]:
        return render_findings_interpreted(findings)

    @staticmethod
    def _pick_headline(findings: list[dict]) -> dict:
        return pick_headline(findings)

    @staticmethod
    def _valence_emoji(valence: str) -> str:
        return valence_emoji(valence)

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
            name = h.get("name") or h.get("id") or "?"
            confidence = h.get("confidence", "")
            status = h.get("status", "untested")
            label = confidence.upper() if confidence else f"P={h.get('prior', '?')}"
            entry = f"- **{name}**: {label} [{status}]"
            rationale = h.get("rationale", "")
            if rationale:
                entry += f"\n  _{rationale}_"
            lines.append(entry)
        return "\n".join(lines) if lines else None

    def _render_belief_narrative(self) -> str | None:
        """Render belief map with confidence tiers, rationale, and evidence links."""
        belief_json = self._read_file(".swarm", "belief-map.json")
        if not belief_json:
            return self._render_belief_map()
        try:
            data = json.loads(belief_json)
        except (json.JSONDecodeError, ValueError):
            return self._render_belief_map()

        hypotheses = data.get("hypotheses", [])
        if not hypotheses:
            return self._render_belief_map()

        lines = []
        confirmed = []
        refuted = []
        inconclusive = []

        for h in hypotheses:
            name = h.get("name") or h.get("id") or "?"
            confidence = h.get("confidence", "")
            status = h.get("status", "untested")
            evidence = h.get("evidence", [])
            rationale = h.get("rationale", "")
            next_test = h.get("next_test", "")

            # Confidence badge
            if confidence:
                conf_label = confidence.upper()
            else:
                prior = h.get("prior", "?")
                posterior = h.get("posterior", prior)
                try:
                    p_val = float(prior)
                    q_val = float(posterior)
                    if q_val > p_val + 0.1:
                        arrow = "\u2191"
                    elif q_val < p_val - 0.1:
                        arrow = "\u2193"
                    else:
                        arrow = "\u2192"
                except (ValueError, TypeError):
                    arrow = "\u2192"
                conf_label = f"P({prior}) {arrow} P({posterior})"

            evidence_str = ""
            if evidence:
                evidence_str = f" (evidence: {', '.join(evidence[:3])})"

            entry = f"- **{name}**: {conf_label} [{status}]{evidence_str}"
            if rationale:
                entry += f"\n  _{rationale}_"
            if next_test:
                entry += f"\n  Next: {next_test}"
            lines.append(entry)

            if status == "confirmed":
                confirmed.append(name)
            elif status == "refuted":
                refuted.append(name)
            elif status == "inconclusive":
                inconclusive.append(name)

        # Summary line
        summary_parts = []
        if confirmed:
            summary_parts.append(f"{len(confirmed)} confirmed")
        if refuted:
            summary_parts.append(f"{len(refuted)} refuted")
        if inconclusive:
            summary_parts.append(f"{len(inconclusive)} inconclusive")
        if summary_parts:
            lines.append(f"\n**Summary:** {', '.join(summary_parts)} "
                         f"out of {len(hypotheses)} hypotheses")

        return "\n".join(lines) if lines else None

    # ------------------------------------------------------------------
    # Evidence chain from claim-evidence registry
    # ------------------------------------------------------------------

    def _render_evidence_chain(self) -> str | None:
        """Render claim-evidence traceability from .swarm/claim-evidence.json."""
        return render_evidence_chain(self.ws)

    # ------------------------------------------------------------------
    # Auto-generated Limitations section
    # ------------------------------------------------------------------

    def _render_limitations(self, findings: list[dict]) -> str | None:
        """Auto-generate limitations from fragile, contested, wide-CI findings."""
        return render_limitations(findings, self.ws)

    # ------------------------------------------------------------------
    # Cross-finding comparison
    # ------------------------------------------------------------------

    @staticmethod
    def _render_cross_finding_comparison(findings: list[dict]) -> str | None:
        return render_cross_finding_comparison(findings)

    # ------------------------------------------------------------------
    # Negative results section
    # ------------------------------------------------------------------

    @staticmethod
    def _render_negative_results(findings: list[dict]) -> str | None:
        return render_negative_results(findings)

    # ------------------------------------------------------------------
    # Human-readable stat description for Telegram
    # ------------------------------------------------------------------

    @staticmethod
    def _humanize_stats(finding: dict) -> str:
        return humanize_stats(finding)

    # ------------------------------------------------------------------
    # Teaser (Telegram message)
    # ------------------------------------------------------------------

    def build_teaser(self, investigation_id: int, question: str,
                     total_tasks: int, closed_tasks: int,
                     elapsed_min: float, *, mode: str = "discover",
                     codename: str = "") -> str:
        """3-5 bullet point teaser for Telegram."""
        from voronoi.gateway.progress import MODE_EMOJI

        findings = self._get_findings()
        mode_emoji = MODE_EMOJI.get(mode, "\U0001f537")
        label = codename or f"#{investigation_id}"

        lines = [f"\U0001f3c1 *{label}* {mode_emoji} COMPLETE \u00b7 {elapsed_min:.0f}min\n"]
        lines.append(f"_{question}_\n")

        if findings:
            headline = self._pick_headline(findings)

            title = _clean_finding_title(headline["title"])
            h_emoji = self._valence_emoji(headline.get("valence", ""))
            stat_desc = self._humanize_stats(headline)

            lines.append("\u2501" * 20)
            lines.append("\U0001f4a1 *The big one:*")
            lines.append(f"{h_emoji} {title}")
            if stat_desc:
                lines.append(stat_desc)
            lines.append("\u2501" * 20 + "\n")

            # Remaining findings (skip headline)
            others = [f for f in findings if f["id"] != headline["id"]]
            if others:
                lines.append("*Also found:*")
                for f in others[:5]:
                    emoji = self._valence_emoji(f.get("valence", ""))
                    f_title = _clean_finding_title(f["title"])
                    f_desc = self._humanize_stats(f)
                    entry = f"{emoji} {f_title}"
                    if f_desc:
                        entry += f" ({f_desc})"
                    lines.append(f"  {entry}")
                lines.append("")

        finding_count = len(findings)
        lines.append(f"{finding_count} finding{'s' if finding_count != 1 else ''} \u00b7 Full {self.doc_type} attached \U0001f4ce")
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
        """Assemble a structured investigation report with evidence chain."""
        sections: list[str] = []

        prompt = self._read_file("PROMPT.md")
        if prompt:
            sections.append("# Investigation Report\n")
            sections.append(f"## Question\n\n{prompt}\n")
        else:
            sections.append("# Investigation Report\n")

        # Executive summary from deliverable (first paragraph)
        deliverable = self._read_file(".swarm", "deliverable.md")
        if deliverable:
            first_para = deliverable.split("\n\n")[0]
            if len(first_para) > 50:
                sections.append(f"## Executive Summary\n\n{first_para}\n")

        findings = self._get_findings()

        # Evidence chain (if claim-evidence registry exists)
        evidence_chain = self._render_evidence_chain()
        if evidence_chain:
            sections.append(f"## Evidence Chain\n\n{evidence_chain}\n")

        # Findings with interpretation
        if findings:
            sections.append("## Findings\n")
            interpreted = self._render_findings_interpreted(findings)
            if interpreted:
                sections.extend(interpreted)
            sections.append("")
            # Summary table
            sections.append("### Summary Table\n")
            sections.extend(self._render_findings_table(findings))
            sections.append("")

        # Cross-finding comparison
        if findings and len(findings) >= 2:
            comparison = self._render_cross_finding_comparison(findings)
            if comparison:
                sections.append(f"### Comparative Analysis\n\n{comparison}\n")

        # Negative results (dedicated section)
        if findings:
            negatives = self._render_negative_results(findings)
            if negatives:
                sections.append(f"## Negative & Inconclusive Results\n\n{negatives}\n")

        # Belief map with narrative trajectory
        belief = self._render_belief_narrative()
        if belief:
            sections.append(f"## Hypothesis Trajectory\n\n{belief}\n")
        else:
            belief_simple = self._render_belief_map()
            if belief_simple:
                sections.append(f"## Belief Map\n\n{belief_simple}\n")

        # Full deliverable
        if deliverable:
            sections.append(f"## Detailed Conclusion\n\n{deliverable}\n")

        # Auto-generated limitations
        if findings:
            limitations = self._render_limitations(findings)
            if limitations:
                sections.append(f"## Limitations & Caveats\n\n{limitations}\n")

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # Scientific manuscript Markdown
    # ------------------------------------------------------------------

    def build_manuscript_markdown(self) -> str:
        """Assemble a structured scientific manuscript with full evidence trail."""
        sections: list[str] = []
        deliverable = self._read_file(".swarm", "deliverable.md") or ""
        prompt = self._read_file("PROMPT.md") or ""
        findings = self._get_findings()

        if deliverable:
            sections.append(deliverable)

            # Append evidence chain if available and not already in deliverable
            evidence_chain = self._render_evidence_chain()
            if evidence_chain and "evidence chain" not in deliverable.lower():
                sections.append("\n## Evidence Chain\n")
                sections.append(evidence_chain)

            # Append interpreted findings if not already embedded
            if findings and "finding" not in deliverable.lower():
                sections.append("\n## Appendix A: Evidence Summary\n")
                sections.extend(self._render_findings_interpreted(findings))
                sections.append("\n### Summary Table\n")
                sections.extend(self._render_findings_table(findings, placeholder="-"))
                sections.append("")

            # Cross-finding comparison
            if findings and len(findings) >= 2:
                comparison = self._render_cross_finding_comparison(findings)
                if comparison and "comparative" not in deliverable.lower():
                    sections.append(f"\n### Comparative Analysis\n\n{comparison}\n")

            # Negative results
            if findings:
                negatives = self._render_negative_results(findings)
                if negatives and "negative result" not in deliverable.lower():
                    sections.append(f"\n## Appendix B: Negative Results\n\n{negatives}\n")

            # Auto-generated limitations
            if findings:
                limitations = self._render_limitations(findings)
                if limitations and "limitation" not in deliverable.lower():
                    sections.append(f"\n## Limitations\n\n{limitations}\n")

        else:
            # No deliverable — build manuscript skeleton from evidence
            sections.append("# Research Manuscript\n")
            if prompt:
                sections.append(f"## Abstract\n\n{prompt}\n")

            if findings:
                sections.append("## Results\n")
                sections.extend(self._render_findings_interpreted(findings))

                if len(findings) >= 2:
                    comparison = self._render_cross_finding_comparison(findings)
                    if comparison:
                        sections.append(f"\n### Comparative Analysis\n\n{comparison}\n")

                negatives = self._render_negative_results(findings)
                if negatives:
                    sections.append(f"\n### Negative Results\n\n{negatives}\n")

            # Belief map narrative for Discussion
            belief_narrative = self._render_belief_narrative()
            if belief_narrative:
                sections.append(f"## Discussion\n\n{belief_narrative}\n")
            else:
                belief = self._read_file(".swarm", "belief-map.md")
                if belief:
                    sections.append(f"## Discussion\n\n{belief}\n")

            # Evidence chain
            evidence_chain = self._render_evidence_chain()
            if evidence_chain:
                sections.append(f"## Evidence Chain\n\n{evidence_chain}\n")

            if findings:
                limitations = self._render_limitations(findings)
                if limitations:
                    sections.append(f"## Limitations\n\n{limitations}\n")

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # Pre-compiled PDF detection
    # ------------------------------------------------------------------

    def _find_precompiled_pdf(self) -> Path | None:
        """Find an agent-compiled PDF in the workspace.

        Prioritises files named ``paper.pdf``, ``report.pdf``, or
        ``manuscript.pdf``.  Broad directory globs (``output/*.pdf``)
        are filtered to exclude figure / chart PDFs that are not the
        main deliverable.
        """
        return find_precompiled_pdf(self.ws, self.swarm)

    # ------------------------------------------------------------------
    # LaTeX detection & compilation
    # ------------------------------------------------------------------

    def _find_latex_main(self) -> Path | None:
        """Find the main LaTeX file in the workspace."""
        return find_latex_main(self.ws)

    def _compile_latex(self, tex_path: Path) -> Path | None:
        """Compile a LaTeX file to PDF using latexmk, pdflatex, tectonic, or pandoc."""
        return compile_latex(tex_path)

    @staticmethod
    def _find_pandoc() -> str | None:
        """Find pandoc \u2014 system binary or pypandoc_binary."""
        return find_pandoc()

    # ------------------------------------------------------------------
    # LaTeX \u2192 Markdown (best-effort for fpdf2 fallback)
    # ------------------------------------------------------------------

    def _latex_to_markdown(self, tex_main: Path) -> str | None:
        """Extract readable content from LaTeX files as markdown.

        Last-resort converter for when no LaTeX compiler or pandoc is
        available.
        """
        return latex_to_markdown(tex_main, self.ws)

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
        return try_pandoc_pdf(md, pdf_path, self.ws, self.swarm)

    def _try_fpdf2(self, md: str, pdf_path: Path) -> Path | None:
        """Strategy 4: markdown \u2192 PDF via fpdf2 (basic typesetting)."""
        return try_fpdf2(md, pdf_path)

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
        """Generate a PDF.  Chains: pre-compiled → LaTeX → pandoc → fpdf2 → .md."""
        # 1. Agent-compiled PDF (publication-quality)
        result = self._try_precompiled_pdf()
        if result:
            self._copy_to_demo_output(result)
            return result

        # 2. LaTeX compilation (publication-quality)
        result = self._try_latex_compile()
        if result:
            self._copy_to_demo_output(result)
            return result

        # Strategies below produce auto-generated output from markdown —
        # adequate for Telegram delivery but NOT publication-quality.
        # These are NOT copied to demos/*/output/paper/.

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

    def _copy_to_demo_output(self, source: Path) -> None:
        """Copy a publication-quality PDF to the demo output/paper/ directory.

        Only called for pre-compiled or LaTeX-compiled PDFs — never for
        auto-generated markdown conversions.  Looks for a single
        ``demos/<name>/`` directory in the workspace and copies the file
        into ``demos/<name>/output/paper/``.
        """
        try:
            demo_dirs = [d for d in self.ws.glob("demos/*/") if d.is_dir()]
            if len(demo_dirs) != 1:
                return  # Ambiguous or no demo directory
            paper_dir = demo_dirs[0] / "output" / "paper"
            paper_dir.mkdir(parents=True, exist_ok=True)
            dest = paper_dir / source.name
            shutil.copy2(source, dest)
        except OSError:
            pass
