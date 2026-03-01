# /spawn — Spawn a Single Worker Agent

## Input
User provides a Beads task ID, or describes a task to create.

## Process

1. If task ID provided:
   - `bd show <id>` to verify it exists and is ready
   - `bd update <id> --claim`

2. If description provided:
   - `bd create "<title>" -t task -p <priority>`
   - Note the returned ID

3. Derive a branch name: `agent-<short-descriptive-name>`

4. Run:
   ```bash
   ./scripts/spawn-agent.sh <task-id> <branch-name> "<task description>"
   ```

5. Confirm to user: agent is running, attach with tmux.
