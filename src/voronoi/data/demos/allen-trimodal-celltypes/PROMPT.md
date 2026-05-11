# Trimodal Cell Type Identity in Mouse Cortex

Across mouse cortical neurons in the Allen Cell Types Database with paired
electrophysiology (E), morphology (M), and transcriptomic (T) data, does a model
predicting T-type from {E ∪ M} achieve significantly higher cross-validated
balanced accuracy than a model using {M} alone, after controlling for cre-line,
layer, region, and sample size?

Run this as a **scientific-rigor** investigation. Voronoi's standard pipeline
(Synthesizer → Scribe → manuscript track) handles the deliverable, claim
ledger, citation coverage, fabrication checks, and convergence gate. This
prompt only specifies the **domain-specific** rigor that Voronoi cannot infer.

---

## Secondary, exploratory

- **Q2.** Are there T-types that are M-indistinguishable but E-separable?
- **Q3.** Within Pvalb and Sst subclasses, which E features drive the marginal
  information (permutation importance + SHAP)? Reported as exploratory, not a
  headline claim.

---

## Data — Public

All data via the **AllenSDK** (`pip install allensdk`). No raw NWB sweep
reprocessing; precomputed feature tables are sufficient.

| Source | API call | Use |
|---|---|---|
| Cell metadata (cre line, region, layer, donor) | `CellTypesCache.get_cells()` | Stratification + filtering |
| Precomputed ephys features | `CellTypesCache.get_ephys_features()` | E feature matrix |
| Precomputed morphology features | `CellTypesCache.get_morphology_features()` | M feature matrix |
| Patch-seq T-type labels | Allen Cell Types portal CSV / Gouwens et al. 2020 supplement (mouse VISp/ALM) | T labels |

**Inclusion:** mouse only, neurons with all three modalities, T-type confidence
above Allen's published threshold. Expected N ≈ 1,500–2,000 — verify and
report exact N.

**Hard constraint:** single CPU node, ≤ 32 GB RAM, < 2 hours wall-clock. No
deep learning. Use scikit-learn, statsmodels, lightgbm (CPU).

---

## Why this is publishable on public data

The Allen trimodal data is fully open, but the precise hypothesis test of E's
**marginal** information *given* M, with proper confound control and per-T-type
decomposition, has not been published as a primary finding. Gouwens et al. 2020
and Scala et al. 2021 describe the data and joint clustering but do not isolate
the additive-information question with the rigor below. A negative result (E
adds nothing beyond M for T identity) is itself notable and constrains future
modeling.

---

## Methodology — domain-specific requirements

### 1. Data audit (before any modeling)
- Per-modality missingness, feature distributions, outliers.
- Confound table: cre-line × layer × region × T-type contingency.
- Any T-type with N < 20 in the matched set: pool to subclass level or exclude
  with justification.

### 2. Feature preparation
- Within-modality standardization. Drop near-zero-variance features.
- Report final dimensionality of E and M.
- No T-derived features may enter E or M (no leakage). Document feature lists.

### 3. Primary test (Q1)
- Outcome: T-type label (or T-subclass if N constraints force pooling —
  pre-commit the level **before seeing model results**).
- Models: regularized multinomial logistic regression *and* gradient-boosted
  trees (LightGBM, CPU). Both must agree in sign for the headline claim.
- Comparators: **M-only** baseline, **E∪M** model, **E-only** reference.
- Evaluation: **stratified group K-fold (group = donor)** to prevent donor
  leakage. Balanced accuracy + macro-F1 + per-class F1.
- Statistical test: paired bootstrap on fold-level scores (10,000 resamples)
  for ΔBalAcc(E∪M − M-only). 95% CI and one-sided p with α = 0.01 (Bonferroni
  for the three primary outcomes).
- **Confound control:** repeat after residualizing each E and M feature on
  cre-line + layer + region (one-hot). Headline claim must hold both before
  and after, or be reported as confound-mediated.

### 4. Per-T-type decomposition (Q2)
- For each T-type with N ≥ 20: compute ΔF1 from adding E to M.
- "E-essential" T-types: M-only F1 < 0.4 *and* E∪M F1 ≥ 0.7. Report with
  bootstrap CIs.

### 5. Interpretability (Q3, exploratory)
- Restrict to Pvalb and Sst subclasses.
- Permutation importance + SHAP from the LightGBM model.
- Top 5 E features per subclass with stability (selection frequency over 100
  bootstrap refits).

### 6. Sensitivity & robustness
- Sample-size sensitivity: re-run primary on 50%, 75%, 100% subsamples.
- Modality-noise injection: Gaussian noise into E at σ = 0.1, 0.25, 0.5 of
  feature SD; report when E's marginal information collapses.
- Alternative T-label granularities (subclass / supertype / leaf). Pre-commit
  which is primary.

---

## Domain-specific rigor gates

Voronoi's platform gates (no fabrication, claim-evidence integrity, citation
coverage ≥ 0.90, reproducibility manifest, convergence) run automatically
under `rigor=scientific`. **In addition**, this investigation must enforce:

1. **Pre-registration discipline** — primary outcome (BalAcc), primary T-label
   granularity, and decision rule (Δ ≥ 0.05 BalAcc with p < 0.01) committed in
   writing **before** the modeling step runs. Record the commit in
   `.swarm/claim-evidence.json` as a pre-registered claim.
2. **Donor-level leakage check** — explicitly assert no donor's cells appear
   in both train and test folds for any model. Fail loudly if violated.

---

## Manuscript constraints

- Nature-format sections (Abstract, Intro, Methods, Results, Discussion,
  Limitations, Data Availability, Code Availability).
- ≤ 4,000 words main text, ≤ 5 figures, ≤ 3 tables.
- Required figures: trimodal overview + UMAP per modality; primary BalAcc bar
  chart with bootstrap CIs (before/after residualization); per-T-type ΔF1
  heatmap flagging E-essential types; Pvalb/Sst top-feature interpretability;
  sample-size and noise sensitivity curves.
- Required tables: final cohort breakdown, headline numbers, per-T-type results.
- Discussion must include: (i) what would falsify the headline claim,
  (ii) compatibility with Gouwens et al. 2020 and Scala et al. 2021,
  (iii) at least three concrete limitations (cre-line confounding, sampling
  bias toward visual cortex, T-label hierarchy ambiguity).
- A negative result is acceptable and must be reported with the same rigor.
  Do not retrofit the question to match the data.

The Scribe agent compiles `paper.tex` from `.swarm/deliverable.md` and
`.swarm/claim-evidence.json`. Figures live under `data/figures/`.

---

## Out of scope

- Human cell types (mouse only).
- Spatial transcriptomics, in-vivo activity, cross-species comparisons.
- T-labels that require re-running Allen's clustering pipeline — use published
  labels only.

---

## Success criterion

The headline claim is either substantiated with the rigor above, or reported
as a clean negative result. No third outcome is acceptable.
