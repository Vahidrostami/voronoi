# /merge — Merge Completed Agent Branches

## Process

1. Find completed tasks:
   ```
   bd list --status closed --json
   ```

2. For each closed task, find its agent branch from Beads notes or by pattern matching

3. For each branch ready to merge:
   a. Show the user what will be merged:
      ```
      git log main..<branch> --oneline
      git diff main..<branch> --stat
      ```
   b. Ask for confirmation
   c. Run: `./scripts/merge-agent.sh <branch> <task-id>`

4. After all merges, check for newly unblocked tasks:
   ```
   bd ready
   ```

5. If there are ready tasks, ask if the user wants to dispatch new agents.
