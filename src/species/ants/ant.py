"""Pheromone Ants species — foraging with pheromone trails."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from src.world.entity import Entity, Species, Action
from src.world.config import SimConfig

if TYPE_CHECKING:
    from src.world import World

_PHEROMONE_DECAY = 0.995
_PHEROMONE_MIN = 0.01
_STRONG_PHEROMONE = 1.0
_WEAK_PHEROMONE = 0.1
_FOLLOW_PROBABILITY = 0.7
_SENSE_RADIUS = 2


class AntSpecies(Species):
    """Colony of ants that communicate via pheromone trails."""

    def __init__(self) -> None:
        self._pheromones: dict[tuple[int, int], float] = {}

    # ------------------------------------------------------------------
    # Species interface
    # ------------------------------------------------------------------

    def spawn(self, world: World, count: int) -> list[Entity]:
        entities: list[Entity] = []
        grid = world.grid
        for _ in range(count):
            x, y = _random_passable(grid)
            ent = Entity(species_name="ant", x=x, y=y, energy=50.0)
            ent.extra = {"carrying_food": False, "home_x": x, "home_y": y}
            entities.append(ent)
        return entities

    def tick(self, entity: Entity, world: World) -> Action:
        self._decay_pheromones()

        ex = entity.extra
        x, y = entity.x, entity.y
        grid = world.grid

        # --- Carrying food: head home ---
        if ex["carrying_food"]:
            self._drop(x, y, _STRONG_PHEROMONE)
            hx, hy = ex["home_x"], ex["home_y"]
            if x == hx and y == hy:
                ex["carrying_food"] = False
                return Action("eat", data=None)
            dx, dy = _step_toward(x, y, hx, hy, grid)
            return Action("move", dx=dx, dy=dy)

        # --- Not carrying: forage ---
        if grid.has_food(x, y):
            ex["carrying_food"] = True
            return Action("eat", dx=0, dy=0)

        # Sense pheromones and decide direction
        dx, dy = self._forage_direction(x, y, grid)
        self._drop(x, y, _WEAK_PHEROMONE)

        # Reproduction check
        if entity.can_reproduce(world.config):
            return Action("reproduce")

        return Action("move", dx=dx, dy=dy)

    def render(self, entity: Entity) -> str:
        return "A" if entity.extra.get("carrying_food") else "a"

    # ------------------------------------------------------------------
    # Pheromone helpers
    # ------------------------------------------------------------------

    def _decay_pheromones(self) -> None:
        to_remove: list[tuple[int, int]] = []
        for pos, val in self._pheromones.items():
            val *= _PHEROMONE_DECAY
            if val < _PHEROMONE_MIN:
                to_remove.append(pos)
            else:
                self._pheromones[pos] = val
        for pos in to_remove:
            del self._pheromones[pos]

    def _drop(self, x: int, y: int, strength: float) -> None:
        self._pheromones[(x, y)] = min(
            self._pheromones.get((x, y), 0.0) + strength, 5.0
        )

    def _forage_direction(self, x: int, y: int, grid) -> tuple[int, int]:
        """Pick a movement direction based on pheromone gradient or random exploration."""
        if random.random() < _FOLLOW_PROBABILITY:
            neighbors = grid.get_neighbors(x, y, radius=_SENSE_RADIUS)
            best_pos = None
            best_val = 0.0
            for nx, ny in neighbors:
                val = self._pheromones.get((nx, ny), 0.0)
                if val > best_val:
                    best_val = val
                    best_pos = (nx, ny)
            if best_pos is not None:
                return _direction(x, y, best_pos[0], best_pos[1])

        # Random exploration
        return random.choice([(-1, 0), (1, 0), (0, -1), (0, 1),
                              (-1, -1), (-1, 1), (1, -1), (1, 1)])


# ------------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------------

def _random_passable(grid) -> tuple[int, int]:
    """Return a random passable (x, y) on the grid."""
    while True:
        x = random.randint(0, grid.width - 1)
        y = random.randint(0, grid.height - 1)
        if grid.is_passable(x, y):
            return x, y


def _direction(fx: int, fy: int, tx: int, ty: int) -> tuple[int, int]:
    """Return a unit-step (dx, dy) from (fx,fy) toward (tx,ty)."""
    dx = 0 if tx == fx else (1 if tx > fx else -1)
    dy = 0 if ty == fy else (1 if ty > fy else -1)
    return dx, dy


def _step_toward(x: int, y: int, tx: int, ty: int, grid) -> tuple[int, int]:
    """Return a passable unit-step from (x,y) toward (tx,ty), with wrapping awareness."""
    w, h = grid.width, grid.height
    # Shortest path on torus
    raw_dx = tx - x
    if abs(raw_dx) > w // 2:
        raw_dx = -raw_dx
    raw_dy = ty - y
    if abs(raw_dy) > h // 2:
        raw_dy = -raw_dy

    dx = 0 if raw_dx == 0 else (1 if raw_dx > 0 else -1)
    dy = 0 if raw_dy == 0 else (1 if raw_dy > 0 else -1)

    # Prefer the combined step if passable
    nx, ny = grid.wrap(x + dx, y + dy)
    if grid.is_passable(nx, ny):
        return dx, dy
    # Fall back to axis-aligned steps
    if dx != 0:
        nx2, ny2 = grid.wrap(x + dx, y)
        if grid.is_passable(nx2, ny2):
            return dx, 0
    if dy != 0:
        nx3, ny3 = grid.wrap(x, y + dy)
        if grid.is_passable(nx3, ny3):
            return 0, dy
    return 0, 0
