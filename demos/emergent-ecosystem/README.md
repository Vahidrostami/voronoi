# Demo: Emergent Multi-Species Ecosystem

A multi-species simulation where 4 creature species with different communication strategies compete and cooperate on a shared grid world. The novel outcome — which strategy wins, whether symbiosis emerges, whether predators cause extinction — is genuinely unpredictable and not something any LLM has memorized.

## What Gets Built

```
src/
├── world/                  # Shared grid world engine
│   ├── __init__.py
│   ├── grid.py             # 100x100 grid, food spawning, tick loop
│   ├── entity.py           # Base creature class
│   └── config.py           # Simulation parameters
├── species/
│   ├── ants/               # Pheromone trail communication
│   │   ├── __init__.py
│   │   └── ant.py
│   ├── birds/              # Sound-based flocking
│   │   ├── __init__.py
│   │   └── bird.py
│   ├── fireflies/          # Visual light-flash signaling
│   │   ├── __init__.py
│   │   └── firefly.py
│   └── wolves/             # Predator with scent tracking
│       ├── __init__.py
│       └── wolf.py
├── main.py                 # Simulation runner
└── visualize.py            # ASCII + HTML report output
```

## Task Dependency Graph

```
Wave 1:  [World Engine]
              │
Wave 2:  [Ants] [Birds] [Fireflies] [Wolves]   ← 4 agents in parallel
              │      │        │          │
Wave 3:       └──────┴────────┴──────────┘
                         │
                  [Sim Runner + Viz]
```

## How to Run

### Prerequisites

```bash
brew install beads tmux gh
./scripts/swarm-init.sh
```

### Option A — Fully Automated (Autopilot)

One command, zero interaction:

```bash
./scripts/autopilot.sh --prompt demos/emergent-ecosystem/PROMPT.md \
  --dashboard /tmp/ecosystem-swarm.txt \
  --notify "say 'ecosystem complete'"
```

Watch progress in another terminal:
```bash
# Live dashboard
python3 scripts/dashboard.py

# Or simple tail
tail -f /tmp/ecosystem-swarm.txt
```

### Option B — Interactive (Human-in-the-Loop)

```bash
copilot
```

Then prompt the orchestrator:

```
/swarm @swarm-orchestrator Build an emergent multi-species ecosystem simulation. Details in demos/emergent-ecosystem/PROMPT.md
```

The orchestrator will plan tasks, dispatch agents in waves, and ask you to approve merges between waves. Use `/standup` to check progress and `/merge` when agents complete.

### Run the Simulation

After the swarm completes (all agents merged):
```bash
python -m src.main --ticks 500 --seed 42

# Or headless for data + HTML report
python -m src.main --ticks 500 --no-display --seed 42
```

### View Results

- **Terminal:** Live ASCII playback of creatures moving on the grid
- **CSV:** `output/population.csv` — population counts per species per tick
- **HTML:** `output/report.html` — charts showing population curves, extinction events, territory maps

### Cleanup

```
/teardown
```

## What to Look For

The novel discoveries emerge from interaction:
- **Do ants form highway networks?** Pheromone trails should create emergent pathways
- **Do birds flock away from wolves?** Sound signals should propagate danger warnings
- **Do fireflies cluster near food?** Light flashes should attract nearby fireflies
- **Does any species go extinct?** Wolf predation pressure may eliminate weaker species
- **Do species form symbiotic zones?** Ants leaving trails might inadvertently guide birds to food

None of these outcomes are pre-programmed — they emerge from the interaction of independently-built systems.
