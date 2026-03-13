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
        """Extract FINDING tasks from Beads with interpretation metadata."""
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
            f: dict = {"title": title, "id": t.get("id", "?"),
                       "notes": notes}
            for key in ("EFFECT_SIZE", "CI_95", "N", "STAT_TEST",
                        "VALENCE", "P", "ROBUST", "STAT_REVIEW",
                        "INTERPRETATION", "PRACTICAL_SIGNIFICANCE",
                        "SUPPORTS_HYPOTHESIS", "CONDITIONS"):
                val = _parse_note_value(notes, key)
                if val:
                    f[key.lower()] = val
            # Auto-compute interpretation if not provided by Statistician
            if "interpretation" not in f or "practical_significance" not in f:
                from voronoi.science import interpret_finding
                interp = interpret_finding(t)
                if "practical_significance" not in f:
                    f["practical_significance"] = interp["practical_significance"]
                if "ci_quality" not in f:
                    f["ci_quality"] = interp["ci_quality"]
                if "strength_label" not in f:
                    f["strength_label"] = interp["strength_label"]
                if "interpretation" not in f and interp["interpretation_text"]:
                    f["interpretation"] = interp["interpretation_text"]
            findings.append(f)

        self._findings_cache = findings
        return self._findings_cache

    # ------------------------------------------------------------------
    # Shared renderers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_findings_table(findings: list[dict], placeholder: str = "\u2014") -> list[str]:
        """Render a markdown findings table with strength indicators."""
        rows = ["| # | Finding | Effect | CI | N | Test | Verdict | Strength |",
                "|---|---------|--------|----|---|------|---------|----------|"]
        for i, f in enumerate(findings, 1):
            title = _clean_finding_title(f["title"])
            effect = f.get("effect_size", placeholder)
            ci = f.get("ci_95", placeholder)
            n = f.get("n", placeholder)
            test = f.get("stat_test", placeholder)
            valence = f.get("valence", placeholder)
            strength = f.get("strength_label", f.get("practical_significance", placeholder))
            rows.append(f"| {i} | {title} | {effect} | {ci} | {n} | {test} | {valence} | {strength} |")
        return rows

    @staticmethod
    def _render_findings_interpreted(findings: list[dict]) -> list[str]:
        """Render findings with interpretation and practical significance."""
        lines: list[str] = []
        for i, f in enumerate(findings, 1):
            title = _clean_finding_title(f["title"])
            valence = f.get("valence", "unknown")
            effect = f.get("effect_size", "")
            ci = f.get("ci_95", "")
            p_val = f.get("p", "")
            n = f.get("n", "")
            practical = f.get("practical_significance", "")
            strength = f.get("strength_label", "")
            interp = f.get("interpretation", "")
            supports = f.get("supports_hypothesis", "")

            lines.append(f"### Finding {i}: {title}\n")

            # Statistical summary
            stat_parts = []
            if effect:
                stat_parts.append(f"**Effect size:** d={effect}")
                if practical and practical != "unknown":
                    stat_parts.append(f"({practical} practical effect)")
            if ci:
                stat_parts.append(f"**CI 95%:** {ci}")
            if p_val:
                stat_parts.append(f"**p:** {p_val}")
            if n:
                stat_parts.append(f"**N:** {n}")
            if stat_parts:
                lines.append(" | ".join(stat_parts) + "\n")

            # Verdict and strength
            lines.append(f"**Verdict:** {valence}")
            if strength and strength not in ("unknown", "unreviewed"):
                lines.append(f" | **Evidence strength:** {strength}")
            lines.append("\n")

            # Interpretation
            if interp:
                lines.append(f"**Interpretation:** {interp}\n")

            # Hypothesis link
            if supports:
                lines.append(f"**Supports hypothesis:** {supports}\n")

            lines.append("")
        return lines

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

    def _render_belief_narrative(self) -> str | None:
        """Render belief map with prior->posterior trajectory and evidence links."""
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
            name = h.get("name", "?")
            prior = h.get("prior", "?")
            posterior = h.get("posterior", prior)
            status = h.get("status", "untested")
            evidence = h.get("evidence", [])

            # Build trajectory arrow
            try:
                p_val = float(prior)
                q_val = float(posterior)
                if q_val > p_val + 0.1:
                    arrow = "\u2191"  # up arrow
                elif q_val < p_val - 0.1:
                    arrow = "\u2193"  # down arrow
                else:
                    arrow = "\u2192"  # right arrow (stable)
            except (ValueError, TypeError):
                arrow = "\u2192"

            evidence_str = ""
            if evidence:
                evidence_str = f" (evidence: {', '.join(evidence[:3])})"

            entry = f"- **{name}**: P({prior}) {arrow} P({posterior}) [{status}]{evidence_str}"
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
        from voronoi.science import load_claim_evidence
        reg = load_claim_evidence(self.ws)
        if not reg.claims:
            return None

        lines = []
        for c in reg.claims:
            strength_badge = {"robust": "\u2705", "provisional": "\u26a0\ufe0f",
                              "weak": "\u274c", "unsupported": "\u2b55"}.get(
                c.strength, "\u2753")
            lines.append(f"### {strength_badge} {c.claim_text}\n")
            lines.append(f"**Evidence strength:** {c.strength}")
            if c.finding_ids:
                lines.append(f" | **Supported by:** {', '.join(c.finding_ids)}")
            if c.hypothesis_ids:
                lines.append(f" | **Tests:** {', '.join(c.hypothesis_ids)}")
            lines.append("\n")
            if c.interpretation:
                lines.append(f"{c.interpretation}\n")
            lines.append("")

        # Audit warnings
        if reg.unsupported_claims:
            lines.append("\n**\u26a0\ufe0f Unsupported claims:** "
                         f"{', '.join(reg.unsupported_claims)}\n")
        if reg.orphan_findings:
            lines.append("**\u2139\ufe0f Findings not cited in claims:** "
                         f"{', '.join(reg.orphan_findings)}\n")

        lines.append(f"\n**Evidence coverage:** {reg.coverage_score:.0%} of claims "
                     f"have supporting evidence\n")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Auto-generated Limitations section
    # ------------------------------------------------------------------

    def _render_limitations(self, findings: list[dict]) -> str | None:
        """Auto-generate limitations from fragile, contested, wide-CI findings."""
        limitations: list[str] = []

        # Fragile findings
        fragile = [f for f in findings
                   if f.get("robust", "").lower() == "no"]
        for f in fragile:
            title = _clean_finding_title(f["title"])
            conditions = f.get("conditions", "conditions not documented")
            limitations.append(
                f"- **Fragile result:** {title} "
                f"(not robust under sensitivity analysis; {conditions})"
            )

        # Wide confidence intervals
        for f in findings:
            ci_q = f.get("ci_quality", "")
            if ci_q in ("wide", "very wide"):
                title = _clean_finding_title(f["title"])
                limitations.append(
                    f"- **Imprecise estimate:** {title} "
                    f"(CI quality: {ci_q} — interpret with caution)"
                )

        # Unreviewed findings
        unreviewed = [f for f in findings
                      if f.get("strength_label") in ("unreviewed", None)
                      and not f.get("stat_review")]
        if unreviewed:
            titles = [_clean_finding_title(f["title"]) for f in unreviewed[:3]]
            limitations.append(
                f"- **Unreviewed evidence:** {len(unreviewed)} finding(s) "
                f"not yet reviewed by Statistician ({', '.join(titles)})"
            )

        # Rejected findings
        rejected = [f for f in findings
                    if f.get("strength_label") == "rejected"]
        for f in rejected:
            title = _clean_finding_title(f["title"])
            limitations.append(
                f"- **Rejected by review:** {title} (failed statistical review)"
            )

        # Check for inconclusive hypotheses in belief map
        belief_json = self._read_file(".swarm", "belief-map.json")
        if belief_json:
            try:
                bm_data = json.loads(belief_json)
                for h in bm_data.get("hypotheses", []):
                    if h.get("status") == "inconclusive":
                        limitations.append(
                            f"- **Inconclusive hypothesis:** {h.get('name', '?')} "
                            f"(insufficient evidence to confirm or refute)"
                        )
            except (json.JSONDecodeError, ValueError):
                pass

        return "\n".join(limitations) if limitations else None

    # ------------------------------------------------------------------
    # Cross-finding comparison
    # ------------------------------------------------------------------

    @staticmethod
    def _render_cross_finding_comparison(findings: list[dict]) -> str | None:
        """Rank findings by effect size and narrate relative magnitudes."""
        scored: list[tuple[float, dict]] = []
        for f in findings:
            es = f.get("effect_size", "")
            try:
                val = abs(float(es))
                scored.append((val, f))
            except (ValueError, TypeError):
                continue

        if len(scored) < 2:
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        lines = []
        top = scored[0]
        top_title = _clean_finding_title(top[1]["title"])
        lines.append(f"The strongest effect observed was **{top_title}** "
                     f"(d={top[1].get('effect_size', '?')}"
                     f"{', ' + top[1].get('practical_significance', '') if top[1].get('practical_significance') else ''}).")

        if len(scored) >= 2:
            bot = scored[-1]
            bot_title = _clean_finding_title(bot[1]["title"])
            if top[0] > 0 and bot[0] > 0:
                ratio = top[0] / bot[0]
                lines.append(
                    f"This is {ratio:.1f}x larger than the weakest effect, "
                    f"**{bot_title}** (d={bot[1].get('effect_size', '?')}).")

        # Note any findings with opposing valence
        positive = [f for _, f in scored if f.get("valence", "").lower() == "positive"]
        negative = [f for _, f in scored if f.get("valence", "").lower() == "negative"]
        if positive and negative:
            pos_titles = [_clean_finding_title(f["title"]) for f in positive[:2]]
            neg_titles = [_clean_finding_title(f["title"]) for f in negative[:2]]
            lines.append(
                f"\nNotably, results were mixed: {', '.join(pos_titles)} showed "
                f"positive effects while {', '.join(neg_titles)} showed negative effects."
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Negative results section
    # ------------------------------------------------------------------

    @staticmethod
    def _render_negative_results(findings: list[dict]) -> str | None:
        """Render a dedicated section for negative/inconclusive findings."""
        negative = [f for f in findings
                    if f.get("valence", "").lower() in ("negative", "inconclusive")]
        if not negative:
            return None

        lines = ["The following hypotheses were tested and did not produce "
                 "the expected positive result. These negative results are "
                 "scientifically valuable as they narrow the solution space "
                 "and prevent future wasted effort.\n"]
        for f in negative:
            title = _clean_finding_title(f["title"])
            effect = f.get("effect_size", "")
            p_val = f.get("p", "")
            valence = f.get("valence", "")
            stat_parts = []
            if effect:
                stat_parts.append(f"d={effect}")
            if p_val:
                stat_parts.append(f"p={p_val}")
            stat_str = f" ({', '.join(stat_parts)})" if stat_parts else ""
            lines.append(f"- **{title}**{stat_str} \u2014 {valence}")
        return "\n".join(lines)

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

        journal = self._read_file(".swarm", "journal.md")
        if journal:
            sections.append(f"## Methodology & Journal\n\n{journal}\n")

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

            journal = self._read_file(".swarm", "journal.md")
            if journal:
                sections.append(f"## Methods\n\n{journal}\n")

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
            self.ws / "paper.tex",
            self.ws / "main.tex",
            self.ws / "manuscript.tex",
        ]
        for d in self.ws.glob("demos/*/"):
            candidates.append(d / "paper.tex")
            candidates.append(d / "main.tex")
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
