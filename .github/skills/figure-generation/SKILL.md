---
name: figure-generation
description: >
  Skill for generating scientific figures from experimental data. Ensures every
  figure referenced in LaTeX documents exists on disk before compilation, preventing
  blank PDFs and broken references.
---

# Figure Generation Skill

Ensures all figures are generated from data before LaTeX compilation. This prevents the
most common cause of blank/broken PDFs: missing figure files.

## When to Use

Use this skill when your task PRODUCES any figure files (PNG, PDF, SVG) or any LaTeX
document that references figures via `\includegraphics`.

## The Problem This Solves

LaTeX references figures by path (e.g., `\includegraphics{figures/ablation.pdf}`).
If the file doesn't exist at compile time, the paper either:
- Fails to compile entirely
- Compiles with blank boxes where figures should be
- Shows `[?]` reference markers

This is the #1 cause of "sometimes figures, sometimes not" in Voronoi investigations.

## Protocol

### Phase 1: Inventory (BEFORE writing any code)

List ALL figures your task must produce and declare them in Beads:

```bash
# Declare outputs
bd update <task-id> --notes "PRODUCES:figures/fig1.pdf,figures/fig2.pdf,figures/fig3.pdf"
```

If your figures depend on data files, declare those too:

```bash
# Declare inputs
bd update <task-id> --notes "REQUIRES:output/results.json,output/data/experiment_results.csv"
```

### Phase 2: Data Dependency Check

For each figure, answer:
1. **What data file does it need?** (results.json, experiment_data.csv, etc.)
2. **Does that data file exist?** Run `ls -la <path>` to verify
3. If missing: your task has an unsatisfied REQUIRES — report BLOCKED:
   ```bash
   bd update <task-id> --notes "BLOCKED: Required data file missing: <path>"
   ```

### Phase 3: Generate Figures (ONE AT A TIME, commit each)

For each figure:

```bash
# 1. Write the plotting script
cat > scripts/plot_ablation.py << 'EOF'
import json
import matplotlib.pyplot as plt

# Load data
with open('output/results.json') as f:
    data = json.load(f)

# Generate figure
fig, ax = plt.subplots(figsize=(8, 5))
# ... plotting code ...
fig.savefig('figures/ablation.pdf', bbox_inches='tight', dpi=300)
plt.close()
print("Generated: figures/ablation.pdf")
EOF

# 2. Create output directory
mkdir -p figures

# 3. Run the script
python scripts/plot_ablation.py

# 4. Verify output exists and has content
ls -la figures/ablation.pdf
# File should be > 0 bytes

# 5. Commit immediately (preserves progress on context overflow)
git add figures/ablation.pdf scripts/plot_ablation.py
git commit -m "Add figure: ablation comparison"
git push origin <branch>
```

**CRITICAL**: Commit after EACH figure. If your context window runs out mid-task,
all previously committed figures survive.

### Phase 4: Post-Flight Verification

After ALL figures are generated:

```bash
# List all figures and verify count
ls -la figures/

# If LaTeX files exist, cross-check references
grep -rn 'includegraphics' *.tex | while IFS= read -r line; do
    FILE=$(echo "$line" | sed 's/.*{\([^}]*\)}/\1/')
    if [ ! -f "$FILE" ] && [ ! -f "figures/$FILE" ]; then
        echo "MISSING: $FILE"
    fi
done

# Update Beads with verification
bd update <task-id> --notes "FIGURES_VERIFIED: all N/N present"
```

### Phase 5: Run figure-lint (if available)

```bash
# Automated check
./scripts/figure-lint.sh .
```

## Figure Quality Checklist

Before committing each figure:

- [ ] Axis labels present and readable
- [ ] Legend present (if multiple series)
- [ ] Title or caption-ready description
- [ ] Error bars / confidence intervals shown (for statistical data)
- [ ] Color-blind friendly palette (avoid red/green only)
- [ ] Resolution ≥ 300 DPI for raster, vector preferred for line plots
- [ ] File format matches LaTeX expectation (.pdf for pdflatex, .eps for latex)

## Common Pitfalls

| Problem | Cause | Fix |
|---------|-------|-----|
| Blank figure | `plt.show()` instead of `plt.savefig()` | Always use `savefig()`, never `show()` |
| Figure path mismatch | Script saves to `output/fig.pdf`, LaTeX expects `figures/fig.pdf` | Match paths exactly |
| Missing data | Data file not yet generated | Check REQUIRES before starting |
| Font errors in PDF | System font not available | Use matplotlib defaults or `plt.rcParams['font.family'] = 'serif'` |
| Figure too large | High-res bitmap | Use vector format (.pdf, .svg) for line plots |
