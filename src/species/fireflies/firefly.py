"""Visual Fireflies — flash light patterns to signal food or danger."""

import random
from src.world.entity import Entity, Species, Action, DIRECTION_DELTAS
from src.world.grid import Grid
from src.world import config


# Shared flash buffer: list of (x, y, flash_type, tick)
# flash_type: 'food' (double flash) or 'danger' (rapid flash)
_flashes: list[tuple[int, int, str, int]] = []

FLASH_RANGE = 12  # max distance for flash visibility


class FireflySpecies(Species):
    """Fireflies communicate via light flashes, blocked by obstacles (line-of-sight)."""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        global _flashes
        _flashes = []
        entities = []
        for _ in range(count):
            x, y = self._random_open(grid)
            e = Entity(x, y, 'firefly', energy=config.ENERGY_START)
            e.extra['flash_cooldown'] = 0
            entities.append(e)
        return entities

    def tick(self, entity: Entity, grid: Grid, all_entities: list[Entity]) -> Action:
        global _flashes

        # Clean old flashes
        _flashes = [(fx, fy, ft, ftk) for fx, fy, ft, ftk in _flashes
                     if grid.current_tick - ftk <= 2]

        # Decrease cooldown
        if entity.extra.get('flash_cooldown', 0) > 0:
            entity.extra['flash_cooldown'] -= 1

        # If on food, eat and flash food signal
        if grid.has_food(entity.x, entity.y):
            self._flash(entity, grid, 'food')
            return Action.EAT

        # Detect wolves nearby — flash danger
        for e in all_entities:
            if e.alive and e.species_name == 'wolf':
                if grid.distance(entity.x, entity.y, e.x, e.y) <= 6:
                    self._flash(entity, grid, 'danger')
                    return self._flee_from(entity, e.x, e.y, grid)

        # Reproduce if enough energy
        if entity.energy > config.REPRODUCE_THRESHOLD:
            return Action.REPRODUCE

        # React to visible flashes
        food_flashes = []
        danger_flashes = []
        for fx, fy, ftype, ftk in _flashes:
            dist = grid.distance(entity.x, entity.y, fx, fy)
            if 0 < dist <= FLASH_RANGE:
                if grid.has_line_of_sight(entity.x, entity.y, fx, fy):
                    if ftype == 'food':
                        food_flashes.append((fx, fy, dist))
                    else:
                        danger_flashes.append((fx, fy, dist))

        # Flee from danger
        if danger_flashes:
            closest = min(danger_flashes, key=lambda f: f[2])
            return self._flee_from(entity, closest[0], closest[1], grid)

        # Move toward food flashes
        if food_flashes:
            closest = min(food_flashes, key=lambda f: f[2])
            return self._move_toward(entity, closest[0], closest[1], grid)

        # Direct food search in small radius
        food = grid.find_nearest_food(entity.x, entity.y, radius=4)
        if food:
            return self._move_toward(entity, food[0], food[1], grid)

        # Random wander with slight bias toward other fireflies
        nearby = [e for e in all_entities if e.alive and e.species_name == 'firefly'
                  and e is not entity
                  and grid.distance(entity.x, entity.y, e.x, e.y) <= 6]
        if nearby and self.rng.random() < 0.2:
            target = self.rng.choice(nearby)
            return self._move_toward(entity, target.x, target.y, grid)

        return self.rng.choice([Action.MOVE_N, Action.MOVE_S,
                                Action.MOVE_E, Action.MOVE_W])

    def render(self, entity: Entity) -> str:
        return 'f'

    def _flash(self, entity: Entity, grid: Grid, flash_type: str) -> None:
        global _flashes
        if entity.extra.get('flash_cooldown', 0) <= 0:
            _flashes.append((entity.x, entity.y, flash_type, grid.current_tick))
            entity.extra['flash_cooldown'] = 3

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

    def _flee_from(self, entity: Entity, fx: int, fy: int,
                   grid: Grid) -> Action:
        dx = entity.x - fx
        dy = entity.y - fy
        if abs(dx) > grid.width // 2:
            dx = -dx
        if abs(dy) > grid.height // 2:
            dy = -dy
        dx = 1 if dx > 0 else (-1 if dx < 0 else 0)
        dy = 1 if dy > 0 else (-1 if dy < 0 else 0)
        if dx == 0 and dy == 0:
            return self.rng.choice([Action.MOVE_N, Action.MOVE_S,
                                    Action.MOVE_E, Action.MOVE_W])
        for action, (adx, ady) in DIRECTION_DELTAS.items():
            if adx == dx and ady == dy:
                return action
        if abs(dx) >= abs(dy):
            return Action.MOVE_E if dx > 0 else Action.MOVE_W
        return Action.MOVE_S if dy > 0 else Action.MOVE_N
