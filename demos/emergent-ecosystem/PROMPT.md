Build an emergent multi-species ecosystem simulation where 4 different species of creatures compete and cooperate on a shared 100x100 grid world. Each species uses a fundamentally different communication strategy to find food and avoid predators.

## Species

1. **Pheromone Ants** — Leave chemical trails that decay over time. Other ants follow pheromone gradients toward food. Trails strengthen with use and fade without reinforcement. Start with 50 ants.

2. **Sonic Birds** — Emit sound signals with limited range (15 cells). Birds flock toward food calls and scatter on danger calls. Signals don't pass through walls/obstacles. Start with 30 birds.

3. **Visual Fireflies** — Flash light patterns to signal food (double flash) or danger (rapid flash). Visible only in line-of-sight, blocked by obstacles. Start with 40 fireflies.

4. **Predator Wolves** — Hunt all other species using scent tracking (follow recent movement trails). No cooperation with each other — lone hunters. Start with 10 wolves. Wolves must eat every 50 ticks or die.

## Architecture

### World Engine (src/world/) — BUILD FIRST
- `grid.py`: 100x100 toroidal grid with terrain (open, obstacle, water)
- `entity.py`: Base creature class with position, energy, alive/dead state
- `config.py`: All simulation parameters (grid size, food spawn rate, species counts)
- Food spawns randomly at a rate of 5 per tick, max 200 on grid
- Each tick: all creatures act in randomized order, then food spawns, then cleanup dead
- Standard species interface that all species must implement:
  ```python
  class Species:
      def spawn(self, world, count) -> list[Entity]
      def tick(self, entity, world_state) -> Action
      def render(self, entity) -> str  # single char for ASCII viz
  ```

### Species Modules (src/species/*/) — BUILD IN PARALLEL after world engine
Each species module must:
- Import and use the base Entity class from src/world/entity.py
- Implement the Species interface from src/world/entity.py
- Handle its own communication logic internally
- Creatures lose 1 energy per tick, gain 10 energy from food, die at 0 energy
- Creatures can reproduce when energy > 80 (costs 40 energy)

### Simulation Runner (src/main.py + src/visualize.py) — BUILD LAST
- Loads all species, initializes the world, runs the tick loop
- Outputs:
  a. Live ASCII visualization in terminal (refreshes each tick, use curses or simple print)
  b. Population dynamics CSV: tick, ants, birds, fireflies, wolves, total_food
  c. HTML report with matplotlib charts: population over time, extinction events marked, final territory heatmap per species

## Technical Requirements
- Python 3.11+
- Only stdlib + matplotlib for charts (no numpy, no pygame, no external sim frameworks)
- Each species file must be fully self-contained (no cross-species imports)
- Total codebase should be under 2000 lines

## File Scope per Agent
- **Agent world-engine**: src/world/__init__.py, src/world/grid.py, src/world/entity.py, src/world/config.py
- **Agent ants**: src/species/ants/__init__.py, src/species/ants/ant.py
- **Agent birds**: src/species/birds/__init__.py, src/species/birds/bird.py
- **Agent fireflies**: src/species/fireflies/__init__.py, src/species/fireflies/firefly.py
- **Agent wolves**: src/species/wolves/__init__.py, src/species/wolves/wolf.py
- **Agent runner**: src/main.py, src/visualize.py, src/__init__.py, output/
