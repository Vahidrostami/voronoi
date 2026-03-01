---
name: agent-standup
description: >
  Skill for running standup meetings across all active agents in the swarm.
  Aggregates Beads task status, git branch activity, commit history, and
  conflict detection into a human-readable progress report.
---

# Agent Standup

Use this skill when running a progress check or standup meeting across
all active agents in the swarm.

## Running a Standup

```bash
./scripts/standup.sh
```

This script generates a comprehensive report covering:

1. **Task Summary** — Open, in-progress, ready, and recently closed tasks from Beads
2. **Agent Branches** — Per-branch commit counts, file changes, and last activity time
3. **Conflict Check** — Detects potential merge conflicts between agent branches
4. **Recommendations** — Suggested next actions

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

Standups can run automatically via:
- **GitHub Actions:** `.github/workflows/daily-standup.yml` (weekdays at 9am UTC)
- **Cron:** `scripts/cron-standup.sh` — writes report and optionally posts as GitHub Issue
