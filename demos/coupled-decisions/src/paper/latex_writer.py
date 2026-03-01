"""Assemble the full LaTeX paper from section templates, generated figures/tables, and bibliography."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Dict

from .results_analyzer import ResultsAnalyzer
from .figure_generator import FigureGenerator
from .table_generator import TableGenerator


class LaTeXWriter:
    """Assembles a complete LaTeX paper from templates and generated content."""

    def __init__(self, analyzer: ResultsAnalyzer, output_dir: str | Path | None = None):
        self.analyzer = analyzer
        self.pkg_dir = Path(__file__).resolve().parent
        self.sections_dir = self.pkg_dir / "sections"
        self.bib_path = self.pkg_dir / "references.bib"
        if output_dir is None:
            output_dir = Path(__file__).resolve().parents[2] / "output" / "paper"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build(self) -> Path:
        """Generate figures, tables, assemble paper, and optionally compile."""
        # Generate figures
        fig_gen = FigureGenerator(self.analyzer, self.output_dir / "figures")
        fig_gen.generate_all()

        # Generate tables
        tbl_gen = TableGenerator(self.analyzer, self.output_dir / "tables")
        tbl_gen.generate_all()

        # Copy bibliography
        bib_dest = self.output_dir / "references.bib"
        shutil.copy2(self.bib_path, bib_dest)

        # Assemble paper
        paper_path = self._assemble()

        # Try to compile
        self._compile(paper_path)

        return paper_path

    # ------------------------------------------------------------------
    # Placeholder replacement
    # ------------------------------------------------------------------
    def _placeholders(self) -> Dict[str, str]:
        """Build placeholder → value mapping from results."""
        summary = self.analyzer.paper_summary()
        enc = self.analyzer.encoding_stats()
        abl = self.analyzer.ablation_stats()
        pipe = self.analyzer.pipeline_stats()

        stages = pipe["stages"]
        stage_map = {}
        for i, (_, val) in enumerate(stages):
            if val >= 1e6:
                stage_map[str(i)] = f"${val:.0e}$".replace("e+0", r" \times 10^{").replace("e+", r" \times 10^{") + "}"
            else:
                stage_map[str(i)] = f"{int(val):,}"

        # Ablation per-config
        abl_rows = {r["config"]: r for r in abl["table"]}

        return {
            r"\EFFECTSDISCOVERED{}": str(summary["effects_discovered"]),
            r"\EFFECTSTOTAL{}": str(summary["effects_total"]),
            r"\BESTABLATION{}": str(abl["best_ablation_effects"]),
            r"\PIPELINEINPUT{}": f"$\\sim 10^{{18}}$",
            r"\PIPELINEOUTPUT{}": str(pipe["final_count"]),
            r"\NSKUS{}": str(self.analyzer.scenario["skus"]),
            r"\NSTORES{}": str(self.analyzer.scenario["stores"]),
            r"\NWEEKS{}": str(self.analyzer.scenario["weeks"]),
            r"\NLEVERS{}": str(len(self.analyzer.scenario["levers"])),
            r"\FIDELITYQUANT{}": str(enc["fidelity"]["quantitative"]),
            r"\FIDELITYPOLICY{}": str(enc["fidelity"]["policy"]),
            r"\FIDELITYEXPERT{}": str(enc["fidelity"]["expert"]),
            r"\AVGFIDELITY{}": str(enc["avg_fidelity"]),
            r"\CROSSTYPEACCURACY{}": f"{enc['full_system_accuracy']:.0%}",
            r"\RAWCONCATACCURACY{}": f"{enc['raw_concat_accuracy']:.0%}",
            r"\LLMBASELINEACCURACY{}": f"{enc['llm_baseline_accuracy']:.0%}",
            r"\CONFLICTSDETECTED{}": str(enc["conflicts_detected"]),
            r"\CONFLICTSTOTAL{}": str(enc["conflicts_total"]),
            r"\FULLPRECISION{}": str(abl["full_precision"]),
            r"\FULLRECALL{}": str(abl["full_recall"]),
            r"\NOCOUPLINGEFFECTS{}": str(abl_rows.get("no_coupling", {}).get("effects_found", "N/A")),
            r"\NOPIPELINEPRECISION{}": str(abl_rows.get("no_pipeline", {}).get("precision", "N/A")),
            # Pipeline stages with index argument
            r"\PIPELINESTAGE{1}": stage_map.get("1", "N/A"),
            r"\PIPELINESTAGE{2}": stage_map.get("2", "N/A"),
            r"\PIPELINESTAGE{3}": stage_map.get("3", "N/A"),
            # Ground-truth coverage
            r"\GTCOVERAGE{1}": f"{pipe['coverage'][0]:.0%}" if len(pipe["coverage"]) > 0 else "N/A",
            r"\GTCOVERAGE{2}": f"{pipe['coverage'][1]:.0%}" if len(pipe["coverage"]) > 1 else "N/A",
            r"\GTCOVERAGE{3}": f"{pipe['coverage'][2]:.0%}" if len(pipe["coverage"]) > 2 else "N/A",
        }

    def _replace_placeholders(self, text: str) -> str:
        """Replace all \\PLACEHOLDER{} tokens in text with actual values."""
        placeholders = self._placeholders()
        for key, val in placeholders.items():
            text = text.replace(key, val)
        return text

    # ------------------------------------------------------------------
    # Section loading
    # ------------------------------------------------------------------
    def _load_section(self, filename: str) -> str:
        path = self.sections_dir / filename
        if path.exists():
            return self._replace_placeholders(path.read_text(encoding="utf-8"))
        return f"% Section template not found: {filename}\n"

    # ------------------------------------------------------------------
    # Paper assembly
    # ------------------------------------------------------------------
    def _assemble(self) -> Path:
        preamble = self._preamble()
        abstract = self._abstract()

        sections = [
            self._load_section("01_introduction.tex"),
            self._load_section("02_problem_characterization.tex"),
            self._load_section("03_encoding_layer.tex"),
            self._load_section("04_pipeline.tex"),
            self._load_section("05_experimental_setup.tex"),
            self._load_section("06_results.tex"),
            self._load_section("07_discussion.tex"),
            self._load_section("08_generalization.tex"),
            self._load_section("09_conclusion.tex"),
        ]

        appendices = [
            self._load_section("appendix_a.tex"),
            self._load_section("appendix_b.tex"),
        ]

        body = "\n\n".join(sections)
        appendix_body = "\n\n".join(appendices)

        paper = f"""{preamble}

\\begin{{document}}

\\maketitle

{abstract}

{body}

\\bibliographystyle{{plainnat}}
\\bibliography{{references}}

{appendix_body}

\\end{{document}}
"""
        path = self.output_dir / "paper.tex"
        path.write_text(paper, encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Preamble
    # ------------------------------------------------------------------
    def _preamble(self) -> str:
        return r"""\documentclass[11pt,a4paper]{article}

% Packages
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb,amsfonts}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{hyperref}
\usepackage[numbers]{natbib}
\usepackage{xcolor}
\usepackage{geometry}
\usepackage{enumitem}
\usepackage{caption}
\usepackage{subcaption}

\geometry{margin=1in}

% Custom colors
\definecolor{navy}{HTML}{1B2A4A}
\definecolor{teal}{HTML}{2A9D8F}

\hypersetup{
    colorlinks=true,
    linkcolor=navy,
    citecolor=teal,
    urlcolor=teal
}

\title{Navigating Coupled Decision Spaces with Fragmented and Heterogeneous Knowledge:\\A System of Agents for Reasoning}

\author{%
    Research Team\\
    Coupled Decisions Framework\\
    \texttt{coupled-decisions@example.org}
}

\date{\today}"""

    # ------------------------------------------------------------------
    # Abstract
    # ------------------------------------------------------------------
    def _abstract(self) -> str:
        summary = self.analyzer.paper_summary()
        return r"""\begin{abstract}
A broad class of applied decision problems---including revenue growth management, precision medicine, and supply chain design---share a common structure: combinatorial decision spaces over interdependent levers, knowledge fragmented across incompatible sources, and cognitive bottlenecks preventing joint reasoning.
We identify three structural invariants characterizing this problem class (lever coupling, knowledge heterogeneity, cognitive assembly bottleneck) and show that addressing any single invariant in isolation is insufficient.
We introduce a multimodal encoding layer that preserves epistemic metadata across knowledge types, achieving """ + f"{summary['cross_type_accuracy']:.0%}" + r""" cross-type query accuracy versus """ + f"{summary['baseline_accuracy']:.0%}" + r""" for raw concatenation.
A progressive three-stage pipeline compresses ${\sim}10^{18}$ candidate combinations to """ + str(summary['pipeline_output']) + r""" actionable recommendations with zero constraint violations and complete ground-truth coverage.
The full system discovers """ + str(summary['effects_discovered']) + r""" of """ + str(summary['effects_total']) + r""" planted interaction effects in a synthetic Revenue Growth Management scenario, and generalizes to precision medicine and supply chain domains without architectural modification.
\end{abstract}
"""

    # ------------------------------------------------------------------
    # Compilation
    # ------------------------------------------------------------------
    def _compile(self, tex_path: Path) -> bool:
        """Attempt to compile with pdflatex if available."""
        import subprocess

        if not shutil.which("pdflatex"):
            return False

        try:
            for _ in range(2):  # Run twice for references
                subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", "-output-directory",
                     str(tex_path.parent), str(tex_path)],
                    capture_output=True, timeout=60, cwd=str(tex_path.parent)
                )
            # Run bibtex
            aux_path = tex_path.with_suffix(".aux")
            if aux_path.exists():
                subprocess.run(
                    ["bibtex", str(aux_path.stem)],
                    capture_output=True, timeout=30, cwd=str(tex_path.parent)
                )
                # Two more pdflatex passes
                for _ in range(2):
                    subprocess.run(
                        ["pdflatex", "-interaction=nonstopmode", "-output-directory",
                         str(tex_path.parent), str(tex_path)],
                        capture_output=True, timeout=60, cwd=str(tex_path.parent)
                    )
            return (tex_path.with_suffix(".pdf")).exists()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
