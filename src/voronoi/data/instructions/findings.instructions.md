---
name: 'Finding Schema Rules'
description: 'Rules for creating, reviewing, and recording findings and results'
applyTo: '**/*finding*,**/*results*,**/*finding*/**'
---
# Finding & Results Rules

## Finding Schema
Every finding MUST include these fields in Beads notes:
- `TYPE:finding`
- `VALENCE:positive|negative|null`
- `CONFIDENCE:0.X`
- `EFFECT_SIZE:[d]`
- `CI_95:[lo, hi]`
- `N:[n]`
- `STAT_TEST:[test]`
- `P:[p]`
- `DATA_FILE:<path>`
- `DATA_HASH:sha256:<hash>`
- `STAT_REVIEW:pending|APPROVED|REJECTED`

## Review Requirements
- Findings MUST pass `STAT_REVIEW: APPROVED` before merge.
- At Scientific+ rigor, findings also require `CRITIC_REVIEW`.
- The Statistician MUST independently recompute statistics from raw data — never trust agent-reported numbers alone.

## Negative Findings
- Negative results are findings too. Record them with `VALENCE:negative`.
- Include `IMPLICATION:` noting what the negative result rules out.
- NEVER discard a negative finding — it prevents other agents from repeating failed experiments.
