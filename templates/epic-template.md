# Epic Planning Template

## Epic: {{EPIC_TITLE}}

**Goal:** {{ONE_SENTENCE_GOAL}}

**Beads ID:** {{EPIC_ID}}

---

## Subtasks

### 1. {{SUBTASK_TITLE}}
- **Priority:** P{{1|2|3}}
- **Scope:** {{files/directories this task owns}}
- **Description:** {{what to build}}
- **Acceptance criteria:**
  - [ ] {{criterion 1}}
  - [ ] {{criterion 2}}
- **Dependencies:** None / {{depends on subtask N}}

### 2. {{SUBTASK_TITLE}}
- **Priority:** P{{1|2|3}}
- **Scope:** {{files/directories}}
- **Description:** {{what to build}}
- **Acceptance criteria:**
  - [ ] {{criterion 1}}
- **Dependencies:** {{depends on subtask N}}

---

## Dependency Graph

```
Subtask 1 (auth) ──┐
                    ├──► Subtask 3 (API) ──► Subtask 4 (frontend)
Subtask 2 (DB)   ──┘
```

## Agent Dispatch Plan

| Order | Task | Branch | Blocked By |
|-------|------|--------|------------|
| 1 | {{SUBTASK}} | agent-{{name}} | — |
| 2 | {{SUBTASK}} | agent-{{name}} | — |
| 3 | {{SUBTASK}} | agent-{{name}} | Tasks 1, 2 |

## Notes
- Max agents: {{MAX_AGENTS}} (from .swarm-config.json)
- Ensure no overlapping file scopes between agents
