# Voronoi Standup Report

**Date:** {{DATE}}
**Project:** {{PROJECT_NAME}}
**Mode:** {{WORKFLOW_MODE}}
**Rigor:** {{RIGOR_LEVEL}}

---

## Completed Since Last Standup
| Task ID | Title | Status |
|---------|-------|--------|
| {{TASK_ID}} | {{TITLE}} | Merged / Ready to merge |

## In Progress
| Task ID | Agent | Title | Commits | Status |
|---------|-------|-------|---------|--------|
| {{TASK_ID}} | {{BRANCH}} | {{TITLE}} | {{COMMIT_COUNT}} | On track / ⚠ Stalled |

## Blocked
| Task ID | Title | Blocked By |
|---------|-------|------------|
| {{TASK_ID}} | {{TITLE}} | {{DEPENDENCY}} |

## Ready to Start
| Task ID | Title | Priority |
|---------|-------|----------|
| {{TASK_ID}} | {{TITLE}} | P{{PRIORITY}} |

## Conflict Check
{{CONFLICT_STATUS}}

<!-- Scientific+ rigor sections below — include only when investigation tasks exist -->

## Belief Map
| Hypothesis | Status | Prior/Posterior | Evidence |
|------------|--------|-----------------|----------|
| {{HYPOTHESIS}} | {{STATUS}} | {{PROBABILITY}} | {{EVIDENCE_IDS}} |

## Findings
| ID | Title | Quality | Review Status |
|----|-------|---------|---------------|
| {{FINDING_ID}} | {{FINDING_TITLE}} | {{STAT_QUALITY}} | Validated / Pending / Contested |

## Working Theory
{{WORKING_THEORY_DESCRIPTION}}

## Convergence
**{{CONVERGENCE_PERCENT}}%** ({{RESOLVED}}/{{TOTAL}} hypotheses resolved)
{{CONVERGENCE_TREND}}

## Rigor Compliance
- Pre-registration: {{PREREG_COMPLIANT}}/{{PREREG_TOTAL}} compliant
- Replications: {{REPL_CONFIRMED}}/{{REPL_TOTAL}} confirmed
- Adversarial reviews: {{ADV_RESOLVED}}/{{ADV_TOTAL}} resolved

<!-- End scientific sections -->

## Recommendations
- {{RECOMMENDATION_1}}
- {{RECOMMENDATION_2}}

---

**Next actions:** `/merge` · `/swarm` · `/spawn` · `/teardown`
