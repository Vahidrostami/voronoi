"""PDF generation strategy chain for investigation reports.

Supports: pre-compiled PDFs, LaTeX compilation, pandoc, fpdf2, markdown fallback.
Extracted from ReportGenerator.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


def which(cmd: str) -> bool:
    """Check if a command is available on PATH."""
    return shutil.which(cmd) is not None


def latin1_safe(text: str) -> str:
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


def find_precompiled_pdf(workspace: Path, swarm: Path) -> Path | None:
    """Find an agent-compiled PDF in the workspace."""
    canonical = swarm / "report.pdf"
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
        for pdf in workspace.glob(pattern):
            if pdf.stat().st_size > 1000:
                return pdf

    tex_main = find_latex_main(workspace)
    if tex_main:
        pdf_sibling = tex_main.with_suffix(".pdf")
        if pdf_sibling.exists() and pdf_sibling.stat().st_size > 1000:
            return pdf_sibling

    return None


def find_latex_main(workspace: Path) -> Path | None:
    """Find the main LaTeX file in the workspace."""
    candidates = [
        workspace / "paper.tex",
        workspace / "main.tex",
        workspace / "manuscript.tex",
    ]
    for d in workspace.glob("demos/*/"):
        candidates.append(d / "paper.tex")
        candidates.append(d / "main.tex")
    for tex in workspace.glob("*.tex"):
        if tex not in candidates:
            candidates.append(tex)
    for tex in workspace.glob("*/*.tex"):
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


def compile_latex(tex_path: Path) -> Path | None:
    """Compile a LaTeX file to PDF."""
    tex_dir = tex_path.parent
    stem = tex_path.stem
    pdf_out = tex_dir / f"{stem}.pdf"

    for compiler in [
        ["latexmk", "-pdf", "-interaction=nonstopmode", str(tex_path)],
        ["pdflatex", "-interaction=nonstopmode", str(tex_path)],
        ["tectonic", str(tex_path)],
    ]:
        if not which(compiler[0]):
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

    pandoc_cmd = find_pandoc()
    if pandoc_cmd:
        for engine in ["tectonic", "pdflatex", "xelatex"]:
            if not which(engine):
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


def find_pandoc() -> str | None:
    """Find pandoc — system binary or pypandoc_binary."""
    if which("pandoc"):
        return "pandoc"
    try:
        import pypandoc  # type: ignore[import-untyped]
        return pypandoc.get_pandoc_path()
    except (ImportError, OSError):
        return None


def latex_to_markdown(tex_main: Path, ws_root: Path) -> str | None:
    """Extract readable content from LaTeX files as markdown.

    Last-resort converter for when no LaTeX compiler or pandoc is available.
    """
    tex_dir = tex_main.parent
    ws_resolved = ws_root.resolve()

    def _read_tex(path: Path) -> str:
        try:
            return path.read_text()
        except OSError:
            return ""

    def _resolve_inputs(content: str, base: Path) -> str:
        r"""Inline \input{file} and \include{file} with path-traversal guard."""
        def _replace(m: re.Match) -> str:
            name = m.group(1)
            if not name.endswith(".tex"):
                name += ".tex"
            child = (base / name).resolve()
            try:
                child.relative_to(ws_resolved)
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


def try_pandoc_pdf(md: str, pdf_path: Path, workspace: Path, swarm: Path) -> Path | None:
    """Strategy: markdown → PDF via pandoc."""
    pandoc_cmd = find_pandoc()
    if not pandoc_cmd or not md:
        return None
    md_tmp = swarm / "_tmp_report.md"
    try:
        md_tmp.parent.mkdir(parents=True, exist_ok=True)
        md_tmp.write_text(md)
        for engine in ["tectonic", "pdflatex", "xelatex"]:
            if not which(engine):
                continue
            try:
                subprocess.run(
                    [pandoc_cmd, str(md_tmp), "-o", str(pdf_path),
                     f"--pdf-engine={engine}",
                     "-V", "geometry:margin=1in"],
                    capture_output=True, timeout=120,
                    cwd=str(workspace),
                )
                if pdf_path.exists():
                    return pdf_path
            except (subprocess.TimeoutExpired, OSError):
                continue
    finally:
        md_tmp.unlink(missing_ok=True)
    return None


def try_fpdf2(md: str, pdf_path: Path) -> Path | None:
    """Strategy: markdown → PDF via fpdf2 (basic typesetting)."""
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
            pdf.cell(0, 12, latin1_safe(stripped.lstrip("# ")), new_x="LMARGIN", new_y="NEXT")
        elif stripped.startswith("## "):
            pdf.set_font("Helvetica", "B", 14)
            pdf.cell(0, 10, latin1_safe(stripped.lstrip("# ")), new_x="LMARGIN", new_y="NEXT")
        elif stripped.startswith("|"):
            pdf.set_font("Courier", "", 7)
            safe = latin1_safe(stripped)[:120]
            pdf.cell(0, 5, safe, new_x="LMARGIN", new_y="NEXT")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            pdf.set_font("Helvetica", "", 10)
            safe = latin1_safe(f"  * {stripped.lstrip('-* ')}")
            try:
                pdf.multi_cell(0, 6, safe)
            except Exception:
                pdf.cell(0, 6, safe[:90], new_x="LMARGIN", new_y="NEXT")
        elif stripped:
            pdf.set_font("Helvetica", "", 10)
            try:
                pdf.multi_cell(0, 6, latin1_safe(stripped))
            except Exception:
                pdf.cell(0, 6, latin1_safe(stripped)[:90], new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.ln(4)

    try:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf.output(str(pdf_path))
        return pdf_path
    except Exception:
        return None
