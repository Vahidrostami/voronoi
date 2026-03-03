# Epic Planning Template

## Epic: {{EPIC_TITLE}}

**Goal:** {{ONE_SENTENCE_GOAL}}

**Beads ID:** {{EPIC_ID}}

**Workflow Mode:** {{BUILD|INVESTIGATE|EXPLORE|HYBRID}}

**Rigor Level:** {{STANDARD|ANALYTICAL|SCIENTIFIC|EXPERIMENTAL}}

---

## Subtasks

### 1. {{SUBTASK_TITLE}}
- **Priority:** P{{1|2|3}}
- **Task Type:** {{build|investigation|exploration|review|replication|theory}}
- **Scope:** {{files/directories this task owns}}
- **Description:** {{what to build or investigate}}
- **Acceptance criteria:**
  - [ ] {{criterion 1}}
  - [ ] {{criterion 2}}
- **Dependencies:** None / {{depends on subtask N}}

### 2. {{SUBTASK_TITLE}}
- **Priority:** P{{1|2|3}}
- **Task Type:** {{type}}
- **Scope:** {{files/directories}}
- **Description:** {{what to build or investigate}}
- **Acceptance criteria:**
  - [ ] {{criterion 1}}
- **Dependencies:** {{depends on subtask N}}

---

<!-- Investigation mode sections — include only for Investigate/Explore/Hybrid epics -->

## Hypothesis List (Investigation/Hybrid Mode)
| # | Hypothesis | Prior | Basis | Testability | Impact |
|---|-----------|-------|-------|-------------|--------|
| H1 | {{HYPOTHESIS}} | {{0.0-1.0}} | {{evidence source}} | {{high/medium/low}} | {{downstream count}} |
| H2 | {{HYPOTHESIS}} | {{0.0-1.0}} | {{evidence source}} | {{high/medium/low}} | {{downstream count}} |

## Expected Information Gain
| Hypothesis | Uncertainty | Impact | Testability | Priority Score |
|------------|-----------|--------|-------------|----------------|
| H1 | {{score}} | {{score}} | {{score}} | {{product}} |
| H2 | {{score}} | {{score}} | {{score}} | {{product}} |

<!-- End investigation sections -->

## Dependency Graph

```
Subtask 1 (auth) ──┐
                    ├──► Subtask 3 (API) ──► Subtask 4 (frontend)
Subtask 2 (DB)   ──┘
```

## Agent Dispatch Plan

| Order | Task | Branch | Role | Blocked By |
|-------|------|--------|------|------------|
| 1 | {{SUBTASK}} | agent-{{name}} | {{Builder/Investigator/Scout/...}} | — |
| 2 | {{SUBTASK}} | agent-{{name}} | {{role}} | — |
| 3 | {{SUBTASK}} | agent-{{name}} | {{role}} | Tasks 1, 2 |

## Notes
- Max agents: {{MAX_AGENTS}} (from .swarm-config.json)
- Ensure no overlapping file scopes between agents
- Investigation tasks require Methodologist review at Scientific+ rigor
