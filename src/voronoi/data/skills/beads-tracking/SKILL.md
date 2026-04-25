---
name: beads-tracking
description: >
  Skill for using Beads (bd) as the single source of truth for task tracking,
  dependency management, and agent coordination. Covers all bd commands needed
  for multi-agent orchestration.
user-invocable: true
disable-model-invocation: false
---

# Beads Task Tracking

Use this skill for all task management operations. Beads is the ONLY task tracking
system — never use markdown files for planning.

## Initialization

```bash
bd init --quiet           # First-time setup (creates .beads/)
bd prime                  # Load context (run at every session start)
```

## Creating Tasks

```bash
# Create an epic
bd create "Full-stack task app" -t epic -p 1

# Create a subtask under an epic
bd create "Auth system" -t task -p 1 --parent <epic-id>

# Add details
bd update <id> --description "Implement JWT-based auth with OAuth support"
bd update <id> --acceptance "Login, logout, token refresh all working with tests"
```

## Dependencies

```bash
# Add dependency (child depends on parent)
bd dep add <child-id> <parent-id>

# View dependency graph
bd list --blocked
```

## Task Lifecycle

```bash
# Find available work
bd ready                          # Show unblocked tasks
bd ready --json                   # Machine-readable format

# Claim a task
bd update <id> --claim

# Log progress
bd update <id> --notes "Implemented user model and migrations"

# Report blockers
bd update <id> --notes "BLOCKED: waiting on API schema from agent-api"

# Complete a task
bd close <id> --reason "Completed: JWT auth with login/logout/refresh endpoints"
```

## Querying State

```bash
bd list                           # All tasks
bd list --status open             # Open tasks
bd list --status in_progress      # In-progress tasks
bd list --status closed           # Completed tasks
bd list --status open --json      # JSON output for scripting
bd show <id>                      # Full task details
```

## Important Rules

- NEVER use `bd edit` — it opens an interactive editor that breaks automation
- ALWAYS use `bd update` with flags for modifications
- ALWAYS run `bd prime` at session start
- Task IDs are hash-based and globally unique — safe across branches
