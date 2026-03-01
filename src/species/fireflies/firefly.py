"""Visual Fireflies species — flash-based signalling with line-of-sight."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from src.world.entity import Entity, Species, Action
from src.world.config import SimConfig

if TYPE_CHECKING:
    from src.world import World

FLASH_RANGE, FLASH_DURATION, FLASH_COOLDOWN = 20, 2, 5
PREDATOR_DETECT, FLOCK_RADIUS, FLOCK_CHANCE = 6, 8, 0.4


class FireflySpecies(Species):
    """Fireflies that communicate via visual flash signals."""

    def __init__(self) -> None:
        # Active flashes: (x, y, flash_type, tick_created, source_id)
        self._flashes: list[tuple[int, int, str, int, int]] = []

    def spawn(self, world: World, count: int) -> list[Entity]:
        entities: list[Entity] = []
        for _ in range(count):
            x, y = _random_passable(world)
            e = Entity('fireflies', x, y, energy=50.0)
            e.extra = {'flash_cooldown': 0, 'attracted_to': None}
            entities.append(e)
        return entities

    def tick(self, entity: Entity, world: World) -> Action:
        tick = world.tick_count
        grid = world.grid
        ex = entity.extra

        # 1. Expire old flashes
        self._flashes = [
            f for f in self._flashes if tick - f[3] <= FLASH_DURATION
        ]

        # 2. Decrease cooldown
        if ex['flash_cooldown'] > 0:
            ex['flash_cooldown'] -= 1

        # 3-4. Receive visible flashes
        visible: list[tuple[int, int, str]] = []
        for fx, fy, ftype, _, fid in self._flashes:
            if fid == entity.id:
                continue
            if _manhattan(entity.x, entity.y, fx, fy, grid) > FLASH_RANGE:
                continue
            if _line_of_sight(entity.x, entity.y, fx, fy, grid):
                visible.append((fx, fy, ftype))

        # 5. Process received flashes — pick closest of each type
        danger_target: tuple[int, int] | None = None
        food_target: tuple[int, int] | None = None
        for fx, fy, ftype in visible:
            if ftype == 'danger':
                if danger_target is None or _manhattan(entity.x, entity.y, fx, fy, grid) < _manhattan(entity.x, entity.y, *danger_target, grid):
                    danger_target = (fx, fy)
            elif ftype == 'food':
                if food_target is None or _manhattan(entity.x, entity.y, fx, fy, grid) < _manhattan(entity.x, entity.y, *food_target, grid):
                    food_target = (fx, fy)

        if danger_target:
            return Action('move', *_dir_away(entity.x, entity.y, *danger_target, grid))

        if food_target:
            ex['attracted_to'] = food_target

        # 6. At food — eat and signal
        if grid.has_food(entity.x, entity.y):
            self._emit(entity, 'food', tick)
            return Action('eat', dx=0, dy=0)

        # 7. Predator nearby — danger flash and flee
        predator = _nearest_predator(entity, world)
        if predator is not None:
            self._emit(entity, 'danger', tick)
            return Action('move', *_dir_away(entity.x, entity.y, predator.x, predator.y, grid))

        # 8. Attracted to food flash
        if ex['attracted_to'] is not None:
            tx, ty = ex['attracted_to']
            if (entity.x, entity.y) == (tx, ty):
                ex['attracted_to'] = None
            else:
                return Action('move', *_dir_toward(entity.x, entity.y, tx, ty, grid))

        # 10. Reproduce check (before random wander so it fires when idle)
        if entity.can_reproduce(world.config):
            return Action('reproduce')

        return Action('move', *_flock_or_wander(entity, world))

    def render(self, entity: Entity) -> str:
        return 'F' if entity.extra.get('flash_cooldown', 0) >= 4 else 'f'

    def _emit(self, entity: Entity, flash_type: str, tick: int) -> None:
        if entity.extra['flash_cooldown'] <= 0:
            self._flashes.append(
                (entity.x, entity.y, flash_type, tick, entity.id)
            )
            entity.extra['flash_cooldown'] = FLASH_COOLDOWN
# -- pure helpers (module-level) ---------------------------------------------

def _random_passable(world: World) -> tuple[int, int]:
    grid = world.grid
    while True:
        x = random.randint(0, grid.width - 1)
        y = random.randint(0, grid.height - 1)
        if grid.is_passable(x, y):
            return x, y


def _wrap_delta(a: int, b: int, size: int) -> int:
    """Shortest signed delta from a to b on a toroidal axis."""
    d = (b - a) % size
    return d if d <= size // 2 else d - size


def _manhattan(x1: int, y1: int, x2: int, y2: int, grid) -> int:
    dx = abs(_wrap_delta(x1, x2, grid.width))
    dy = abs(_wrap_delta(y1, y2, grid.height))
    return dx + dy


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def _dir_toward(x1: int, y1: int, x2: int, y2: int, grid) -> tuple[int, int]:
    return _sign(_wrap_delta(x1, x2, grid.width)), _sign(_wrap_delta(y1, y2, grid.height))


def _dir_away(x1: int, y1: int, x2: int, y2: int, grid) -> tuple[int, int]:
    dx, dy = _dir_toward(x1, y1, x2, y2, grid)
    return -dx, -dy


def _line_of_sight(x1: int, y1: int, x2: int, y2: int, grid) -> bool:
    """Bresenham line-of-sight with toroidal wrapping."""
    dx = _wrap_delta(x1, x2, grid.width)
    dy = _wrap_delta(y1, y2, grid.height)
    steps = max(abs(dx), abs(dy))
    if steps == 0:
        return True
    sx, sy = _sign(dx), _sign(dy)
    adx, ady = abs(dx), abs(dy)
    # Bresenham
    cx, cy = x1, y1
    if adx >= ady:
        err = adx // 2
        for _ in range(steps):
            cx = (cx + sx) % grid.width
            err -= ady
            if err < 0:
                cy = (cy + sy) % grid.height
                err += adx
            if (cx, cy) != (x2 % grid.width, y2 % grid.height):
                if grid.get_terrain(cx, cy) == 1:
                    return False
    else:
        err = ady // 2
        for _ in range(steps):
            cy = (cy + sy) % grid.height
            err -= adx
            if err < 0:
                cx = (cx + sx) % grid.width
                err += ady
            if (cx, cy) != (x2 % grid.width, y2 % grid.height):
                if grid.get_terrain(cx, cy) == 1:
                    return False
    return True


def _nearest_predator(entity: Entity, world: World) -> Entity | None:
    nearby = world.get_nearby_entities(entity.x, entity.y, PREDATOR_DETECT)
    best, best_d = None, PREDATOR_DETECT + 1
    for e in nearby:
        if e.id == entity.id or e.species_name == 'fireflies':
            continue
        if e.species_name in ('wolves',):
            d = _manhattan(entity.x, entity.y, e.x, e.y, world.grid)
            if d < best_d:
                best, best_d = e, d
    return best


def _flock_or_wander(entity: Entity, world: World) -> tuple[int, int]:
    if random.random() < FLOCK_CHANCE:
        nearby = world.get_nearby_entities(entity.x, entity.y, FLOCK_RADIUS)
        friends = [e for e in nearby if e.id != entity.id and e.species_name == 'fireflies']
        if friends:
            f = min(friends, key=lambda e: _manhattan(entity.x, entity.y, e.x, e.y, world.grid))
            return _dir_toward(entity.x, entity.y, f.x, f.y, world.grid)
    return random.choice([-1, 0, 1]), random.choice([-1, 0, 1])
