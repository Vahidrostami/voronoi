"""Pheromone Ants — leave chemical trails that decay over time."""

import random
from src.world.entity import Entity, Species, Action, DIRECTION_DELTAS
from src.world.grid import Grid
from src.world import config


class PheromoneMap:
    """Grid-sized pheromone layer that decays each tick."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.food_trail: list[list[float]] = [
            [0.0] * width for _ in range(height)
        ]
        self.decay_rate = 0.95
        self.deposit_amount = 10.0

    def deposit(self, x: int, y: int, amount: float | None = None) -> None:
        amt = amount if amount is not None else self.deposit_amount
        self.food_trail[y % self.height][x % self.width] += amt

    def get(self, x: int, y: int) -> float:
        return self.food_trail[y % self.height][x % self.width]

    def decay(self) -> None:
        for y in range(self.height):
            for x in range(self.width):
                self.food_trail[y][x] *= self.decay_rate
                if self.food_trail[y][x] < 0.01:
                    self.food_trail[y][x] = 0.0


# Shared pheromone map (initialized on first spawn)
_pheromone_map: PheromoneMap | None = None


class AntSpecies(Species):
    """Ants follow pheromone gradients toward food."""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        global _pheromone_map
        _pheromone_map = PheromoneMap(grid.width, grid.height)

        entities = []
        for _ in range(count):
            x, y = self._random_open(grid)
            e = Entity(x, y, 'ant', energy=config.ENERGY_START)
            e.extra['carrying_food'] = False
            entities.append(e)
        return entities

    def tick(self, entity: Entity, grid: Grid, all_entities: list[Entity]) -> Action:
        global _pheromone_map
        if _pheromone_map is None:
            return Action.IDLE

        # Decay pheromones periodically (once per tick, keyed on first ant)
        if entity.extra.get('_decay_done') != grid.current_tick:
            _pheromone_map.decay()
            # Mark all ants as decayed this tick
            for e in all_entities:
                if e.species_name == 'ant' and e.alive:
                    e.extra['_decay_done'] = grid.current_tick

        # If on food, eat it
        if grid.has_food(entity.x, entity.y):
            _pheromone_map.deposit(entity.x, entity.y, 20.0)
            return Action.EAT

        # Reproduce if enough energy
        if entity.energy > config.REPRODUCE_THRESHOLD:
            return Action.REPRODUCE

        # Follow pheromone gradient or wander
        neighbors = grid.get_neighbors(entity.x, entity.y, radius=1)
        if not neighbors:
            return Action.IDLE

        # Check for nearby food directly (short range sensing)
        for nx, ny in neighbors:
            if grid.has_food(nx, ny):
                return self._move_toward(entity, nx, ny, grid)

        # Follow strongest pheromone
        best_pos = None
        best_val = 0.0
        for nx, ny in neighbors:
            val = _pheromone_map.get(nx, ny)
            if val > best_val:
                best_val = val
                best_pos = (nx, ny)

        if best_pos and best_val > 0.1 and self.rng.random() < 0.8:
            # Deposit trail while following
            _pheromone_map.deposit(entity.x, entity.y, 2.0)
            return self._move_toward(entity, best_pos[0], best_pos[1], grid)

        # Random wander — also deposit a small amount
        _pheromone_map.deposit(entity.x, entity.y, 0.5)
        return self.rng.choice([Action.MOVE_N, Action.MOVE_S,
                                Action.MOVE_E, Action.MOVE_W])

    def render(self, entity: Entity) -> str:
        return 'a'

    def _random_open(self, grid: Grid) -> tuple[int, int]:
        while True:
            x = self.rng.randint(0, grid.width - 1)
            y = self.rng.randint(0, grid.height - 1)
            if grid.is_passable(x, y):
                return x, y

    def _move_toward(self, entity: Entity, tx: int, ty: int,
                     grid: Grid) -> Action:
        dx = tx - entity.x
        dy = ty - entity.y
        # Handle wrapping
        if abs(dx) > grid.width // 2:
            dx = -1 if dx > 0 else 1
        else:
            dx = 1 if dx > 0 else (-1 if dx < 0 else 0)
        if abs(dy) > grid.height // 2:
            dy = -1 if dy > 0 else 1
        else:
            dy = 1 if dy > 0 else (-1 if dy < 0 else 0)

        for action, (adx, ady) in DIRECTION_DELTAS.items():
            if adx == dx and ady == dy:
                return action
        # Fallback: move in primary direction
        if abs(dx) >= abs(dy):
            return Action.MOVE_E if dx > 0 else Action.MOVE_W
        return Action.MOVE_S if dy > 0 else Action.MOVE_N
