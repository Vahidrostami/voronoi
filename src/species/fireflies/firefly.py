"""Visual Fireflies species — light flash signalling system.

Fireflies communicate via light patterns visible in line-of-sight only:
- DOUBLE_FLASH: food signal (two quick flashes)
- RAPID_FLASH: danger signal (fast repeated flashes)
"""

from __future__ import annotations

import enum
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.world.entity import Action, Entity, Species, WorldState
from src.world import config

if TYPE_CHECKING:
    from src.world.grid import Grid


# ---------------------------------------------------------------------------
# Flash signal types
# ---------------------------------------------------------------------------

class FlashSignal(enum.Enum):
    """Light flash patterns a firefly can emit."""
    NONE = "none"
    DOUBLE_FLASH = "double_flash"  # food signal
    RAPID_FLASH = "rapid_flash"    # danger signal


# ---------------------------------------------------------------------------
# Per-firefly state stored alongside Entity
# ---------------------------------------------------------------------------

@dataclass
class FireflyState:
    """Extra per-firefly state tracked by the species logic."""
    flash_state: FlashSignal = FlashSignal.NONE
    flash_cooldown: int = 0


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FLASH_COOLDOWN_TICKS = 5
_SIGHT_RADIUS = 5
_DANGER_SPECIES = ("wolf",)
_STARTING_COUNT = config.FIREFLY_COUNT  # 40


# ---------------------------------------------------------------------------
# FireflySpecies
# ---------------------------------------------------------------------------

class FireflySpecies(Species):
    """Visual fireflies that communicate via light flash patterns.

    Flash signals propagate only along unobstructed line-of-sight.
    """

    name: str = "firefly"

    def __init__(self) -> None:
        self._states: dict[str, FireflyState] = {}

    # -- helpers -----------------------------------------------------------

    def _get_state(self, entity: Entity) -> FireflyState:
        if entity.id not in self._states:
            self._states[entity.id] = FireflyState()
        return self._states[entity.id]

    @staticmethod
    def _direction_toward(
        x: int, y: int, tx: int, ty: int, grid_w: int, grid_h: int,
    ) -> Action:
        """Return a move action toward *(tx, ty)* using shortest toroidal path."""
        dx = (tx - x + grid_w // 2) % grid_w - grid_w // 2
        dy = (ty - y + grid_h // 2) % grid_h - grid_h // 2
        if abs(dx) >= abs(dy):
            return Action.MOVE_E if dx > 0 else Action.MOVE_W
        return Action.MOVE_S if dy > 0 else Action.MOVE_N

    @staticmethod
    def _direction_away(
        x: int, y: int, tx: int, ty: int, grid_w: int, grid_h: int,
    ) -> Action:
        """Return a move action away from *(tx, ty)*."""
        dx = (tx - x + grid_w // 2) % grid_w - grid_w // 2
        dy = (ty - y + grid_h // 2) % grid_h - grid_h // 2
        if abs(dx) >= abs(dy):
            return Action.MOVE_W if dx > 0 else Action.MOVE_E
        return Action.MOVE_N if dy > 0 else Action.MOVE_S

    @staticmethod
    def _random_walk() -> Action:
        return random.choice(
            [Action.MOVE_N, Action.MOVE_S, Action.MOVE_E, Action.MOVE_W]
        )

    # -- Species interface -------------------------------------------------

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        """Place *count* fireflies on passable cells."""
        entities: list[Entity] = []
        attempts = 0
        while len(entities) < count and attempts < count * 20:
            attempts += 1
            x = random.randint(0, grid.width - 1)
            y = random.randint(0, grid.height - 1)
            if grid.is_passable(x, y):
                e = Entity(x=x, y=y, energy=config.STARTING_ENERGY,
                           species_name=self.name)
                entities.append(e)
                self._states[e.id] = FireflyState()
        return entities

    def tick(self, entity: Entity, world_state: WorldState) -> Action:
        """Decide the action for *entity* this tick."""
        state = self._get_state(entity)
        grid = world_state.grid
        gw, gh = grid.width, grid.height

        # Decay cooldown
        if state.flash_cooldown > 0:
            state.flash_cooldown -= 1
        # Reset flash each tick (signals are instantaneous)
        state.flash_state = FlashSignal.NONE

        nearby = world_state.nearby_entities(entity.position, _SIGHT_RADIUS)

        # 1. Check for wolves — danger response
        wolves = [
            e for e in nearby
            if e.species_name in _DANGER_SPECIES
            and grid.line_of_sight(entity.x, entity.y, e.x, e.y)
        ]
        if wolves:
            if state.flash_cooldown == 0:
                state.flash_state = FlashSignal.RAPID_FLASH
                state.flash_cooldown = _FLASH_COOLDOWN_TICKS
            w = wolves[0]
            return self._direction_away(entity.x, entity.y, w.x, w.y, gw, gh)

        # 2. Check for food at current cell — eat and signal
        if grid.has_food(entity.x, entity.y):
            if state.flash_cooldown == 0:
                state.flash_state = FlashSignal.DOUBLE_FLASH
                state.flash_cooldown = _FLASH_COOLDOWN_TICKS
            return Action.EAT

        # 3. Check for food nearby — move toward it
        food_positions = world_state.nearby_food(entity.position, _SIGHT_RADIUS)
        visible_food = [
            fp for fp in food_positions
            if grid.line_of_sight(entity.x, entity.y, fp[0], fp[1])
        ]
        if visible_food:
            closest = min(
                visible_food,
                key=lambda fp: abs(fp[0] - entity.x) + abs(fp[1] - entity.y),
            )
            return self._direction_toward(
                entity.x, entity.y, closest[0], closest[1], gw, gh,
            )

        # 4. React to flash signals from visible fireflies
        visible_fireflies = [
            e for e in nearby
            if e.species_name == self.name
            and grid.line_of_sight(entity.x, entity.y, e.x, e.y)
        ]

        for ff in visible_fireflies:
            ff_state = self._states.get(ff.id)
            if ff_state is None:
                continue
            if ff_state.flash_state == FlashSignal.DOUBLE_FLASH:
                return self._direction_toward(
                    entity.x, entity.y, ff.x, ff.y, gw, gh,
                )
            if ff_state.flash_state == FlashSignal.RAPID_FLASH:
                return self._direction_away(
                    entity.x, entity.y, ff.x, ff.y, gw, gh,
                )

        # 5. Reproduction check
        if entity.energy >= config.REPRODUCE_THRESHOLD:
            return Action.REPRODUCE

        # 6. Random walk
        return self._random_walk()

    def render(self, entity: Entity) -> str:
        """Return display character for a firefly."""
        return "f"
