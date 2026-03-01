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

### Step 1 — Launch Copilot CLI and Prompt the Swarm

```bash
copilot
```

Then paste the prompt from [PROMPT.md](PROMPT.md):

```
/swarm @swarm-orchestrator Build an emergent multi-species ecosystem simulation. Details in demos/emergent-ecosystem/PROMPT.md
```

Or paste the full prompt inline (see PROMPT.md for the complete text).

### Step 2 — Watch Agents Work

```bash
# Attach to the tmux session
tmux attach -t $(jq -r '.tmux_session' .swarm-config.json)
```

### Step 3 — Run Standups

In Copilot CLI:
```
/standup
```

### Step 4 — Merge Completed Work

After Wave 1 (world engine) completes:
```
/merge
```

This unblocks Wave 2. The orchestrator dispatches 4 species agents in parallel.

After all 4 species complete:
```
/merge
```

Then dispatch the final runner agent:
```
/swarm continue
```

### Step 5 — Run the Simulation

After the final merge:
```bash
# Colorful live visualization (the wow moment)
python demos/emergent-ecosystem/run.py --ticks 500 --seed 42

# Or headless for data + HTML report
python demos/emergent-ecosystem/src/main.py --ticks 500 --no-viz --fast --seed 42
```

### Step 6 — View Results

- **Terminal:** Live ASCII playback of creatures moving on the grid
- **CSV:** `demos/emergent-ecosystem/output/population.csv` — population counts per species per tick
- **HTML:** `demos/emergent-ecosystem/output/report.html` — charts showing population curves, extinction events, territory maps

### Step 7 — Cleanup

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
