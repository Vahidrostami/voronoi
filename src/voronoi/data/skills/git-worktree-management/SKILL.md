---
name: git-worktree-management
description: >
  Skill for creating, managing, and cleaning up git worktrees used as isolated
  working directories for parallel agent execution. Covers worktree lifecycle
  from creation through merge and teardown.
user-invocable: true
disable-model-invocation: false
---

# Git Worktree Management

Use this skill when creating isolated working environments for agents, managing
active worktrees, or cleaning up after task completion.

## Creating a Worktree

```bash
# Create worktree with a new branch
git worktree add <path> -b <branch-name>

# Example: create agent worktree
SWARM_DIR=$(jq -r '.swarm_dir' .swarm-config.json)
git worktree add "$SWARM_DIR/agent-auth" -b agent-auth
```

### Naming Convention
- Branch: `agent-<short-descriptive-name>` (e.g., `agent-auth`, `agent-api`, `agent-dashboard`)
- Path: `<swarm-dir>/agent-<name>`

### Reusing Existing Branches
```bash
# If branch already exists
git worktree add <path> <existing-branch>
```

## Listing Worktrees

```bash
git worktree list                    # Simple list
git worktree list --porcelain        # Machine-readable format
```

## Inspecting Worktree Activity

```bash
# Commits on agent branch vs main
git log main..agent-auth --oneline

# Files changed
git diff main..agent-auth --stat

# Last commit time
git log agent-auth -1 --format="%ar"
```

## Removing a Worktree

```bash
# Clean removal (after merge)
git worktree remove <path>

# Force removal (if dirty)
git worktree remove <path> --force

# Clean up stale metadata
git worktree prune
```

## Branch Cleanup

```bash
# Delete merged branch
git branch -d agent-auth

# Force delete unmerged branch
git branch -D agent-auth
```

## Conflict Detection Between Worktrees

```bash
# Check if two agent branches would conflict
git merge-tree $(git merge-base agent-auth agent-api) agent-auth agent-api
```

## Best Practices

- Always create worktrees in the swarm directory (outside main project)
- One worktree per agent, one agent per task
- Run `git worktree prune` after cleanup to remove stale references
- Never modify the main worktree while agents are running
