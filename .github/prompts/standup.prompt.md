---
name: standup
description: Run a daily standup meeting across all active agents. Generates a progress report with task status, branch activity, conflict detection, and recommendations.
agent: agent
tools:
  - execute
  - read
  - search
---

You are running a standup meeting across all active agents.

## Process

1. Run `./scripts/standup.sh` and read the output

2. Interpret the results and provide a human-friendly report:

   **Completed since last standup:**
   - [task-id] task title — merged / ready to merge

   **In progress:**
   - [task-id] task title — X commits, working on [current focus]
   - [task-id] task title — ⚠ STALLED (no commits in 24h)

   **Blocked:**
   - [task-id] task title — waiting on [dependency]

   **Ready to start:**
   - [task-id] task title — all dependencies met

3. Make recommendations:
   - Which completed branches should be merged now?
   - Should any stalled agents be restarted?
   - Are there newly unblocked tasks to dispatch?
   - Any conflicts that need human attention?

4. Update Beads with standup notes:
   ```
   bd update <id> --notes "Standup [date]: [status summary]"
   ```

5. Ask the user what they want to do next:
   - Merge completed work? → use the merge prompt
   - Dispatch new agents? → use the swarm prompt
   - Restart a stalled agent? → use the spawn prompt
   - Full teardown? → use the teardown prompt
