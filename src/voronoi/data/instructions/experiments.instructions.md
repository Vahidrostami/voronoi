---
name: 'Anti-Fabrication Rules'
description: 'Mandatory rules for experiment code: anti-fabrication, anti-simulation, statistical contracts'
applyTo: 'experiments/**'
---
# Experiment Code Rules — MANDATORY

## Anti-Fabrication
- NEVER report numbers you didn't compute from actual data using actual code.
- ALWAYS commit experiment scripts to `experiments/` alongside raw data in `data/raw/`.
- ALWAYS compute statistics programmatically — write a script that reads the raw data and outputs the numbers.
- If an experiment fails, report honestly. NEVER re-run until you get a "nice" result.

## Anti-Simulation
- NEVER create files named `*sim*`, `*mock*`, `*fake*` that replace real LLM/tool calls with `np.random` sampling.
- NEVER hardcode detection probabilities, scores, or effect sizes that the experiment is supposed to *measure*.
- If the experiment requires too many LLM calls, reduce sample size — do NOT simulate.
- If real experiment results are disappointing (high p-values, small effects), report them honestly.
  Flag `RESULT_CONTRADICTS_HYPOTHESIS` — do NOT create a simulation to produce better numbers.

## Statistical Contracts
- Every experiment MUST declare its metric contract at pre-registration.
- Results MUST include: effect size, CI, N, statistical test, p-value.
- Data file MUST have SHA-256 hash recorded in the finding.
- The `results.json` file MUST include `"runner": "<script>"` field pointing to the script that produced it.

## Merge Gate Checks
- `verify_finding_against_data()` cross-checks reported N against data file rows, verifies data hashes, and flags suspiciously clean patterns.
- `audit_all_findings()` blocks convergence if any finding has critical fabrication flags.
