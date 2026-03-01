# /progress — Quick Status Check

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

Present as a compact table and nothing more.
