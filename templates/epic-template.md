# Epic Planning Template

## Epic: {{EPIC_TITLE}}
**Priority:** P{{PRIORITY}}
**Beads ID:** {{EPIC_ID}}

---

### Description
{{EPIC_DESCRIPTION}}

### Subtasks

| # | Task | Priority | Dependencies | File Scope |
|---|------|----------|--------------|------------|
| 1 | {{TASK_1}} | P1 | None | {{SCOPE_1}} |
| 2 | {{TASK_2}} | P1 | None | {{SCOPE_2}} |
| 3 | {{TASK_3}} | P1 | Task 1 | {{SCOPE_3}} |
| 4 | {{TASK_4}} | P2 | Task 3 | {{SCOPE_4}} |

### Dependency Graph

```
Task 1 (independent) ──┐
                       ├──→ Task 3 ──→ Task 4
Task 2 (independent) ──┘
```

### Beads Commands to Create This Epic

```bash
# Create epic
bd create "{{EPIC_TITLE}}" -t epic -p 1

# Create subtasks (replace EPIC_ID with actual ID from above)
bd create "{{TASK_1}}" -t task -p 1 --parent EPIC_ID
bd create "{{TASK_2}}" -t task -p 1 --parent EPIC_ID
bd create "{{TASK_3}}" -t task -p 1 --parent EPIC_ID
bd create "{{TASK_4}}" -t task -p 2 --parent EPIC_ID

# Set dependencies (replace IDs with actual IDs)
bd dep add TASK_3_ID TASK_1_ID
bd dep add TASK_4_ID TASK_3_ID

# Verify
bd list
bd ready
```

### Acceptance Criteria
- [ ] All subtasks completed and merged to main
- [ ] All tests passing on main branch
- [ ] No known regressions
- [ ] Documentation updated
