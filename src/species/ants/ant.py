"""Pheromone Ants — leave chemical trails that decay over time."""

import random
from src.world.entity import Entity, Species, Action, ActionCommand, DIRECTION_DELTAS
from src.world.config import (
    GRID_WIDTH, GRID_HEIGHT, ENERGY_PER_FOOD, ENERGY_LOSS_PER_TICK,
    REPRODUCE_THRESHOLD, REPRODUCE_COST, ANT_PHEROMONE_DECAY, INITIAL_ANTS,
    ENERGY_START,
)
from src.world.grid import Grid, Terrain

# Ant states
FORAGING = 'foraging'
RETURNING = 'returning'

# Movement probabilities
PHEROMONE_FOLLOW_CHANCE = 0.8
MAX_PATH_MEMORY = 50


class PheromoneMap:
    """100x100 grid of floats (0.0-1.0) tracking trail intensity."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.grid: list[list[float]] = [
            [0.0] * width for _ in range(height)
        ]

    def deposit(self, x: int, y: int, amount: float = 1.0) -> None:
        """Deposit pheromone, clamped to [0.0, 1.0]."""
        wx, wy = x % self.width, y % self.height
        self.grid[wy][wx] = min(1.0, self.grid[wy][wx] + amount)

    def get(self, x: int, y: int) -> float:
        return self.grid[y % self.height][x % self.width]

    def decay(self, rate: float = ANT_PHEROMONE_DECAY) -> None:
        """Decay all pheromones by rate (subtracted). Values below threshold zeroed."""
        for y in range(self.height):
            row = self.grid[y]
            for x in range(self.width):
                row[x] -= rate
                if row[x] < 0.001:
                    row[x] = 0.0

    def deposit_path(self, path: list[tuple[int, int]], strength: float = 1.0) -> None:
        """Deposit pheromone along a path with decaying strength."""
        n = len(path)
        for i, (px, py) in enumerate(path):
            # Stronger near food (end of path), weaker near home
            frac = (i + 1) / n if n > 0 else 1.0
            self.deposit(px, py, strength * frac)


class AntSpecies(Species):
    """Ants follow pheromone gradients toward food.

    Manages a shared pheromone grid internally. Each ant tracks home position,
    has_food boolean, state (FORAGING/RETURNING), and path memory.
    """

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.pheromone_map: PheromoneMap | None = None
        self._decay_tick: int = -1  # track which tick we last decayed on

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        self.pheromone_map = PheromoneMap(grid.width, grid.height)
        entities: list[Entity] = []
        for _ in range(count):
            x, y = self._random_open(grid)
            e = Entity(x, y, 'ant', energy=ENERGY_START)
            e.extra['state'] = FORAGING
            e.extra['has_food'] = False
            e.extra['home'] = (x, y)
            e.extra['path'] = []  # list of recent (x,y) positions
            entities.append(e)
        return entities

    def tick(self, entity: Entity, grid: Grid,
             all_entities: list[Entity]) -> ActionCommand:
        pmap = self.pheromone_map
        if pmap is None:
            return ActionCommand(type='idle')

        # Decay pheromones once per tick (keyed on grid.current_tick)
        if self._decay_tick != grid.current_tick:
            pmap.decay()
            self._decay_tick = grid.current_tick

        # Record current position in path memory
        path: list = entity.extra['path']
        path.append((entity.x, entity.y))
        if len(path) > MAX_PATH_MEMORY:
            path.pop(0)

        state = entity.extra['state']

        # --- RETURNING state: go home, deposit pheromone ---
        if state == RETURNING:
            return self._tick_returning(entity, grid, pmap)

        # --- FORAGING state ---
        return self._tick_foraging(entity, grid, pmap)

    def render(self, entity: Entity) -> str:
        return 'a'

    # --- Internal tick helpers ---

    def _tick_foraging(self, entity: Entity, grid: Grid,
                       pmap: PheromoneMap) -> ActionCommand:
        """Foraging: look for food, follow pheromones, or random walk."""
        # If standing on food, eat it and switch to RETURNING
        if grid.has_food(entity.x, entity.y):
            entity.extra['has_food'] = True
            entity.extra['state'] = RETURNING
            # Deposit strong pheromone along remembered path
            pmap.deposit_path(entity.extra['path'], strength=1.0)
            return ActionCommand(type='eat')

        # Reproduce if enough energy
        if entity.energy > REPRODUCE_THRESHOLD:
            return ActionCommand(type='reproduce')

        # Check immediate neighbors for food
        neighbors = grid.get_neighbors(entity.x, entity.y, radius=1)
        if not neighbors:
            return ActionCommand(type='idle')

        for nx, ny in neighbors:
            if grid.has_food(nx, ny):
                dx, dy = self._delta_toward(entity, nx, ny, grid)
                return ActionCommand(type='move', dx=dx, dy=dy)

        # 80% follow strongest pheromone, 20% random walk
        if self.rng.random() < PHEROMONE_FOLLOW_CHANCE:
            best_pos, best_val = None, 0.0
            for nx, ny in neighbors:
                val = pmap.get(nx, ny)
                if val > best_val:
                    best_val = val
                    best_pos = (nx, ny)
            if best_pos and best_val > 0.0:
                dx, dy = self._delta_toward(entity, best_pos[0], best_pos[1], grid)
                return ActionCommand(type='move', dx=dx, dy=dy)

        # Random walk
        return self._random_move()

    def _tick_returning(self, entity: Entity, grid: Grid,
                        pmap: PheromoneMap) -> ActionCommand:
        """Returning: head home, deposit pheromone trail."""
        hx, hy = entity.extra['home']

        # Deposit pheromone at current position
        pmap.deposit(entity.x, entity.y, 0.5)

        # If home, switch back to foraging and clear path
        if entity.x == hx and entity.y == hy:
            entity.extra['state'] = FORAGING
            entity.extra['has_food'] = False
            entity.extra['path'] = []
            return ActionCommand(type='idle')

        # Reproduce if enough energy (even while returning)
        if entity.energy > REPRODUCE_THRESHOLD:
            return ActionCommand(type='reproduce')

        # Move toward home
        dx, dy = self._delta_toward(entity, hx, hy, grid)
        return ActionCommand(type='move', dx=dx, dy=dy)

    # --- Utility methods ---

    def _delta_toward(self, entity: Entity, tx: int, ty: int,
                      grid: Grid) -> tuple[int, int]:
        """Compute (dx, dy) unit delta toward target with toroidal wrapping."""
        raw_dx = tx - entity.x
        raw_dy = ty - entity.y
        # Pick shortest toroidal direction
        if abs(raw_dx) > grid.width // 2:
            dx = -1 if raw_dx > 0 else 1
        else:
            dx = (1 if raw_dx > 0 else -1) if raw_dx != 0 else 0
        if abs(raw_dy) > grid.height // 2:
            dy = -1 if raw_dy > 0 else 1
        else:
            dy = (1 if raw_dy > 0 else -1) if raw_dy != 0 else 0
        return dx, dy

    def _random_move(self) -> ActionCommand:
        """Return a random cardinal move ActionCommand."""
        dx, dy = self.rng.choice([(0, -1), (0, 1), (1, 0), (-1, 0)])
        return ActionCommand(type='move', dx=dx, dy=dy)

    def _random_open(self, grid: Grid) -> tuple[int, int]:
        """Find a random passable cell."""
        while True:
            x = self.rng.randint(0, grid.width - 1)
            y = self.rng.randint(0, grid.height - 1)
            if grid.is_passable(x, y):
                return x, y


if __name__ == '__main__':
    import sys
    sys.path.insert(0, '.')

    print("=== Pheromone Ants Tests ===")

    # --- PheromoneMap tests ---
    pm = PheromoneMap(10, 10)
    assert pm.get(0, 0) == 0.0
    pm.deposit(0, 0, 0.5)
    assert pm.get(0, 0) == 0.5
    pm.deposit(0, 0, 0.7)
    assert pm.get(0, 0) == 1.0, "Should clamp to 1.0"
    # Decay test: ANT_PHEROMONE_DECAY = 0.02
    pm2 = PheromoneMap(5, 5)
    pm2.deposit(2, 2, 1.0)
    pm2.decay()
    assert abs(pm2.get(2, 2) - 0.98) < 0.001, f"After 1 decay: {pm2.get(2, 2)}"
    pm2.decay()
    assert abs(pm2.get(2, 2) - 0.96) < 0.001, f"After 2 decays: {pm2.get(2, 2)}"
    # Decay to zero
    pm3 = PheromoneMap(3, 3)
    pm3.deposit(1, 1, 0.01)
    pm3.decay()
    assert pm3.get(1, 1) == 0.0, "Small values should zero out"
    # Path deposit
    pm4 = PheromoneMap(10, 10)
    pm4.deposit_path([(1, 1), (2, 2), (3, 3)], strength=1.0)
    assert pm4.get(3, 3) > pm4.get(1, 1), "End of path should be stronger"
    assert pm4.get(3, 3) == 1.0
    print("  PheromoneMap: OK")

    # --- AntSpecies spawn test ---
    grid = Grid(width=20, height=20, seed=42)
    grid.terrain = [[Terrain.OPEN] * 20 for _ in range(20)]
    species = AntSpecies(seed=123)
    ants = species.spawn(grid, 5)
    assert len(ants) == 5
    for ant in ants:
        assert ant.species_name == 'ant'
        assert ant.extra['state'] == FORAGING
        assert ant.extra['has_food'] is False
        assert 'home' in ant.extra
        assert ant.extra['path'] == []
        assert ant.energy == ENERGY_START
    assert species.pheromone_map is not None
    print("  Spawn: OK")

    # --- Render test ---
    assert species.render(ants[0]) == 'a'
    print("  Render: OK")

    # --- Tick: random walk when no food/pheromone ---
    grid.current_tick = 1
    cmd = species.tick(ants[0], grid, ants)
    assert cmd.type == 'move', f"Expected move, got {cmd.type}"
    assert (cmd.dx, cmd.dy) != (0, 0), "Should move somewhere"
    print("  Tick (random walk): OK")

    # --- Tick: eat food and switch to RETURNING ---
    ant = ants[1]
    grid.add_food(ant.x, ant.y)
    grid.current_tick = 2
    cmd = species.tick(ant, grid, ants)
    assert cmd.type == 'eat', f"Expected eat, got {cmd.type}"
    assert ant.extra['state'] == RETURNING
    assert ant.extra['has_food'] is True
    grid.remove_food(ant.x, ant.y)
    print("  Tick (eat food → RETURNING): OK")

    # --- Tick: returning ant moves toward home ---
    ant.extra['home'] = (0, 0)
    ant.x, ant.y = 3, 3
    grid.current_tick = 3
    cmd = species.tick(ant, grid, ants)
    assert cmd.type == 'move'
    assert cmd.dx == -1 and cmd.dy == -1, f"Should move toward (0,0): got ({cmd.dx},{cmd.dy})"
    print("  Tick (returning → move home): OK")

    # --- Tick: returning ant arrives home ---
    ant.x, ant.y = 0, 0
    grid.current_tick = 4
    cmd = species.tick(ant, grid, ants)
    assert cmd.type == 'idle'
    assert ant.extra['state'] == FORAGING
    assert ant.extra['has_food'] is False
    assert ant.extra['path'] == []
    print("  Tick (arrived home → FORAGING): OK")

    # --- Tick: follow pheromone gradient ---
    species2 = AntSpecies(seed=999)
    grid2 = Grid(width=10, height=10, seed=0)
    grid2.terrain = [[Terrain.OPEN] * 10 for _ in range(10)]
    ants2 = species2.spawn(grid2, 1)
    a = ants2[0]
    a.x, a.y = 5, 5
    a.extra['home'] = (5, 5)
    # Place strong pheromone to the east
    species2.pheromone_map.deposit(6, 5, 0.9)
    grid2.current_tick = 1
    # Run many ticks: with 80% follow, most should go east
    east_count = 0
    for i in range(100):
        a.x, a.y = 5, 5
        a.extra['path'] = []
        # Re-deposit pheromone so it doesn't fully decay
        species2.pheromone_map.deposit(6, 5, 0.9)
        grid2.current_tick = i + 10
        cmd = species2.tick(a, grid2, ants2)
        if cmd.dx == 1 and cmd.dy == 0:
            east_count += 1
    assert east_count > 60, f"Should follow pheromone east mostly, got {east_count}/100"
    print(f"  Tick (pheromone follow): {east_count}/100 east OK")

    # --- Tick: reproduce when energy high ---
    ant3 = ants[2]
    ant3.energy = REPRODUCE_THRESHOLD + 10
    grid.current_tick = 100
    cmd = species.tick(ant3, grid, ants)
    assert cmd.type == 'reproduce'
    print("  Tick (reproduce): OK")

    # --- Pheromone decay over many ticks ---
    pm5 = PheromoneMap(5, 5)
    pm5.deposit(0, 0, 1.0)
    for _ in range(50):
        pm5.decay()
    # After 50 decays of 0.02 each: 1.0 - 50*0.02 = 0.0
    assert pm5.get(0, 0) == 0.0, f"Should be zero after 50 decays: {pm5.get(0, 0)}"
    print("  Pheromone full decay: OK")

    # --- Path memory tracking ---
    ant4 = ants[3]
    ant4.extra['path'] = []
    ant4.x, ant4.y = 7, 7
    grid.current_tick = 200
    species.tick(ant4, grid, ants)
    assert (7, 7) in ant4.extra['path'], "Path should record position"
    print("  Path memory: OK")

    # --- Decay is once per tick ---
    pm6 = PheromoneMap(5, 5)
    species3 = AntSpecies(seed=42)
    species3.pheromone_map = pm6
    grid3 = Grid(width=5, height=5, seed=0)
    grid3.terrain = [[Terrain.OPEN] * 5 for _ in range(5)]
    ants3 = species3.spawn(grid3, 3)
    species3.pheromone_map = pm6  # re-set after spawn creates new one
    pm6.deposit(2, 2, 1.0)
    grid3.current_tick = 300
    # Tick all 3 ants on same tick — decay should only happen once
    for a in ants3:
        species3.tick(a, grid3, ants3)
    assert abs(pm6.get(2, 2) - 0.98) < 0.01, f"Decay once: {pm6.get(2, 2)}"
    print("  Decay once per tick: OK")

    print("\nAll Pheromone Ants tests passed!")
