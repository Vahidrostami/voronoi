#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════
#  🐝 AGENT SWARM DEMO — Watch AI agents build in parallel
#
#  This script creates a tmux session with a split layout showing:
#  - Top-left:  Orchestrator status (beads + standup)
#  - Top-right: Agent 1 working
#  - Bot-left:  Agent 2 working  
#  - Bot-right: Agent 3 working
#
#  Usage: ./demos/swarm_demo.sh
# ══════════════════════════════════════════════════════════════

SESSION="swarm-demo"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "🐝 Agent Swarm Demo"
echo "════════════════════"
echo ""

# Kill existing demo session
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Create session with 4 panes in tiled layout
tmux new-session -d -s "$SESSION" -c "$PROJECT_DIR" -x 200 -y 50

# Split into 4 quadrants
tmux split-window -t "$SESSION" -h -c "$PROJECT_DIR"
tmux split-window -t "$SESSION:0.0" -v -c "$PROJECT_DIR"
tmux split-window -t "$SESSION:0.2" -v -c "$PROJECT_DIR"

# Label panes
tmux send-keys -t "$SESSION:0.0" "echo '🎯 ORCHESTRATOR — Task Board'" Enter
tmux send-keys -t "$SESSION:0.1" "echo '🐜 AGENT: ants — Building pheromone system'" Enter
tmux send-keys -t "$SESSION:0.2" "echo '🐦 AGENT: birds — Building flocking AI'" Enter
tmux send-keys -t "$SESSION:0.3" "echo '🐺 AGENT: wolves — Building predator logic'" Enter

sleep 1

# Pane 0: Show live task board
tmux send-keys -t "$SESSION:0.0" "watch -n 2 'bd list 2>/dev/null || echo \"No active tasks\"'" Enter

# Pane 1-3: Show agent activity (simulated with file watching)
tmux send-keys -t "$SESSION:0.1" "watch -n 1 'wc -l src/species/ants/ant.py 2>/dev/null && echo \"\" && tail -5 src/species/ants/ant.py 2>/dev/null'" Enter
tmux send-keys -t "$SESSION:0.2" "watch -n 1 'wc -l src/species/birds/bird.py 2>/dev/null && echo \"\" && tail -5 src/species/birds/bird.py 2>/dev/null'" Enter
tmux send-keys -t "$SESSION:0.3" "watch -n 1 'wc -l src/species/wolves/wolf.py 2>/dev/null && echo \"\" && tail -5 src/species/wolves/wolf.py 2>/dev/null'" Enter

echo "✓ Demo tmux session created: $SESSION"
echo ""
echo "  Attach with:  tmux attach -t $SESSION"
echo "  Kill with:    tmux kill-session -t $SESSION"
echo ""
