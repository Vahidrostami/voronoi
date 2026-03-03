---
name: progress
description: Quick status check showing Beads tasks, ready work, active worktrees, and tmux sessions. No analysis, just data.
agent: agent
tools:
  - execute
---

Fast overview. No analysis, just data.

Run these commands and display the results:

```bash
echo "=== BEADS STATUS ==="
bd list

echo ""
echo "=== READY TASKS ==="
bd ready

echo ""
echo "=== ACTIVE WORKTREES ==="
git worktree list

echo ""
echo "=== TMUX SESSION ==="
tmux list-windows -t $(jq -r '.tmux_session' .swarm-config.json) 2>/dev/null || echo "No active session"
```

If investigation tasks exist (check for `TASK_TYPE:investigation` in Beads), also run:

```bash
echo ""
echo "=== FINDINGS ==="
bd list --json 2>/dev/null | python3 -c "
import sys, json
tasks = json.load(sys.stdin)
findings = [t for t in tasks if 'TYPE:finding' in (t.get('notes','') or '')]
validated = [f for f in findings if 'STAT_REVIEW: APPROVED' in (f.get('notes','') or '')]
pending = [f for f in findings if 'STAT_REVIEW' not in (f.get('notes','') or '')]
print(f'  {len(validated)} validated | {len(pending)} pending review | {len(findings)} total')
" 2>/dev/null || true

echo ""
echo "=== JOURNAL (last 10 lines) ==="
tail -10 .swarm/journal.md 2>/dev/null || echo "No investigation journal"
```

Present as a compact summary:
```
Tasks:     N total | X closed | Y in-progress | Z queued | W review
Findings:  X validated | Y pending | Z contradicted  (if investigation)
Converge:  XX%                                        (if investigation)
```
