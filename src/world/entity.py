"""Base entity and species interface for the ecosystem simulation."""

from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.world.grid import Grid


class Action(Enum):
    """Actions an entity can take on a tick."""
    MOVE_N = auto()
    MOVE_S = auto()
    MOVE_E = auto()
    MOVE_W = auto()
    MOVE_NE = auto()
    MOVE_NW = auto()
    MOVE_SE = auto()
    MOVE_SW = auto()
    EAT = auto()
    REPRODUCE = auto()
    IDLE = auto()


# Direction deltas for movement actions
DIRECTION_DELTAS: dict[Action, tuple[int, int]] = {
    Action.MOVE_N: (0, -1),
    Action.MOVE_S: (0, 1),
    Action.MOVE_E: (1, 0),
    Action.MOVE_W: (-1, 0),
    Action.MOVE_NE: (1, -1),
    Action.MOVE_NW: (-1, -1),
    Action.MOVE_SE: (1, 1),
    Action.MOVE_SW: (-1, 1),
}


class Entity:
    """Base creature in the simulation."""

    __slots__ = ('x', 'y', 'energy', 'alive', 'species_name', 'age',
                 'entity_id', 'extra')

    _next_id = 0

    def __init__(self, x: int, y: int, species_name: str, energy: int = 50):
        self.x = x
        self.y = y
        self.energy = energy
        self.alive = True
        self.species_name = species_name
        self.age = 0
        self.entity_id = Entity._next_id
        Entity._next_id += 1
        self.extra: dict = {}  # species-specific state

    def move(self, dx: int, dy: int, grid: 'Grid') -> None:
        """Move by delta, wrapping toroidally. Only moves to passable cells."""
        nx = (self.x + dx) % grid.width
        ny = (self.y + dy) % grid.height
        if grid.is_passable(nx, ny):
            self.x = nx
            self.y = ny

    def is_dead(self) -> bool:
        return not self.alive or self.energy <= 0


class Species(ABC):
    """Interface that every species module must implement."""

    @abstractmethod
    def spawn(self, grid: 'Grid', count: int) -> list[Entity]:
        """Create initial entities placed on the grid."""
        ...

    @abstractmethod
    def tick(self, entity: Entity, grid: 'Grid', all_entities: list[Entity]) -> Action:
        """Decide what action this entity takes this tick."""
        ...

    @abstractmethod
    def render(self, entity: Entity) -> str:
        """Return a single character for ASCII visualization."""
        ...
