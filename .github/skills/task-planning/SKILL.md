---
name: task-planning
description: >
  Skill for decomposing high-level feature requests into structured epics and subtasks
  using Beads (bd). Covers dependency graph creation, priority assignment, scope definition,
  and agent dispatch planning.
---

# Task Planning with Beads

Use this skill when you need to break down a large feature or project into manageable,
independently implementable tasks for parallel agent execution.

## Step 1: Analyze the Request

- Identify the top-level goal (this becomes the epic)
- List 3–8 concrete subtasks that can be implemented independently
- Determine dependencies between subtasks
- Assign file/directory scopes to avoid agent overlap

## Step 2: Create the Epic

```bash
bd create "<epic title>" -t epic -p 1
```

Note the returned epic ID for use as `--parent` in subtasks.

## Step 3: Create Subtasks

For each subtask:

```bash
bd create "<subtask title>" -t task -p <1|2|3> --parent <epic-id>
bd update <task-id> --description "<detailed specification>"
bd update <task-id> --acceptance "<definition of done>"

# Artifact contracts — MANDATORY for pipeline correctness
bd update <task-id> --notes "PRODUCES:<output files this task must create>"
bd update <task-id> --notes "REQUIRES:<input files that must exist before task starts>"
# For validation-gated tasks:
bd update <task-id> --notes "GATE:<path/to/validation_report.json>"
```

### Priority Guidelines
- **P1** — Critical path, blocks other work
- **P2** — Important but not blocking
- **P3** — Nice to have, can be deferred

### Scope Specification
Every task description MUST include:
- Which files/directories the agent should create or modify
- Which existing code to integrate with
- Clear boundaries (what NOT to touch)

## Step 4: Set Dependencies

```bash
bd dep add <child-id> <parent-id>
```

Common dependency patterns:
- API depends on database schema
- Frontend depends on API endpoints
- Integration tests depend on all components
- Auth is often independent (good first dispatch)

## Step 5: Verify the Plan

```bash
bd list              # See all tasks
bd ready             # Verify unblocked tasks are correct
bd list --blocked    # Check dependency graph
```

## Anti-Patterns to Avoid

- Tasks that are too large (>4 hours of work)
- Tasks with overlapping file scopes
- Circular dependencies
- Missing acceptance criteria
- Vague descriptions ("make it work")
- Missing artifact contracts (PRODUCES/REQUIRES) — causes downstream tasks to fail
- Tasks that consume files without declaring REQUIRES on those files
- Validation-gated tasks (e.g., paper writing) without a GATE contract
