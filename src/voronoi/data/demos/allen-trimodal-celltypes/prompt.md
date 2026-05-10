# Trimodal Cell Type Identity in Mouse Cortex: Are Electrophysiological Types Predictive of Transcriptomic Types Beyond Morphology?

Produce a Nature-format research paper using the Allen Cell Types Database. The investigation must answer one **open**, falsifiable question with rigorous statistics, defensible figures, and complete provenance. The paper must be reproducible end-to-end from this prompt and the public Allen data.

---

## Primary Research Question

**Q1.** Do electrophysiological (E) features carry information about transcriptomic (T) cell-type identity *beyond* what morphological (M) features alone provide?

Operational form (the *only* claim the paper defends):

> Across mouse cortical neurons in the Allen Cell Types Database with paired E + M + T data, a model predicting transcriptomic cluster from {E ∪ M} features achieves significantly higher cross-validated balanced accuracy than a model using {M} alone, controlling for cre-line, layer, region, and sample size. The marginal information from E is non-uniform across T-types and is concentrated in [report which subclasses].

**Secondary, exploratory:**

- **Q2.** Are there T-types that are *only* separable when E is added (i.e., M-indistinguishable but E-separable)?
- **Q3.** Within Pvalb and Sst inhibitory subclasses, which specific E features drive the marginal information (interpretability via permutation importance + SHAP)?

The interpretation question (Q3) is exploratory and reported as such — not a headline claim.

---

## Data — Public, CPU-only

All data must be obtained through the **AllenSDK** (`pip install allensdk`). No raw NWB sweeps need to be reprocessed; precomputed feature tables are sufficient and CPU-tractable.

| Source | API call | Approx size | Use |
|---|---|---|---|
| Cell metadata (cre line, region, layer, donor species) | `CellTypesCache.get_cells()` | <5 MB | Stratification + filtering |
| Precomputed ephys features | `CellTypesCache.get_ephys_features()` | <50 MB | E feature matrix |
| Precomputed morphology features | `CellTypesCache.get_morphology_features()` | <10 MB | M feature matrix |
| Patch-seq T-type labels | Allen Cell Types portal CSV / Gouwens et al. 2020 supplement (mouse VISp/ALM) | <50 MB | T labels (ground truth) |

**Inclusion criteria:** mouse only, neurons with **all three modalities present**, T-type label confidence above Allen's published threshold. Expected N ≈ 1,500–2,000 cells after filtering — verify and report exact N.

**Hard constraint:** the analysis must run on a single CPU node with ≤ 32 GB RAM in under 2 hours wall-clock. No deep learning. Use scikit-learn, statsmodels, lightgbm (CPU).

---

## Why This Question Is Publishable on Public Data

- The Allen trimodal data is fully open, but **the precise hypothesis test of E's marginal information *given* M, with proper confound control and per-T-type decomposition, has not been published** as a primary finding. Gouwens et al. 2020 and Scala et al. 2021 describe the data and joint clustering but do not isolate the *additive* information question with the rigor below.
- The result is interpretable to a neuroscience reviewer regardless of sign: a positive finding refines the multimodal-taxonomy literature; a negative finding (E adds nothing beyond M for T identity) is itself a notable result that constrains future modeling.

---

## Methodology — Mandatory Elements

The investigation must execute and report **all** of the following. Skipping any step invalidates the contribution.

### 1. Data audit (before any modeling)
- Per-modality missingness, feature distributions, outliers.
- Confound table: cre-line × layer × region × T-type contingency.
- Report any T-type with N < 20 in the matched set; either pool to the subclass level or exclude (with justification).

### 2. Feature preparation
- Within-modality standardization. Drop near-zero-variance features. Report final dimensionality of E and M.
- No T-derived features may enter E or M (no leakage). Document explicit feature lists.

### 3. Primary test (Q1)
- Outcome: T-type label (or T-subclass if N constraints force pooling — pre-commit the level **before seeing model results**).
- Models: regularized multinomial logistic regression *and* gradient-boosted trees (LightGBM, CPU). Both must agree in sign for the headline claim.
- Comparators:
  - **M-only** baseline
  - **E∪M** model
  - **E-only** reference (for completeness, not a headline)
- Evaluation: **stratified group K-fold** (group = donor) to prevent donor leakage. Balanced accuracy + macro-F1 + per-class F1.
- Statistical test: paired bootstrap on fold-level scores (10,000 resamples) for ΔBalAcc(E∪M − M-only). Report 95% CI and one-sided p-value with α = 0.01 (Bonferroni for the three primary outcomes: BalAcc, macro-F1, per-class F1 trend).
- **Confound control:** repeat the comparison after residualizing each E and M feature on cre-line + layer + region (one-hot). The headline claim must hold both before and after residualization, or be reported as confound-mediated.

### 4. Per-T-type decomposition (Q2)
- For each T-type with N ≥ 20: compute ΔF1 from adding E to M.
- Identify "E-essential" T-types: those where M-only F1 < 0.4 *and* E∪M F1 ≥ 0.7. Report with bootstrap CIs.

### 5. Interpretability (Q3, exploratory)
- Restrict to Pvalb and Sst subclasses.
- Permutation importance + SHAP values from the LightGBM model.
- Report top 5 E features per subclass with stability (selection frequency over 100 bootstrap refits).

### 6. Sensitivity & robustness
- Sample-size sensitivity: re-run primary test on 50%, 75%, 100% subsamples.
- Modality-noise injection: inject Gaussian noise into E features at σ = 0.1, 0.25, 0.5 of feature SD; report when E's marginal information collapses.
- Alternative T-label granularities: subclass, supertype, leaf type. Pre-commit which is primary.

---

## Rigor Gates (Voronoi must enforce)

These are non-negotiable. Failing any gate must be reported in the limitations section, not hidden:

1. **No fabrication** — every cited number, gene name, T-type label, or paper reference must be traceable to the actual data file or a real DOI. Citations must be verified by Voronoi's fabrication gate.
2. **Pre-registration discipline** — primary outcome (BalAcc), primary T-label granularity, and decision rule (Δ ≥ 0.05 BalAcc with p < 0.01) must be committed in writing **before** the modeling step runs. Record the commit in the manifest.
3. **Donor-level leakage check** — explicitly test that no donor's cells appear in both train and test folds. Fail loudly if they do.
4. **Reproducibility manifest** — record allensdk version, data manifest hash, scikit-learn / lightgbm versions, random seeds, exact filter counts.
5. **Convergence rule** — investigation may not be marked complete until: (a) primary test reported with CI, (b) confound-controlled re-test reported, (c) per-T-type table produced, (d) all figures rendered, (e) limitations section drafted.

---

## Required Paper Artifacts

The investigation produces the following files in the workspace, all reproducible from `pipeline.py`:

| Path | Content |
|---|---|
| `paper/main.md` | Nature-format manuscript (Abstract, Intro, Methods, Results, Discussion, Limitations, Data Availability, Code Availability) |
| `paper/figures/fig1_trimodal_overview.{pdf,svg}` | Schematic + N table + UMAP per modality colored by T-type |
| `paper/figures/fig2_primary_result.{pdf,svg}` | Bar chart of BalAcc for M, E, E∪M with bootstrap CIs; before/after confound residualization |
| `paper/figures/fig3_per_ttype.{pdf,svg}` | Heatmap of per-T-type ΔF1; flag E-essential types |
| `paper/figures/fig4_interpretability.{pdf,svg}` | Top E features for Pvalb/Sst with stability |
| `paper/figures/fig5_robustness.{pdf,svg}` | Sample-size and noise sensitivity curves |
| `paper/tables/table1_cohort.csv` | Final cohort breakdown |
| `paper/tables/table2_primary.csv` | Headline numbers |
| `paper/tables/table3_per_ttype.csv` | Per-T-type results |
| `pipeline.py` | Single entry point: downloads data → runs full analysis → writes all artifacts |
| `manifest.json` | Pre-registration record + versions + hashes + final numbers |
| `claims.json` | Every quantitative claim in the paper, linked to a producing artifact |

---

## Manuscript Constraints

- ≤ 4,000 words main text, ≤ 5 figures, ≤ 3 tables.
- Each numerical claim in the manuscript must reference an entry in `claims.json`.
- Discussion must include: (i) what would falsify the headline claim, (ii) compatibility with Gouwens et al. 2020 and Scala et al. 2021 framings, (iii) at least three concrete limitations (cre-line confounding, sampling bias toward visual cortex, T-label hierarchy ambiguity).
- A negative result is acceptable and must be reported with the same rigor as a positive one. Do not retrofit the question to match the data.

---

## Out of Scope

- Deep learning models, GPU compute, raw NWB sweep reprocessing.
- Human cell types (mouse only for this investigation).
- Spatial transcriptomics, in-vivo activity, or cross-species comparisons.
- Any T-label that requires re-running Allen's clustering pipeline — use published labels only.

---

## Success Criterion

A reviewer in computational neuroscience, given only this prompt, the workspace, and 2 hours, can reproduce every number in `paper/main.md` by running `python pipeline.py`. The paper either substantiates the headline claim with the rigor specified above, or reports a clean negative result. No third outcome is acceptable.
