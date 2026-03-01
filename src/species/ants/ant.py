"""Pheromone Ants — trail-following colony species.

Ants leave pheromone trails that decay over time.  They forage for food
using a simple priority: seek visible food → follow pheromone gradient →
random walk.  On eating, ants reinforce the trail from their position back
toward the colony centre.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from src.world.entity import Action, Entity, Species, WorldState
from src.world import config

if TYPE_CHECKING:
    from src.world.grid import Grid


# Direction deltas keyed by Action
_MOVE_DELTAS: dict[Action, tuple[int, int]] = {
    Action.MOVE_N: (0, -1),
    Action.MOVE_S: (0, 1),
    Action.MOVE_E: (1, 0),
    Action.MOVE_W: (-1, 0),
}

_MOVE_ACTIONS: list[Action] = list(_MOVE_DELTAS.keys())

# Pheromone constants
_PHEROMONE_DECAY: float = 0.95
_PHEROMONE_DEPOSIT: float = 1.0
_PHEROMONE_MIN: float = 0.01  # prune below this


class AntSpecies(Species):
    """Colony of pheromone-trail-following ants."""

    name: str = "ant"

    def __init__(self) -> None:
        # Shared pheromone map: (x, y) -> strength
        self.pheromones: dict[tuple[int, int], float] = {}
        # Colony centre — set during spawn
        self._colony: tuple[int, int] = (0, 0)

    # ------------------------------------------------------------------
    # Species interface
    # ------------------------------------------------------------------

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        """Place *count* ants on random passable cells."""
        passable: list[tuple[int, int]] = [
            (x, y) for x, y, t in grid
            if grid.is_passable(x, y)
        ]
        rng = random.Random()
        rng.shuffle(passable)
        positions = passable[:count]

        # Colony centre is the mean position of the initial spawn
        if positions:
            cx = sum(p[0] for p in positions) // len(positions)
            cy = sum(p[1] for p in positions) // len(positions)
            self._colony = (cx, cy)

        entities: list[Entity] = []
        for x, y in positions:
            e = Entity(x=x, y=y, energy=config.STARTING_ENERGY, species_name=self.name)
            entities.append(e)
        return entities

    def tick(self, entity: Entity, world_state: WorldState) -> Action:
        """Decide the action for *entity* this tick.

        Priority:
        1. Enough energy to reproduce → reproduce.
        2. Standing on food → eat.
        3. Food nearby → move toward closest food.
        4. Pheromone gradient → follow strongest nearby trail.
        5. Otherwise → random walk.

        Side-effects (pheromone bookkeeping) happen here too.
        """
        # --- decay pheromones (once per tick — first entity acts as trigger) ---
        # We decay lazily; it's cheap enough and simpler than a separate hook.
        self._decay_pheromones()

        # --- deposit pheromone at current location ---
        pos = entity.position
        self.pheromones[pos] = self.pheromones.get(pos, 0.0) + _PHEROMONE_DEPOSIT

        # --- reproduction ---
        if entity.energy >= config.REPRODUCE_THRESHOLD:
            return Action.REPRODUCE

        # --- eat if food at feet ---
        if world_state.grid.has_food(entity.x, entity.y):
            self._reinforce_trail_to_colony(entity, world_state.grid)
            return Action.EAT

        # --- move toward nearby food ---
        food = world_state.nearby_food(pos, radius=5)
        if food:
            return self._move_toward(entity, min(food, key=lambda f: _dist(pos, f, world_state.grid)), world_state.grid)

        # --- follow pheromone gradient ---
        best_action = self._follow_pheromone(entity, world_state.grid)
        if best_action is not None:
            return best_action

        # --- random walk ---
        return self._random_move(entity, world_state.grid)

    def render(self, entity: Entity) -> str:
        """Return display character for an ant."""
        return "a"

    # ------------------------------------------------------------------
    # Pheromone helpers
    # ------------------------------------------------------------------

    def _decay_pheromones(self) -> None:
        """Decay all pheromone values and prune negligible ones."""
        to_delete: list[tuple[int, int]] = []
        for pos, strength in self.pheromones.items():
            new = strength * _PHEROMONE_DECAY
            if new < _PHEROMONE_MIN:
                to_delete.append(pos)
            else:
                self.pheromones[pos] = new
        for pos in to_delete:
            del self.pheromones[pos]

    def _reinforce_trail_to_colony(self, entity: Entity, grid: Grid) -> None:
        """Strengthen pheromone trail from entity position toward colony."""
        x, y = entity.x, entity.y
        cx, cy = self._colony
        steps = max(abs(cx - x), abs(cy - y))
        if steps == 0:
            return
        for i in range(steps + 1):
            ix = x + round((cx - x) * i / steps)
            iy = y + round((cy - y) * i / steps)
            wp = grid.wrap(ix, iy)
            self.pheromones[wp] = self.pheromones.get(wp, 0.0) + _PHEROMONE_DEPOSIT

    def _follow_pheromone(self, entity: Entity, grid: Grid) -> Action | None:
        """Move toward the neighbouring cell with the strongest pheromone."""
        best_strength = 0.0
        best_action: Action | None = None
        for action, (dx, dy) in _MOVE_DELTAS.items():
            nx, ny = grid.wrap(entity.x + dx, entity.y + dy)
            if not grid.is_passable(nx, ny):
                continue
            strength = self.pheromones.get((nx, ny), 0.0)
            if strength > best_strength:
                best_strength = strength
                best_action = action
        return best_action

    def _move_toward(self, entity: Entity, target: tuple[int, int], grid: Grid) -> Action:
        """Return the best movement action to approach *target*."""
        tx, ty = target
        ex, ey = entity.x, entity.y
        w, h = grid.width, grid.height

        # Toroidal signed distance
        dx = (tx - ex + w // 2) % w - w // 2
        dy = (ty - ey + h // 2) % h - h // 2

        candidates: list[Action] = []
        if dx > 0:
            candidates.append(Action.MOVE_E)
        elif dx < 0:
            candidates.append(Action.MOVE_W)
        if dy > 0:
            candidates.append(Action.MOVE_S)
        elif dy < 0:
            candidates.append(Action.MOVE_N)

        # Prefer passable candidates
        for action in candidates:
            ddx, ddy = _MOVE_DELTAS[action]
            nx, ny = grid.wrap(ex + ddx, ey + ddy)
            if grid.is_passable(nx, ny):
                return action

        return self._random_move(entity, grid)

    @staticmethod
    def _random_move(entity: Entity, grid: Grid) -> Action:
        """Return a random passable movement action (or IDLE)."""
        actions = list(_MOVE_ACTIONS)
        random.shuffle(actions)
        for action in actions:
            dx, dy = _MOVE_DELTAS[action]
            nx, ny = grid.wrap(entity.x + dx, entity.y + dy)
            if grid.is_passable(nx, ny):
                return action
        return Action.IDLE


def _dist(a: tuple[int, int], b: tuple[int, int], grid: Grid) -> int:
    """Chebyshev distance on a toroidal grid."""
    dx = min(abs(a[0] - b[0]), grid.width - abs(a[0] - b[0]))
    dy = min(abs(a[1] - b[1]), grid.height - abs(a[1] - b[1]))
    return max(dx, dy)
