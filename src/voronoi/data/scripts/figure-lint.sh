#!/bin/bash
set -euo pipefail

# =============================================================================
# figure-lint.sh — Verify all \includegraphics references resolve to real files
#
# Usage: ./scripts/figure-lint.sh [workspace-dir]
#
# Scans all .tex files for \includegraphics references, checks each file exists
# on disk, and reports missing figures. Exits 0 if all present, 1 if any missing.
#
# This is a hard gate: if a referenced figure doesn't exist, LaTeX compilation
# will produce a paper with blank boxes or errors. Catch it BEFORE compilation.
# =============================================================================

WORKSPACE="${1:-.}"

# Find all .tex files
TEX_FILES=$(find "$WORKSPACE" -name '*.tex' -not -path '*/.git/*' -not -path '*/node_modules/*' 2>/dev/null || true)

if [ -z "$TEX_FILES" ]; then
    echo "figure-lint: No .tex files found in $WORKSPACE — skipping"
    exit 0
fi

echo "figure-lint: Scanning .tex files for \\includegraphics references..."

TOTAL=0
PRESENT=0
MISSING=0
MISSING_LIST=""

while IFS= read -r tex_file; do
    [ -z "$tex_file" ] && continue
    TEX_DIR=$(dirname "$tex_file")

    # Extract all \includegraphics references (with or without options)
    # Handles: \includegraphics{path}, \includegraphics[opts]{path}
    REFS=$(grep -oP '\\includegraphics(\[[^\]]*\])?\{([^}]+)\}' "$tex_file" 2>/dev/null | \
           sed 's/.*{\([^}]*\)}/\1/' || true)

    while IFS= read -r ref; do
        [ -z "$ref" ] && continue
        TOTAL=$((TOTAL + 1))

        # Try multiple resolution paths (LaTeX search order)
        FOUND=false

        # 1. Exact path from .tex file directory
        if [ -f "${TEX_DIR}/${ref}" ]; then
            FOUND=true
        # 2. Exact path from workspace root
        elif [ -f "${WORKSPACE}/${ref}" ]; then
            FOUND=true
        # 3. With common extensions if no extension given
        elif [[ "$ref" != *.* ]]; then
            for ext in .pdf .png .jpg .jpeg .eps .svg; do
                if [ -f "${TEX_DIR}/${ref}${ext}" ] || [ -f "${WORKSPACE}/${ref}${ext}" ]; then
                    FOUND=true
                    break
                fi
            done
        fi

        if [ "$FOUND" = true ]; then
            PRESENT=$((PRESENT + 1))
        else
            MISSING=$((MISSING + 1))
            MISSING_LIST="${MISSING_LIST}  ✗ ${ref}  (referenced in $(basename "$tex_file"))\n"
        fi
    done <<< "$REFS"
done <<< "$TEX_FILES"

echo "figure-lint: ${PRESENT}/${TOTAL} figures present"

if [ "$MISSING" -gt 0 ]; then
    echo ""
    echo "figure-lint: ${MISSING} MISSING figure(s):"
    echo -e "$MISSING_LIST"
    echo ""
    echo "figure-lint: FAILED — generate missing figures before compilation"

    # Check if plotting scripts exist that could generate missing figures
    PLOT_SCRIPTS=$(find "$WORKSPACE" -name 'plot_*.py' -o -name 'generate_*.py' -o -name 'make_figures.py' 2>/dev/null | head -5 || true)
    if [ -n "$PLOT_SCRIPTS" ]; then
        echo ""
        echo "figure-lint: Found plotting scripts that may help:"
        echo "$PLOT_SCRIPTS" | while IFS= read -r script; do
            echo "  → $script"
        done
    fi

    exit 1
fi

echo "figure-lint: PASSED — all referenced figures exist"
exit 0
