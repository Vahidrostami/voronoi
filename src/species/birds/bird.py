"""Sonic Birds — a flocking species that communicates via sound signals.

Birds emit sound signals (FOOD_CALL, DANGER_CALL) that propagate within a
limited range and are blocked by obstacles.  They use these signals to
coordinate flocking, feeding, and predator evasion.
"""

from __future__ import annotations

import enum
import random
from dataclasses import dataclass, field
from typing import ClassVar

from world.entity import Action, Entity, Species, WorldState
from world import config
from world.grid import Grid, Terrain

# ---------------------------------------------------------------------------
# Sound signal system
# ---------------------------------------------------------------------------

SIGNAL_RANGE: int = 15
"""Maximum Chebyshev distance a sound signal can travel."""

SIGNAL_MEMORY: int = 10
"""Number of ticks a bird remembers a heard signal."""

WOLF_DETECTION_RADIUS: int = 8
"""How far a bird can detect wolves."""

FOOD_DETECTION_RADIUS: int = 5
"""How far a bird can detect food."""

FLOCK_RADIUS: int = 6
"""Radius for flocking tendency calculations."""


class SignalType(enum.Enum):
    """Types of sound signals birds can emit."""
    FOOD_CALL = "food_call"
    DANGER_CALL = "danger_call"


@dataclass
class SoundSignal:
    """A sound signal emitted by a bird."""
    signal_type: SignalType
    source_x: int
    source_y: int
    emitter_id: str
    tick: int


# ---------------------------------------------------------------------------
# Per-bird state stored outside Entity (keyed by entity id)
# ---------------------------------------------------------------------------

@dataclass
class _BirdMemory:
    """Internal memory for a single bird."""
    signals_heard: list[SoundSignal] = field(default_factory=list)


# ---------------------------------------------------------------------------
# BirdSpecies
# ---------------------------------------------------------------------------

class BirdSpecies(Species):
    """Sonic Birds species implementation.

    Birds communicate using sound signals with limited range (15 cells).
    Signals are blocked by obstacles.  Behaviour priority:

    1. Food nearby → eat and emit FOOD_CALL
    2. Wolf nearby → emit DANGER_CALL and flee
    3. Heard FOOD_CALL → move toward source
    4. Heard DANGER_CALL → move away from source
    5. Otherwise → random movement with slight flocking tendency

    Energy: −1/tick, +10 from food, reproduce when >80 (cost 40).
    """

    name: str = "bird"

    # Shared state across all birds managed by this species instance
    _memories: dict[str, _BirdMemory]
    _pending_signals: list[SoundSignal]
    _current_tick: int
    _rng: random.Random

    def __init__(self, *, seed: int | None = None) -> None:
        self._memories = {}
        self._pending_signals = []
        self._current_tick = 0
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Species interface
    # ------------------------------------------------------------------

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        """Place *count* birds on random passable cells."""
        entities: list[Entity] = []
        attempts = 0
        while len(entities) < count and attempts < count * 20:
            attempts += 1
            x = self._rng.randint(0, grid.width - 1)
            y = self._rng.randint(0, grid.height - 1)
            if grid.is_passable(x, y):
                e = Entity(
                    x=x,
                    y=y,
                    energy=config.STARTING_ENERGY,
                    species_name=self.name,
                )
                entities.append(e)
                self._memories[e.id] = _BirdMemory()
        return entities

    def tick(self, entity: Entity, world_state: WorldState) -> Action:
        """Decide the action for *entity* this tick."""
        self._current_tick += 1
        mem = self._memories.setdefault(entity.id, _BirdMemory())

        # Deliver pending signals to this bird
        self._receive_signals(entity, world_state)

        # Prune old signals from memory
        mem.signals_heard = [
            s for s in mem.signals_heard
            if self._current_tick - s.tick <= SIGNAL_MEMORY
        ]

        # --- Priority 1: food nearby → eat and emit FOOD_CALL ---
        nearby_food = world_state.nearby_food(entity.position, FOOD_DETECTION_RADIUS)
        if nearby_food:
            # If standing on food, eat it
            if world_state.grid.has_food(entity.x, entity.y):
                self._emit_signal(SignalType.FOOD_CALL, entity)
                return Action.EAT

            # Move toward closest food
            fx, fy = self._closest(entity, nearby_food, world_state.grid)
            return self._move_toward(entity, fx, fy, world_state.grid)

        # --- Priority 2: wolf nearby → emit DANGER_CALL and flee ---
        nearby = world_state.nearby_entities(entity.position, WOLF_DETECTION_RADIUS)
        wolves = [e for e in nearby if e.species_name == "wolf"]
        if wolves:
            self._emit_signal(SignalType.DANGER_CALL, entity)
            wx, wy = wolves[0].x, wolves[0].y
            return self._move_away(entity, wx, wy, world_state.grid)

        # --- Priority 3: check for reproduction ---
        if entity.energy >= config.REPRODUCE_THRESHOLD:
            return Action.REPRODUCE

        # --- Priority 4: heard FOOD_CALL → move toward source ---
        food_calls = [
            s for s in mem.signals_heard if s.signal_type == SignalType.FOOD_CALL
        ]
        if food_calls:
            latest = food_calls[-1]
            return self._move_toward(
                entity, latest.source_x, latest.source_y, world_state.grid
            )

        # --- Priority 5: heard DANGER_CALL → move away ---
        danger_calls = [
            s for s in mem.signals_heard if s.signal_type == SignalType.DANGER_CALL
        ]
        if danger_calls:
            latest = danger_calls[-1]
            return self._move_away(
                entity, latest.source_x, latest.source_y, world_state.grid
            )

        # --- Priority 6: random movement with flocking tendency ---
        return self._flock_move(entity, world_state)

    def render(self, entity: Entity) -> str:
        """Return display character for a bird."""
        return "b"

    # ------------------------------------------------------------------
    # Signal helpers
    # ------------------------------------------------------------------

    def _emit_signal(self, sig_type: SignalType, entity: Entity) -> None:
        """Queue a signal to be delivered to nearby birds next tick."""
        self._pending_signals.append(
            SoundSignal(
                signal_type=sig_type,
                source_x=entity.x,
                source_y=entity.y,
                emitter_id=entity.id,
                tick=self._current_tick,
            )
        )

    def _receive_signals(self, entity: Entity, world_state: WorldState) -> None:
        """Deliver pending signals within range and line-of-sight."""
        mem = self._memories.setdefault(entity.id, _BirdMemory())
        grid = world_state.grid
        still_pending: list[SoundSignal] = []

        for sig in self._pending_signals:
            if sig.emitter_id == entity.id:
                continue
            dx = min(
                abs(sig.source_x - entity.x),
                grid.width - abs(sig.source_x - entity.x),
            )
            dy = min(
                abs(sig.source_y - entity.y),
                grid.height - abs(sig.source_y - entity.y),
            )
            dist = max(dx, dy)
            if dist <= SIGNAL_RANGE and grid.line_of_sight(
                entity.x, entity.y, sig.source_x, sig.source_y
            ):
                mem.signals_heard.append(sig)

        # Signals persist for all birds in this tick cycle; cleared externally
        # by the caller between ticks (or naturally expire via SIGNAL_MEMORY).

    def clear_pending_signals(self) -> None:
        """Clear pending signals — call between simulation ticks."""
        self._pending_signals.clear()

    def register_entity(self, entity: Entity) -> None:
        """Register a new entity (e.g. after reproduction)."""
        if entity.id not in self._memories:
            self._memories[entity.id] = _BirdMemory()

    # ------------------------------------------------------------------
    # Movement helpers
    # ------------------------------------------------------------------

    def _move_toward(
        self, entity: Entity, tx: int, ty: int, grid: Grid
    ) -> Action:
        """Return an action that moves *entity* toward *(tx, ty)*."""
        dx = (tx - entity.x + grid.width // 2) % grid.width - grid.width // 2
        dy = (ty - entity.y + grid.height // 2) % grid.height - grid.height // 2

        # Prefer the axis with greater distance
        if abs(dx) >= abs(dy):
            action = Action.MOVE_E if dx > 0 else Action.MOVE_W
            nx, ny = self._action_dest(entity, action, grid)
            if grid.is_passable(nx, ny):
                return action

        if dy != 0:
            action = Action.MOVE_S if dy > 0 else Action.MOVE_N
            nx, ny = self._action_dest(entity, action, grid)
            if grid.is_passable(nx, ny):
                return action

        # Fallback: try the other axis
        if dx != 0:
            action = Action.MOVE_E if dx > 0 else Action.MOVE_W
            nx, ny = self._action_dest(entity, action, grid)
            if grid.is_passable(nx, ny):
                return action

        return Action.IDLE

    def _move_away(
        self, entity: Entity, tx: int, ty: int, grid: Grid
    ) -> Action:
        """Return an action that moves *entity* away from *(tx, ty)*."""
        dx = (tx - entity.x + grid.width // 2) % grid.width - grid.width // 2
        dy = (ty - entity.y + grid.height // 2) % grid.height - grid.height // 2

        # Move in opposite direction
        if abs(dx) >= abs(dy):
            action = Action.MOVE_W if dx > 0 else Action.MOVE_E
            nx, ny = self._action_dest(entity, action, grid)
            if grid.is_passable(nx, ny):
                return action

        if dy != 0:
            action = Action.MOVE_N if dy > 0 else Action.MOVE_S
            nx, ny = self._action_dest(entity, action, grid)
            if grid.is_passable(nx, ny):
                return action

        if dx != 0:
            action = Action.MOVE_W if dx > 0 else Action.MOVE_E
            nx, ny = self._action_dest(entity, action, grid)
            if grid.is_passable(nx, ny):
                return action

        return Action.IDLE

    def _flock_move(self, entity: Entity, world_state: WorldState) -> Action:
        """Random movement biased toward nearby flock-mates."""
        flock = [
            e
            for e in world_state.nearby_entities(entity.position, FLOCK_RADIUS)
            if e.species_name == self.name
        ]

        if flock:
            # Average position of flock-mates (simple centroid, ignoring wrap)
            avg_x = sum(e.x for e in flock) / len(flock)
            avg_y = sum(e.y for e in flock) / len(flock)
            # 50% chance to move toward flock, 50% random
            if self._rng.random() < 0.5:
                return self._move_toward(
                    entity, int(avg_x), int(avg_y), world_state.grid
                )

        # Random movement
        actions = [Action.MOVE_N, Action.MOVE_S, Action.MOVE_E, Action.MOVE_W]
        self._rng.shuffle(actions)
        for action in actions:
            nx, ny = self._action_dest(entity, action, world_state.grid)
            if world_state.grid.is_passable(nx, ny):
                return action
        return Action.IDLE

    @staticmethod
    def _action_dest(
        entity: Entity, action: Action, grid: Grid
    ) -> tuple[int, int]:
        """Return the destination *(x, y)* if *entity* takes *action*."""
        dx, dy = {
            Action.MOVE_N: (0, -1),
            Action.MOVE_S: (0, 1),
            Action.MOVE_E: (1, 0),
            Action.MOVE_W: (-1, 0),
        }.get(action, (0, 0))
        return grid.wrap(entity.x + dx, entity.y + dy)

    def _closest(
        self,
        entity: Entity,
        positions: list[tuple[int, int]],
        grid: Grid,
    ) -> tuple[int, int]:
        """Return the position from *positions* closest to *entity* (toroidal)."""
        best = positions[0]
        best_dist = float("inf")
        for px, py in positions:
            dx = min(abs(px - entity.x), grid.width - abs(px - entity.x))
            dy = min(abs(py - entity.y), grid.height - abs(py - entity.y))
            d = max(dx, dy)
            if d < best_dist:
                best_dist = d
                best = (px, py)
        return best
