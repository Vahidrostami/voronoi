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

1. Gather agent status using Beads and git:

   ```bash
   bd list --json
   bd ready --json
   ```

   For each active agent branch:
   ```bash
   git log main..<branch> --oneline
   git log <branch> -1 --format="%ar"
   ```

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

3. **Scientific+ Rigor Sections** (include only when investigation tasks exist):

   **Belief Map:**
   - H1: [name] — STATUS (prior/posterior, evidence)
   - H2: [name] — STATUS (prior/posterior, evidence)

   **Findings** (N validated, M pending review):
   - #ID "[title]" — quality: X.XX
   - #ID "[title]" — AWAITING [REVIEWER]

   **Working Theory:**
   [Current best explanation from journal]

   **Rigor Compliance:**
   - Pre-registration: X/Y compliant
   - Replications: X/Y confirmed

   **Convergence:** XX% (N/M hypotheses resolved, trend direction)

4. Make recommendations:
   - Which completed branches should be merged now?
   - Should any stalled agents be restarted?
   - Are there newly unblocked tasks to dispatch?
   - Any conflicts that need human attention?
   - Any findings ready for Statistician/Critic review?

5. Update Beads with standup notes:
   ```
   bd update <id> --notes "Standup [date]: [status summary]"
   ```

6. Ask the user what they want to do next:
   - Merge completed work? → use the merge prompt
   - Dispatch new agents? → use the swarm prompt
   - Restart a stalled agent? → use the spawn prompt
   - Full teardown? → use the teardown prompt
