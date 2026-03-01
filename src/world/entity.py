"""Entity model, Species interface, and world-state view.

This module defines the core abstractions that *every* species implementation
must work with:

* :class:`Action` — discrete actions an entity can take each tick.
* :class:`Entity` — a single living creature on the grid.
* :class:`WorldState` — read-only view of the world passed to species logic.
* :class:`Species` — abstract base class that species agents implement.
"""

from __future__ import annotations

import enum
import itertools
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:
    from .grid import Grid, Terrain


# ---------------------------------------------------------------------------
# Action enum
# ---------------------------------------------------------------------------

class Action(enum.Enum):
    """Discrete actions an entity may return from its ``tick``."""

    MOVE_N = "move_n"
    """Move one cell north (y − 1)."""

    MOVE_S = "move_s"
    """Move one cell south (y + 1)."""

    MOVE_E = "move_e"
    """Move one cell east (x + 1)."""

    MOVE_W = "move_w"
    """Move one cell west (x − 1)."""

    EAT = "eat"
    """Attempt to eat food at the current cell."""

    REPRODUCE = "reproduce"
    """Attempt to reproduce (requires energy ≥ REPRODUCE_THRESHOLD)."""

    IDLE = "idle"
    """Do nothing this tick."""


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    """A single creature living on the grid.

    Attributes
    ----------
    x : int
        Horizontal position on the grid.
    y : int
        Vertical position on the grid.
    energy : int
        Current energy.  The entity dies when energy reaches 0.
    alive : bool
        ``False`` once the entity has died or been removed.
    species_name : str
        Human-readable species identifier (e.g. ``"ant"``, ``"wolf"``).
    id : str
        Globally unique identifier for this entity.
    """

    x: int
    y: int
    energy: int = config.STARTING_ENERGY
    alive: bool = True
    species_name: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # Convenience -------------------------------------------------------

    @property
    def position(self) -> tuple[int, int]:
        """Return ``(x, y)`` as a tuple."""
        return self.x, self.y

    def is_alive(self) -> bool:
        """Return ``True`` if the entity is still alive."""
        return self.alive and self.energy > 0

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"Entity(id={self.id!r}, species={self.species_name!r}, "
            f"pos=({self.x},{self.y}), energy={self.energy}, alive={self.alive})"
        )


# ---------------------------------------------------------------------------
# WorldState — read-only view passed to species logic
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorldState:
    """Immutable snapshot of the world visible to a species' ``tick`` method.

    Species implementations receive a ``WorldState`` each tick so they can
    make decisions *without* holding a direct reference to the mutable
    :class:`Grid` or entity list.

    Parameters
    ----------
    grid : Grid
        Reference to the simulation grid (for terrain/food queries).
    entities : list[Entity]
        Flat list of **all** living entities (across every species).
    """

    grid: Grid
    entities: list[Entity]

    # -- Query helpers --------------------------------------------------

    def nearby_entities(
        self,
        pos: tuple[int, int],
        radius: int = 5,
    ) -> list[Entity]:
        """Return living entities within Chebyshev distance *radius* of *pos*.

        Parameters
        ----------
        pos : tuple[int, int]
            ``(x, y)`` centre of the search area.
        radius : int
            Maximum Chebyshev (chessboard) distance.

        Returns
        -------
        list[Entity]
            Entities within range, **excluding** any entity at *pos* itself.
        """
        cx, cy = pos
        w, h = self.grid.width, self.grid.height
        results: list[Entity] = []
        for e in self.entities:
            if not e.is_alive():
                continue
            if (e.x, e.y) == (cx, cy):
                continue
            # Toroidal distance
            dx = min(abs(e.x - cx), w - abs(e.x - cx))
            dy = min(abs(e.y - cy), h - abs(e.y - cy))
            if max(dx, dy) <= radius:
                results.append(e)
        return results

    def nearby_food(
        self,
        pos: tuple[int, int],
        radius: int = 5,
    ) -> list[tuple[int, int]]:
        """Return food positions within Chebyshev distance *radius* of *pos*.

        Parameters
        ----------
        pos : tuple[int, int]
            ``(x, y)`` centre of the search area.
        radius : int
            Maximum Chebyshev (chessboard) distance.

        Returns
        -------
        list[tuple[int, int]]
            Coordinates of food items within range.
        """
        cx, cy = pos
        w, h = self.grid.width, self.grid.height
        results: list[tuple[int, int]] = []
        for fx, fy in self.grid.get_food_positions():
            dx = min(abs(fx - cx), w - abs(fx - cx))
            dy = min(abs(fy - cy), h - abs(fy - cy))
            if max(dx, dy) <= radius:
                results.append((fx, fy))
        return results

    def terrain_at(self, pos: tuple[int, int]) -> Terrain:
        """Return the terrain type at *pos*.

        Parameters
        ----------
        pos : tuple[int, int]
            ``(x, y)`` coordinate.
        """
        return self.grid.get_cell(*pos)


# ---------------------------------------------------------------------------
# Species — abstract base class
# ---------------------------------------------------------------------------

class Species(ABC):
    """Abstract base class for a species in the ecosystem.

    To create a new species (e.g. ``Ant``), subclass :class:`Species` and
    implement the three required methods:

    .. code-block:: python

        class AntSpecies(Species):
            name = "ant"

            def spawn(self, grid: Grid, count: int) -> list[Entity]:
                # Place *count* ants on passable cells and return them.
                ...

            def tick(self, entity: Entity, world_state: WorldState) -> Action:
                # Decide what *entity* should do this tick.
                ...

            def render(self, entity: Entity) -> str:
                # Return a single character for terminal display.
                return "🐜"

    Notes
    -----
    * ``spawn`` is called **once** during initialisation.
    * ``tick`` is called **every simulation tick** for each living entity of
      this species.
    * ``render`` is called by the visualiser; return a single character or
      emoji.
    """

    name: str = ""
    """Short identifier for this species (set in subclass)."""

    @abstractmethod
    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        """Create *count* entities at valid positions on *grid*.

        Parameters
        ----------
        grid : Grid
            The simulation grid — use to find passable spawn locations.
        count : int
            Number of entities to create.

        Returns
        -------
        list[Entity]
            The newly created entities (already positioned on the grid).
        """

    @abstractmethod
    def tick(self, entity: Entity, world_state: WorldState) -> Action:
        """Decide the action for *entity* this tick.

        Parameters
        ----------
        entity : Entity
            The entity making a decision.  Inspect its position, energy, etc.
        world_state : WorldState
            Read-only snapshot of the world.  Use its helper methods
            (``nearby_entities``, ``nearby_food``, ``terrain_at``) to perceive
            the environment.

        Returns
        -------
        Action
            The action the entity wishes to perform.
        """

    @abstractmethod
    def render(self, entity: Entity) -> str:
        """Return a display character/emoji for *entity*.

        Parameters
        ----------
        entity : Entity
            The entity to render.

        Returns
        -------
        str
            A single character or emoji suitable for terminal output.
        """
