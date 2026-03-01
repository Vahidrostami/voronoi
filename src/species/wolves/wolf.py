"""Predator Wolves — lone hunters that track prey by scent."""

import random
from src.world.entity import Entity, Species, Action, DIRECTION_DELTAS
from src.world.grid import Grid
from src.world import config


PREY_SPECIES = {'ant', 'bird', 'firefly'}
HUNT_RANGE = 8
SCENT_RANGE = 3


class WolfSpecies(Species):
    """Wolves hunt all other species using scent tracking. Must eat every 50 ticks or die."""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        entities = []
        for _ in range(count):
            x, y = self._random_open(grid)
            e = Entity(x, y, 'wolf', energy=config.ENERGY_START)
            e.extra['ticks_since_eat'] = 0
            entities.append(e)
        return entities

    def tick(self, entity: Entity, grid: Grid, all_entities: list[Entity]) -> Action:
        entity.extra['ticks_since_eat'] = entity.extra.get('ticks_since_eat', 0) + 1

        # Starve if haven't eaten in WOLF_HUNGER_LIMIT ticks
        if entity.extra['ticks_since_eat'] >= config.WOLF_HUNGER_LIMIT:
            entity.alive = False
            return Action.IDLE

        # Try to catch prey at current position
        prey_here = [e for e in all_entities if e.alive
                     and e.species_name in PREY_SPECIES
                     and e.x == entity.x and e.y == entity.y]
        if prey_here:
            victim = prey_here[0]
            victim.alive = False
            entity.energy += 15
            entity.extra['ticks_since_eat'] = 0
            return Action.IDLE  # eating takes the turn

        # Reproduce if well-fed
        if (entity.energy > config.REPRODUCE_THRESHOLD
                and entity.extra['ticks_since_eat'] < 10):
            return Action.REPRODUCE

        # Hunt: find nearest visible prey
        nearest_prey = None
        nearest_dist = HUNT_RANGE + 1
        for e in all_entities:
            if e.alive and e.species_name in PREY_SPECIES:
                d = grid.distance(entity.x, entity.y, e.x, e.y)
                if d < nearest_dist:
                    nearest_prey = e
                    nearest_dist = d

        if nearest_prey and nearest_dist <= HUNT_RANGE:
            return self._move_toward(entity, nearest_prey.x, nearest_prey.y, grid)

        # Follow scent trails
        best_scent_pos = None
        best_scent_score = 0
        neighbors = grid.get_neighbors(entity.x, entity.y, radius=SCENT_RANGE)
        for nx, ny in neighbors:
            scents = grid.get_scent(nx, ny, max_age=20)
            prey_scents = [(s, t) for s, t in scents if s in PREY_SPECIES]
            if prey_scents:
                # Score by recency
                score = sum(1.0 / (grid.current_tick - t + 1) for _, t in prey_scents)
                if score > best_scent_score:
                    best_scent_score = score
                    best_scent_pos = (nx, ny)

        if best_scent_pos:
            return self._move_toward(entity, best_scent_pos[0], best_scent_pos[1], grid)

        # Random wander — wolves move faster (pick two directions)
        return self.rng.choice([Action.MOVE_N, Action.MOVE_S,
                                Action.MOVE_E, Action.MOVE_W,
                                Action.MOVE_NE, Action.MOVE_NW,
                                Action.MOVE_SE, Action.MOVE_SW])

    def render(self, entity: Entity) -> str:
        return 'W'

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
        if abs(dx) >= abs(dy):
            return Action.MOVE_E if dx > 0 else Action.MOVE_W
        return Action.MOVE_S if dy > 0 else Action.MOVE_N
