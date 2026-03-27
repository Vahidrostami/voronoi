---
name: teardown
description: Clean up all agent worktrees, tmux sessions, and branches. Beads data is preserved.
agent: agent
tools:
  - execute
---

Clean up everything.

## Process

1. Warn the user: this will kill all running agents and remove all worktrees.
   Beads data is preserved.

2. Ask for explicit confirmation before proceeding.

3. Run: `./scripts/teardown.sh`

4. Report results showing what was removed.
