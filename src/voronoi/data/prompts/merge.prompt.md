---
name: merge
description: Merge completed agent branches back to main. Reviews changes, runs merge script, cleans up worktrees, and checks for newly unblocked tasks.
agent: agent
tools:
  - execute
  - read
  - search
---

Merge completed agent branches.

## Process

1. Find completed tasks:
   ```
   bd list --status closed --json
   ```

2. For each closed task, find its agent branch from Beads notes or by pattern matching

3. **Finding Gate Verification** (for investigation tasks at Analytical+ rigor):
   Before merging a branch that produced findings, verify:
   ```bash
   # Check all findings from this task have passed review gates
   bd list --json | python3 -c "
   import sys, json
   tasks = json.load(sys.stdin)
   for t in tasks:
       notes = t.get('notes','') or ''
       if 'TYPE:finding' in notes and 'SOURCE_TASK:<task-id>' in notes:
           has_stat = 'STAT_REVIEW: APPROVED' in notes
           has_critic = 'CRITIC_REVIEW:' in notes
           print(f\"{t['id']}: stat={has_stat} critic={has_critic}\")
   "
   ```
   - If findings exist but haven't passed Statistician review: BLOCK merge, dispatch Statistician
   - If findings exist but haven't passed Critic review (Scientific+): BLOCK merge, dispatch Critic

4. For each branch ready to merge:
   a. Show the user what will be merged:
      ```
      git log main..<branch> --oneline
      git diff main..<branch> --stat
      ```
   b. Ask for confirmation
   c. Run: `./scripts/merge-agent.sh <branch> <task-id>`

5. **Knowledge Store Acceptance** (for validated findings):
   After merge, findings that passed all review gates are considered part of the knowledge store.
   The Synthesizer should run a consistency check if 2+ new findings entered since last check.

6. After all merges, check for newly unblocked tasks:
   ```
   bd ready
   ```

7. If there are ready tasks, ask if the user wants to dispatch new agents.
