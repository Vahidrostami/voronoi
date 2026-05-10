---
name: adversarial-review
description: >
  Use for adversarial review of Voronoi plans, findings, claims, manuscripts, and
  final deliverables. Covers reviewer-style objections, confounds, alternative
  explanations, evidence gaps, and falsification-oriented critique.
user-invocable: true
disable-model-invocation: false
---

# Adversarial Review

Use this skill when a plan, finding, claim ledger, manuscript, or final deliverable needs a hostile but evidence-grounded review before acceptance.

## Procedure

1. Identify the artifact under review and the claim it is meant to support.
2. Separate evidence-backed claims from interpretation, speculation, and missing data.
3. Check for confounds, alternative explanations, weak controls, statistical misuse, selection effects, and unsupported generalization.
4. For each objection, cite the exact artifact or missing artifact that makes it matter.
5. Classify each objection as `blocking`, `major`, `minor`, or `resolved`.
6. Recommend the smallest experiment, analysis, citation, or wording change that would resolve each unresolved objection.

## Output

Write a concise review with:

- artifact reviewed
- strongest claim challenged
- blocking objections
- major objections
- minor objections
- suggested resolution tasks
