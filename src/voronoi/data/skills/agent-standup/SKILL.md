---
name: agent-standup
description: >
  Skill for running standup meetings across all active agents in the swarm.
  Aggregates Beads task status, git branch activity, commit history, and
  conflict detection into a human-readable progress report.
user-invocable: true
disable-model-invocation: false
---

# Agent Standup

Use this skill when running a progress check or standup meeting across
all active agents in the swarm.

## Running a Standup

Use Beads and git directly to gather status:

```bash
# Task status
bd list --json | jq -r '.[] | "[\(.id)] \(.status) P\(.priority) \(.title)"'

# Ready tasks
bd ready

# Per-branch activity
for wt in ../$(basename $(pwd))-swarm/agent-*; do
  [ -d "$wt" ] || continue
  b=$(basename "$wt")
  echo "$b: $(git log main..$b --oneline 2>/dev/null | wc -l | tr -d ' ') commits"
done
```

Or run the dashboard for live monitoring:
```bash
python3 scripts/dashboard.py
```

## Interpreting Results

### Healthy Agent
- Regular commits (multiple in the last few hours)
- Beads task status matches git activity
- No conflicts with other branches

### Stalled Agent
- No commits in the last 24 hours
- Task still marked as in-progress
- **Action:** Consider restarting with `/spawn`

### Blocked Agent
- Beads notes contain "BLOCKED"
- No recent commits
- **Action:** Check dependency graph, merge blockers first

### Conflict Detected
- Two agent branches modify the same files
- **Action:** Merge one branch first, then rebase the other

## Updating Beads After Standup

```bash
bd update <id> --notes "Standup $(date +%Y-%m-%d): [status summary]"
```

## Automated Standups

Standups run as part of the orchestrator's OODA loop — the orchestrator Copilot
checks agent status continuously and acts on stalls, blocks, and completions.
