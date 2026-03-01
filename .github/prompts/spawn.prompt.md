---
name: spawn
description: Spawn a single worker agent on a Beads task. Creates a git worktree, opens a tmux pane, and launches Claude Code with task-specific instructions.
agent: agent
tools:
  - execute
argument-hint: Provide a Beads task ID or describe the task to create
---

Spawn a single worker agent.

## Process

1. If user provides a Beads task ID:
   - `bd show <id>` to verify it exists and is ready
   - `bd update <id> --claim`

2. If user provides a description instead:
   - `bd create "<title>" -t task -p <priority>`
   - Note the returned ID

3. Derive a branch name: `agent-<short-descriptive-name>`

4. Run:
   ```bash
   ./scripts/spawn-agent.sh <task-id> <branch-name> "<task description>"
   ```

5. Confirm to user: agent is running, provide tmux attach command.
