"""Generate all 7 LaTeX tables from experiment results."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .results_analyzer import ResultsAnalyzer


class TableGenerator:
    """Generates LaTeX table fragments for inclusion in the paper."""

    def __init__(self, analyzer: ResultsAnalyzer, output_dir: str | Path | None = None):
        self.analyzer = analyzer
        if output_dir is None:
            output_dir = Path(__file__).resolve().parents[2] / "output" / "paper" / "tables"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_all(self) -> List[Path]:
        """Generate all 7 tables and return paths."""
        methods = [
            self.table1_domains,
            self.table2_encoding_summary,
            self.table3_agent_specs,
            self.table4_quality_dimensions,
            self.table5_ablation_results,
            self.table6_top_interventions,
            self.table7_generalization,
        ]
        return [m() for m in methods]

    def _write(self, filename: str, content: str) -> Path:
        path = self.output_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Table 1: Decision domains sharing 3 structural invariants
    # ------------------------------------------------------------------
    def table1_domains(self) -> Path:
        tex = r"""\begin{table}[ht]
\centering
\caption{Decision domains sharing the three structural invariants.}
\label{tab:domains}
\small
\begin{tabular}{lcccp{4cm}}
\toprule
\textbf{Domain} & \textbf{Lever Coupling} & \textbf{Knowledge Het.} & \textbf{Cognitive Asm.} & \textbf{Example Levers} \\
\midrule
Revenue Growth Mgmt & \checkmark & \checkmark & \checkmark & Pricing, promotion, assortment, distribution, pack-price \\
Precision Medicine & \checkmark & \checkmark & \checkmark & Drug, dose, timing \\
Materials Discovery & \checkmark & \checkmark & \checkmark & Composition, processing, structure \\
Supply Chain Design & \checkmark & \checkmark & \checkmark & Sourcing, inventory, routing \\
Financial Risk Mgmt & \checkmark & \checkmark & \checkmark & Hedging, allocation, timing \\
\bottomrule
\end{tabular}
\end{table}"""
        return self._write("table1_domains.tex", tex)

    # ------------------------------------------------------------------
    # Table 2: Knowledge type encoding summary
    # ------------------------------------------------------------------
    def table2_encoding_summary(self) -> Path:
        enc = self.analyzer.encoding_stats()
        fid = enc["fidelity"]
        tex = r"""\begin{table}[ht]
\centering
\caption{Knowledge type encoding: input forms, encoded representations, and fidelity scores.}
\label{tab:encoding}
\small
\begin{tabular}{llll c}
\toprule
\textbf{Knowledge Type} & \textbf{Raw Input} & \textbf{Encoded Form} & \textbf{Properties Preserved} & \textbf{Fidelity} \\
\midrule
Quantitative & CSV time series & Statistical Profile & Distribution, trend, CI & """ + f"{fid['quantitative']:.3f}" + r""" \\
Policy & JSON rules & Constraint Vector & Bounds, hardness, scope & """ + f"{fid['policy']:.3f}" + r""" \\
Expert & JSON beliefs & Temporal Belief & Confidence, decay, basis & """ + f"{fid['expert']:.3f}" + r""" \\
\bottomrule
\end{tabular}
\end{table}"""
        return self._write("table2_encoding_summary.tex", tex)

    # ------------------------------------------------------------------
    # Table 3: Diagnostic agent specifications
    # ------------------------------------------------------------------
    def table3_agent_specs(self) -> Path:
        tex = r"""\begin{table}[ht]
\centering
\caption{Diagnostic agent specifications: analytical dimensions and I/O.}
\label{tab:agents}
\small
\begin{tabular}{llp{3.5cm}p{3.5cm}}
\toprule
\textbf{Agent} & \textbf{Dimension} & \textbf{Primary Input} & \textbf{Output} \\
\midrule
Elasticity & Price sensitivity & Own/cross-price elasticities & Lever sensitivity rankings \\
Interaction & Lever coupling & Pairwise interaction statistics & Synergy/conflict flags \\
Constraint & Feasibility & Policy constraint vectors & Feasible region map \\
Temporal & Time dynamics & Trend/seasonality decomposition & Structural break alerts \\
Portfolio & SKU effects & Cross-SKU correlations & Cannibalization/halo map \\
\bottomrule
\end{tabular}
\end{table}"""
        return self._write("table3_agent_specs.tex", tex)

    # ------------------------------------------------------------------
    # Table 4: Quality gate dimensions and weights
    # ------------------------------------------------------------------
    def table4_quality_dimensions(self) -> Path:
        tex = r"""\begin{table}[ht]
\centering
\caption{Quality gate scoring dimensions.}
\label{tab:quality}
\small
\begin{tabular}{lcp{6cm}}
\toprule
\textbf{Dimension} & \textbf{Weight} & \textbf{Description} \\
\midrule
Evidence Density & 0.25 & Number of independent evidence sources supporting the intervention \\
Constraint Alignment & 0.25 & Compliance with hard/soft policy constraints (veto on hard violation) \\
Actionability & 0.20 & Specificity of lever, direction, magnitude, and scope \\
Testability & 0.15 & Whether the intervention can be A/B tested with measurable outcomes \\
Novelty & 0.15 & Non-obviousness; penalizes findings any single-lever analysis would produce \\
\bottomrule
\end{tabular}
\end{table}"""
        return self._write("table4_quality_dimensions.tex", tex)

    # ------------------------------------------------------------------
    # Table 5: Ablation experiment results
    # ------------------------------------------------------------------
    def table5_ablation_results(self) -> Path:
        abl = self.analyzer.ablation_stats()
        rows = abl["table"]

        header = r"""\begin{table}[ht]
\centering
\caption{Ablation study results across four system configurations.}
\label{tab:ablation}
\small
\begin{tabular}{lccccc}
\toprule
\textbf{Configuration} & \textbf{Effects (/5)} & \textbf{Precision} & \textbf{Recall} & \textbf{Violations} & \textbf{Revenue $\Delta$} \\
\midrule
"""
        body = ""
        labels = {
            "full_system": "Full System",
            "no_coupling": "No Coupling",
            "no_encoding": "No Encoding",
            "no_pipeline": "No Pipeline",
        }
        for r in rows:
            label = labels.get(r["config"], r["config"])
            rev = f"{r['revenue_impact']:+.0%}" if isinstance(r["revenue_impact"], float) else str(r["revenue_impact"])
            body += (
                f"{label} & {r['effects_found']} & {r['precision']:.2f} & "
                f"{r['recall']:.2f} & {r['violations']} & {rev} \\\\\n"
            )

        footer = r"""\bottomrule
\end{tabular}
\end{table}"""
        return self._write("table5_ablation_results.tex", header + body + footer)

    # ------------------------------------------------------------------
    # Table 6: Top interventions
    # ------------------------------------------------------------------
    def table6_top_interventions(self) -> Path:
        interventions = self.analyzer.intervention_stats()[:10]

        header = r"""\begin{table}[ht]
\centering
\caption{Top recommended interventions with quality scores.}
\label{tab:interventions}
\small
\begin{tabular}{clcccl}
\toprule
\textbf{Rank} & \textbf{Lever} & \textbf{Quality} & \textbf{Evidence} & \textbf{Constraints} & \textbf{Revenue} \\
\midrule
"""
        body = ""
        for iv in interventions:
            lever = iv["lever"].replace("_", r"\_")
            body += (
                f"{iv['rank']} & {lever} & {iv['quality_score']:.2f} & "
                f"{iv['evidence_density']:.2f} & {iv['constraint_alignment']:.2f} & "
                f"{iv['revenue_impact']} \\\\\n"
            )

        footer = r"""\bottomrule
\end{tabular}
\end{table}"""
        return self._write("table6_top_interventions.tex", header + body + footer)

    # ------------------------------------------------------------------
    # Table 7: Cross-domain generalization
    # ------------------------------------------------------------------
    def table7_generalization(self) -> Path:
        gen = self.analyzer.generalization_stats()
        abl = self.analyzer.ablation_stats()

        header = r"""\begin{table}[ht]
\centering
\caption{Cross-domain generalization results.}
\label{tab:generalization}
\small
\begin{tabular}{lccc}
\toprule
\textbf{Domain} & \textbf{Effects Found} & \textbf{Effects Total} & \textbf{Pipeline Functional} \\
\midrule
"""
        body = f"RGM (BevCo) & {abl['full_effects']} & 5 & \\checkmark \\\\\n"
        for d in gen["domains"]:
            check = r"\checkmark" if d["pipeline_functional"] else r"$\times$"
            body += f"{d['domain']} & {d['effects_found']} & {d['effects_total']} & {check} \\\\\n"

        footer = r"""\bottomrule
\end{tabular}
\end{table}"""
        return self._write("table7_generalization.tex", header + body + footer)
