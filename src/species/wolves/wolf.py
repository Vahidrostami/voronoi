"""Predator Wolf species — lone hunters that track prey by scent.

Wolves follow scent trails left by non-wolf entities.  They attack adjacent
prey, gain energy from kills, and die if they go too long without eating.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from src.world.entity import Action, Entity, Species, WorldState
from src.world import config

if TYPE_CHECKING:
    from src.world.grid import Grid

# Movement actions and their (dx, dy) offsets
_MOVES: dict[Action, tuple[int, int]] = {
    Action.MOVE_N: (0, -1),
    Action.MOVE_S: (0, 1),
    Action.MOVE_E: (1, 0),
    Action.MOVE_W: (-1, 0),
}

_PATROL_ACTIONS = list(_MOVES.keys())

# Scent decay factor per tick
_SCENT_DECAY = 0.9

# Minimum scent strength to bother tracking
_SCENT_MIN = 0.01

# Energy gained from eating prey
_ENERGY_FROM_PREY = 10


class WolfSpecies(Species):
    """Lone predator wolves that hunt by scent tracking.

    Attributes
    ----------
    scent_map : dict[tuple[int, int], float]
        Maps ``(x, y)`` to a scent intensity.  Updated every tick from
        non-wolf entity positions; decays by ``_SCENT_DECAY`` per tick.
    ticks_since_last_meal : dict[str, int]
        Per-entity hunger counter keyed by entity id.
    """

    name: str = "wolf"

    def __init__(self) -> None:
        self.scent_map: dict[tuple[int, int], float] = {}
        self.ticks_since_last_meal: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Species interface
    # ------------------------------------------------------------------

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        """Place *count* wolves on random passable cells."""
        wolves: list[Entity] = []
        attempts = 0
        while len(wolves) < count and attempts < count * 20:
            x = random.randint(0, grid.width - 1)
            y = random.randint(0, grid.height - 1)
            attempts += 1
            if grid.is_passable(x, y):
                e = Entity(x=x, y=y, energy=config.STARTING_ENERGY, species_name=self.name)
                self.ticks_since_last_meal[e.id] = 0
                wolves.append(e)
        return wolves

    def tick(self, entity: Entity, world_state: WorldState) -> Action:
        """Decide what *entity* should do this tick."""
        if not entity.is_alive():
            return Action.IDLE

        # --- Energy drain ---
        entity.energy += config.ENERGY_PER_TICK

        # --- Hunger tracking ---
        hunger = self.ticks_since_last_meal.get(entity.id, 0) + 1
        self.ticks_since_last_meal[entity.id] = hunger

        if hunger > config.WOLF_HUNGER_LIMIT:
            entity.alive = False
            return Action.IDLE

        if entity.energy <= 0:
            entity.alive = False
            return Action.IDLE

        # --- Update scent map from prey positions ---
        self._update_scent(world_state)

        # --- Reproduction ---
        if entity.energy >= config.REPRODUCE_THRESHOLD:
            return Action.REPRODUCE

        # --- Attack adjacent prey ---
        adjacent = world_state.nearby_entities(entity.position, radius=1)
        prey = [e for e in adjacent if e.species_name != self.name and e.is_alive()]
        if prey:
            target = prey[0]
            target.alive = False
            entity.energy += _ENERGY_FROM_PREY
            self.ticks_since_last_meal[entity.id] = 0
            return self._move_toward(entity, target.x, target.y, world_state)

        # --- Follow scent ---
        best_action = self._follow_scent(entity, world_state)
        if best_action is not None:
            return best_action

        # --- Random patrol ---
        return random.choice(_PATROL_ACTIONS)

    def render(self, entity: Entity) -> str:
        """Return the display character for a wolf."""
        return "W"

    # ------------------------------------------------------------------
    # Scent system
    # ------------------------------------------------------------------

    def _update_scent(self, world_state: WorldState) -> None:
        """Decay existing scent and deposit new scent from non-wolf entities."""
        # Decay
        to_remove: list[tuple[int, int]] = []
        for pos, strength in self.scent_map.items():
            new_val = strength * _SCENT_DECAY
            if new_val < _SCENT_MIN:
                to_remove.append(pos)
            else:
                self.scent_map[pos] = new_val
        for pos in to_remove:
            del self.scent_map[pos]

        # Deposit scent for every living non-wolf entity
        for e in world_state.entities:
            if e.is_alive() and e.species_name != self.name:
                self.scent_map[(e.x, e.y)] = 1.0

    def _follow_scent(self, entity: Entity, world_state: WorldState) -> Action | None:
        """Move toward the adjacent cell with the strongest scent, if any."""
        grid = world_state.grid
        best_strength = 0.0
        best_action: Action | None = None

        for action, (dx, dy) in _MOVES.items():
            nx, ny = grid.wrap(entity.x + dx, entity.y + dy)
            if not grid.is_passable(nx, ny):
                continue
            strength = self.scent_map.get((nx, ny), 0.0)
            if strength > best_strength:
                best_strength = strength
                best_action = action

        return best_action

    def _move_toward(self, entity: Entity, tx: int, ty: int, world_state: WorldState) -> Action:
        """Return the action that moves *entity* toward *(tx, ty)*."""
        grid = world_state.grid
        ex, ey = entity.x, entity.y

        # Toroidal delta — pick shortest direction
        dx = (tx - ex + grid.width // 2) % grid.width - grid.width // 2
        dy = (ty - ey + grid.height // 2) % grid.height - grid.height // 2

        if abs(dx) >= abs(dy):
            return Action.MOVE_E if dx > 0 else Action.MOVE_W
        else:
            return Action.MOVE_S if dy > 0 else Action.MOVE_N
