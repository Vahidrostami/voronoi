---
name: branch-merging
description: >
  Skill for safely merging completed agent branches back to main. Covers
  pre-merge checks, conflict resolution, post-merge cleanup, and promotion
  of newly unblocked tasks.
user-invocable: true
disable-model-invocation: false
---

# Branch Merging

Use this skill when merging completed agent work back to the main branch.

## Pre-Merge Checklist

Before merging, verify:

1. **Task is closed in Beads:**
   ```bash
   bd show <task-id>      # Status should be "closed"
   ```

2. **All tests pass on the agent branch:**
   ```bash
   cd <worktree-path>
   # Run project-appropriate tests
   npm test / pytest / go test ./... / cargo test
   ```

3. **Review changes:**
   ```bash
   git log main..<branch> --oneline    # Commit history
   git diff main..<branch> --stat      # Files changed
   git diff main..<branch>             # Full diff
   ```

## Merging

### Using the merge script:
```bash
./scripts/merge-agent.sh <branch-name> <task-id>
```

### Manual merge:
```bash
git checkout main
git pull --rebase
git merge <branch> --no-ff -m "Merge <branch>: agent work complete"
git push origin main
```

## Conflict Resolution

If `git merge` fails with conflicts:

1. Identify conflicting files: `git diff --name-only --diff-filter=U`
2. Resolve conflicts manually or with a merge tool
3. `git add <resolved-files>`
4. `git commit` (merge commit message is pre-populated)
5. `git push origin main`

## Post-Merge Cleanup

```bash
# Remove worktree
git worktree remove <worktree-path>

# Delete branch
git branch -d <branch-name>

# Kill tmux window
tmux kill-window -t <session>:<branch>

# Prune stale references
git worktree prune
```

## Promoting Unblocked Tasks

After merging, check for newly available work:

```bash
bd ready
```

If tasks are now unblocked, dispatch new agents:
```bash
./scripts/spawn-agent.sh <task-id> agent-<name> "<description>"
```

## Merge Order Strategy

When multiple branches are ready to merge:
1. Merge branches that unblock the most downstream tasks first
2. Merge smaller changesets before larger ones (easier conflict resolution)
3. Run the full test suite after each merge before proceeding
