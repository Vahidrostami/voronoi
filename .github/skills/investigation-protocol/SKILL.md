# Investigation Protocol Skill

Hypothesis → Experiment → Finding workflow for scientific investigations.

## When to Use

Use this skill when working on investigation, exploration, or hybrid-mode tasks that require evidence-based answers.

## Investigation Task Lifecycle

### 1. Create Investigation Task

```bash
bd create "Test whether [hypothesis]" -t task -p 1 --parent <epic>
bd update <id> --description "TASK_TYPE:investigation | RIGOR:<standard|analytical|scientific|experimental>"
bd update <id> --notes "HYPOTHESIS: [specific, falsifiable statement]"
bd update <id> --notes "METHOD: [experimental approach]"
bd update <id> --notes "CONTROLS: [control conditions]"
bd update <id> --notes "EXPECTED_RESULT: [quantified expected outcome]"
bd update <id> --notes "CONFOUNDS: [identified confounding variables]"
bd update <id> --notes "STAT_TEST: [statistical test, alpha level]"
bd update <id> --notes "SAMPLE_SIZE: [N per condition with justification]"
```

### 2. Pre-Registration (Scientific+ Rigor)

Before running ANY experiment:
```bash
bd update <id> --notes "POWER_ANALYSIS: effect=[d] | alpha=[a] | power=[p] | min_N=[n] | method=[tool]"
bd update <id> --notes "SENSITIVITY_PLAN: param1=[range]; param2=[range]"
bd update <id> --acceptance "[specific criteria for confirm/refute]"
```

### 3. Methodologist Review Gate (Scientific+ Rigor)

Investigation CANNOT proceed until:
```bash
# Methodologist approves the design
bd update <id> --notes "METHODOLOGIST_REVIEW: APPROVED | REVIEWER:<reviewer-id>"
```

### 4. Run Experiment

```bash
# Execute the experiment
# Commit raw data to worktree: data/raw/
# Compute data hash
shasum -a 256 data/raw/<datafile>.csv
bd update <id> --notes "DATA_FILE:data/raw/<datafile>.csv"
bd update <id> --notes "DATA_HASH:sha256:<hash>"
```

### 5. Sensitivity Analysis

Test at least 2 parameter variations:
```bash
bd update <id> --notes "SENSITIVITY: param1=[values] -> effect=[range] | ROBUST:yes|no"
bd update <id> --notes "SENSITIVITY: param2=[values] -> effect=[range] | ROBUST:yes|no"
```

### 6. Create Finding

```bash
bd create "FINDING: [result summary with CI]" -t task --parent <epic>
bd update <finding-id> --notes "TYPE:finding | VALENCE:positive|negative|inconclusive | CONFIDENCE:0.X"
bd update <finding-id> --notes "SOURCE_TASK:<investigation-task-id>"
bd update <finding-id> --notes "EFFECT_SIZE:[d] | CI_95:[lo, hi] | N:[n] | STAT_TEST:[test] | P:[p]"
bd update <finding-id> --notes "DATA_FILE:<path>"
bd update <finding-id> --notes "DATA_HASH:sha256:<hash>"
bd update <finding-id> --notes "SENSITIVITY: [summary] | ROBUST:yes|no"
bd update <finding-id> --notes "REPLICATED:no | STAT_QUALITY:[pending] | REVIEWED_BY:[pending]"
```

### 7. Review Gates

Findings must pass through these gates before entering the knowledge store:

| Gate | Rigor Level | Reviewer |
|------|-------------|----------|
| Statistical review | Analytical+ | Statistician |
| Adversarial review (partially blinded) | Scientific+ | Critic |
| Consistency check | Scientific+ | Synthesizer |

## Negative Findings

Negative findings are equally important:
```bash
bd create "FINDING: [variable] has no measurable effect on [outcome]" -t task --parent <epic>
bd update <id> --notes "TYPE:finding | VALENCE:negative | CONFIDENCE:0.X"
bd update <id> --notes "IMPLICATION: [what this rules out, how it narrows hypothesis space]"
```

## Replication Tasks

```bash
bd create "Replicate: [original finding description]" -t task -p 2 --parent <epic>
bd update <id> --description "TASK_TYPE:replication | RIGOR:scientific | TARGET:<original-task-id>"
bd update <id> --notes "MUST use different implementation than original"
bd update <id> --notes "MUST use same hypothesis and acceptance criteria as original"
```

### Replication Policy (when to trigger)
- Finding would change investigation direction
- Finding has CI wider than 30% of effect size
- Finding contradicts Theorist's current model
- Finding has statistical quality score < 0.7

### Replication Limits
- Max 2 replications per finding (3 total measurements)
- 2/3 agree → majority enters knowledge store
- All 3 disagree → finding marked CONTESTED, escalate to user

## Serendipity Protocol

When you discover something unexpected:
```bash
bd update <id> --notes "SERENDIPITY:HIGH | DESCRIPTION:[what you found]"
```
The orchestrator may allocate up to 2 OODA cycles to pursue the lead.

## Worktree Data Layout

```
<worktree>/
├── src/           # Code (if build task)
├── experiments/   # Experiment scripts
├── data/
│   ├── raw/       # Raw experimental data (CSV, JSON)
│   ├── processed/ # Cleaned/transformed data
│   └── figures/   # Generated plots
└── report.md      # Structured summary of work done
```
