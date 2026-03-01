"""Sonic Birds — emit sound signals to flock toward food and scatter from danger."""

import random
from src.world.entity import Entity, Species, Action, DIRECTION_DELTAS
from src.world.grid import Grid
from src.world import config


# Shared signal buffer: list of (x, y, signal_type, tick)
_signals: list[tuple[int, int, str, int]] = []


class BirdSpecies(Species):
    """Birds communicate via sound signals within range, blocked by obstacles."""

    SOUND_RANGE = config.BIRD_SOUND_RANGE

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        global _signals
        _signals = []
        entities = []
        for _ in range(count):
            x, y = self._random_open(grid)
            e = Entity(x, y, 'bird', energy=config.ENERGY_START)
            e.extra['last_signal_tick'] = -10
            entities.append(e)
        return entities

    def tick(self, entity: Entity, grid: Grid, all_entities: list[Entity]) -> Action:
        global _signals

        # Clean old signals
        _signals = [(sx, sy, st, stk) for sx, sy, st, stk in _signals
                     if grid.current_tick - stk <= 3]

        # If on food, eat and broadcast food signal
        if grid.has_food(entity.x, entity.y):
            self._emit_signal(entity, grid, 'food')
            return Action.EAT

        # Check for nearby wolves (danger detection within 5 cells)
        for e in all_entities:
            if e.alive and e.species_name == 'wolf':
                if grid.distance(entity.x, entity.y, e.x, e.y) <= 5:
                    self._emit_signal(entity, grid, 'danger')
                    return self._flee_from(entity, e.x, e.y, grid)

        # Reproduce if enough energy
        if entity.energy > config.REPRODUCE_THRESHOLD:
            return Action.REPRODUCE

        # Listen for signals
        food_signals = []
        danger_signals = []
        for sx, sy, stype, stk in _signals:
            dist = grid.distance(entity.x, entity.y, sx, sy)
            if dist <= self.SOUND_RANGE and dist > 0:
                # Sound blocked by obstacles
                if grid.has_line_of_sight(entity.x, entity.y, sx, sy):
                    if stype == 'food':
                        food_signals.append((sx, sy, dist))
                    else:
                        danger_signals.append((sx, sy, dist))

        # React to danger first — scatter away
        if danger_signals:
            closest = min(danger_signals, key=lambda s: s[2])
            return self._flee_from(entity, closest[0], closest[1], grid)

        # Move toward food signals
        if food_signals:
            closest = min(food_signals, key=lambda s: s[2])
            return self._move_toward(entity, closest[0], closest[1], grid)

        # Look for food directly in small radius
        food = grid.find_nearest_food(entity.x, entity.y, radius=5)
        if food:
            return self._move_toward(entity, food[0], food[1], grid)

        # Flock behavior — move toward nearby birds
        nearby_birds = [e for e in all_entities if e.alive and e.species_name == 'bird'
                        and e is not entity
                        and grid.distance(entity.x, entity.y, e.x, e.y) <= 8]
        if nearby_birds and self.rng.random() < 0.3:
            target = self.rng.choice(nearby_birds)
            return self._move_toward(entity, target.x, target.y, grid)

        # Random wander
        return self.rng.choice([Action.MOVE_N, Action.MOVE_S,
                                Action.MOVE_E, Action.MOVE_W])

    def render(self, entity: Entity) -> str:
        return 'b'

    def _emit_signal(self, entity: Entity, grid: Grid, signal_type: str) -> None:
        global _signals
        if grid.current_tick - entity.extra.get('last_signal_tick', -10) >= 3:
            _signals.append((entity.x, entity.y, signal_type, grid.current_tick))
            entity.extra['last_signal_tick'] = grid.current_tick

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
