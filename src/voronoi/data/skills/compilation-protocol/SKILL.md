---
name: compilation-protocol
description: >
  Skill for compiling LaTeX papers with hard dependency checking. Ensures all
  figures, bibliography, and data dependencies are resolved before compilation,
  and verifies the output PDF is complete.
---

# LaTeX Compilation Protocol Skill

Compile LaTeX papers with full pre-flight validation and post-compilation verification.
Prevents the "blank PDF" problem by enforcing figure existence as a hard gate.

## When to Use

Use this skill when your task involves compiling a LaTeX document into a PDF,
especially for scientific papers produced by Voronoi investigations.

## The Three Phases

### PHASE 1: Pre-Flight Checks (MANDATORY — do this BEFORE running any compiler)

```bash
# 1. Find all .tex files
find . -name '*.tex' -not -path './.git/*'

# 2. Check \includegraphics references
echo "=== Figure References ==="
grep -rn 'includegraphics' *.tex | while IFS= read -r line; do
    REF=$(echo "$line" | sed 's/.*{\([^}]*\)}/\1/')
    # Try exact path, then with common extensions
    if [ -f "$REF" ]; then
        echo "  ✓ $REF"
    elif [ -f "${REF}.pdf" ] || [ -f "${REF}.png" ] || [ -f "${REF}.jpg" ]; then
        echo "  ✓ $REF (with extension)"
    else
        echo "  ✗ MISSING: $REF (from $line)"
    fi
done

# 3. Check \bibliography references
echo "=== Bibliography References ==="
grep -rn 'bibliography{' *.tex | while IFS= read -r line; do
    BIB=$(echo "$line" | sed 's/.*{\([^}]*\)}/\1/')
    if [ -f "${BIB}.bib" ] || [ -f "$BIB" ]; then
        echo "  ✓ $BIB"
    else
        echo "  ✗ MISSING: $BIB"
    fi
done

# 4. Check \input / \include references
echo "=== Input File References ==="
grep -rn '\\input{\|\\include{' *.tex | while IFS= read -r line; do
    REF=$(echo "$line" | sed 's/.*{\([^}]*\)}/\1/')
    if [ -f "$REF" ] || [ -f "${REF}.tex" ]; then
        echo "  ✓ $REF"
    else
        echo "  ✗ MISSING: $REF"
    fi
done

# 5. Run figure-lint if available
if [ -x ./scripts/figure-lint.sh ]; then
    ./scripts/figure-lint.sh .
fi
```

**STOP HERE if any figures are missing.** Generate them first using the `figure-generation` skill.

### PHASE 2: Compilation

Try compilers in this order (stop at first success):

```bash
# Detect the main LaTeX file (Scribe writes paper.tex by convention)
TEX_FILE="paper.tex"
if [ ! -f "$TEX_FILE" ]; then
    # Fallback: look for main.tex or any .tex with \documentclass
    for candidate in main.tex manuscript.tex; do
        if [ -f "$candidate" ]; then TEX_FILE="$candidate"; break; fi
    done
fi
TEX_STEM="${TEX_FILE%.tex}"

# Option A: Tectonic (best — auto-downloads packages, no sudo)
if command -v tectonic >/dev/null 2>&1; then
    tectonic "$TEX_FILE"
    echo "Compiled with tectonic"

# Option B: latexmk (handles multiple passes automatically)
elif command -v latexmk >/dev/null 2>&1; then
    latexmk -pdf -interaction=nonstopmode "$TEX_FILE"
    echo "Compiled with latexmk"

# Option C: pdflatex (manual multi-pass)
elif command -v pdflatex >/dev/null 2>&1; then
    pdflatex -interaction=nonstopmode "$TEX_FILE"
    bibtex "$TEX_STEM" 2>/dev/null || true
    pdflatex -interaction=nonstopmode "$TEX_FILE"
    pdflatex -interaction=nonstopmode "$TEX_FILE"
    echo "Compiled with pdflatex"

# Option D: Install tectonic (no sudo needed)
else
    echo "No LaTeX compiler found — installing tectonic..."
    # macOS
    if command -v brew >/dev/null 2>&1; then
        brew install tectonic
    # Linux
    else
        mkdir -p ~/.local/bin
        curl -SL https://github.com/tectonic-typesetting/tectonic/releases/latest/download/tectonic-0.15.0-x86_64-unknown-linux-gnu.tar.gz | tar xz -C ~/.local/bin/
        export PATH="$HOME/.local/bin:$PATH"
    fi
    tectonic "$TEX_FILE"
fi
```

### Fix Common Compilation Errors

| Error | Fix |
|-------|-----|
| `! LaTeX Error: File 'X.sty' not found` | Install the package: `tlmgr install X` or use tectonic (auto-installs) |
| `! Missing $ inserted` | Math mode issue — check for unescaped `_`, `%`, `&` in text |
| `! Undefined control sequence` | Missing `\usepackage{}` for the command |
| `! I can't find file 'figures/X'` | Figure missing — run figure-generation skill first |
| `Runaway argument?` | Unmatched braces `{}` — check for missing closing brace |

### PHASE 3: Post-Compilation Verification (MANDATORY)

```bash
# 1. Verify PDF exists and has content
ls -la "${TEX_STEM}.pdf"
# Should be > 10KB for any real paper

# 2. Check page count
python3 -c "
import subprocess, sys
pdf = '${TEX_STEM}.pdf'
result = subprocess.run(['pdfinfo', pdf], capture_output=True, text=True)
if result.returncode == 0:
    for line in result.stdout.split('\n'):
        if 'Pages:' in line:
            print(line.strip())
else:
    import os
    size = os.path.getsize(pdf)
    print(f'PDF size: {size:,} bytes')
    if size < 10000:
        print('WARNING: PDF suspiciously small — may be empty')
" 2>/dev/null || echo "PDF exists (pdfinfo not available for page count)"

# 3. Check for undefined references (grep the log)
if [ -f "${TEX_STEM}.log" ]; then
    UNDEF=$(grep -c 'undefined' "${TEX_STEM}.log" 2>/dev/null || echo "0")
    if [ "$UNDEF" -gt 0 ]; then
        echo "WARNING: $UNDEF undefined reference(s) in ${TEX_STEM}.log"
        grep 'undefined' "${TEX_STEM}.log" | head -5
    fi

    # Check for missing figures specifically
    MISSING_FIG=$(grep -c 'cannot find image file' "${TEX_STEM}.log" 2>/dev/null || echo "0")
    if [ "$MISSING_FIG" -gt 0 ]; then
        echo "ERROR: $MISSING_FIG missing figure(s) detected in compilation log"
        grep 'cannot find image file' "${TEX_STEM}.log"
    fi
fi

# 4. Copy to .swarm for delivery
cp "${TEX_STEM}.pdf" .swarm/report.pdf
echo "✓ PDF copied to .swarm/report.pdf"

# 5. Commit
git add "${TEX_STEM}.pdf" .swarm/report.pdf
git commit -m "Compile final paper PDF"
# If `origin` exists, also run: git push origin <branch>

# 6. Update Beads
bd update <task-id> --notes "COMPILATION:SUCCESS | PAGES:<N> | SIZE:<bytes>"
```

## Artifact Contracts for Compilation Tasks

When the orchestrator creates a compilation task, it should declare:

```bash
bd create "Compile final paper" -t task -p 1
bd update <id> --notes "REQUIRES:paper.tex,figures/"
bd update <id> --notes "PRODUCES:.swarm/report.pdf"
bd update <id> --notes "GATE:output/validation_report.json"  # if validation exists
```

This ensures:
- spawn-agent.sh blocks dispatch until all figure files exist
- merge-agent.sh blocks merge until report.pdf is produced
- The orchestrator can't skip compilation
