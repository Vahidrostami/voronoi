"""Base entity and species interface for the ecosystem simulation."""

from abc import ABC, abstractmethod
from collections import namedtuple
from enum import Enum, auto
from typing import Any, TYPE_CHECKING

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
    SIGNAL = auto()
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


# Structured action for richer species behaviors (signal support, explicit dx/dy)
ActionCommand = namedtuple('ActionCommand', [
    'type',         # str: 'move', 'eat', 'reproduce', 'signal', 'idle'
    'dx',           # int: x movement delta
    'dy',           # int: y movement delta
    'signal_type',  # str: signal category (e.g. 'pheromone', 'flash', 'song')
    'signal_data',  # any: signal payload
], defaults=[0, 0, '', None])


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

    @property
    def position(self) -> tuple[int, int]:
        """Position as (x, y) tuple."""
        return (self.x, self.y)

    @position.setter
    def position(self, val: tuple[int, int]) -> None:
        self.x, self.y = val

    @property
    def species_type(self) -> str:
        """Alias for species_name."""
        return self.species_name

    @species_type.setter
    def species_type(self, val: str) -> None:
        self.species_name = val

    @property
    def metadata(self) -> dict:
        """Alias for extra dict (species-specific state)."""
        return self.extra

    @metadata.setter
    def metadata(self, val: dict) -> None:
        self.extra = val

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
    def tick(self, entity: Entity, grid: 'Grid',
             all_entities: list[Entity]) -> Action:
        """Decide what action this entity takes this tick."""
        ...

    @abstractmethod
    def render(self, entity: Entity) -> str:
        """Return a single character for ASCII visualization."""
        ...


if __name__ == '__main__':
    print("=== Entity Tests ===")

    # Test Action enum
    assert Action.MOVE_N in DIRECTION_DELTAS
    assert Action.IDLE not in DIRECTION_DELTAS
    assert Action.SIGNAL not in DIRECTION_DELTAS
    assert DIRECTION_DELTAS[Action.MOVE_N] == (0, -1)
    assert DIRECTION_DELTAS[Action.MOVE_SE] == (1, 1)
    assert len(DIRECTION_DELTAS) == 8
    print("  Action enum: OK")

    # Test ActionCommand namedtuple
    cmd = ActionCommand(type='move', dx=1, dy=0)
    assert cmd.type == 'move'
    assert cmd.dx == 1
    assert cmd.dy == 0
    assert cmd.signal_type == ''
    assert cmd.signal_data is None

    sig = ActionCommand(type='signal', signal_type='pheromone',
                        signal_data={'strength': 1.0})
    assert sig.type == 'signal'
    assert sig.signal_type == 'pheromone'
    assert sig.signal_data == {'strength': 1.0}
    assert sig.dx == 0 and sig.dy == 0
    print("  ActionCommand namedtuple: OK")

    # Test Entity
    e = Entity(10, 20, 'ant', energy=60)
    assert e.x == 10 and e.y == 20
    assert e.position == (10, 20)
    assert e.energy == 60
    assert e.alive is True
    assert e.species_name == 'ant'
    assert e.species_type == 'ant'
    assert e.metadata is e.extra
    assert isinstance(e.entity_id, int)
    assert not e.is_dead()

    # Test position setter
    e.position = (5, 15)
    assert e.x == 5 and e.y == 15 and e.position == (5, 15)

    # Test species_type setter
    e.species_type = 'bird'
    assert e.species_name == 'bird'

    # Test metadata setter
    e.metadata = {'foo': 'bar'}
    assert e.extra == {'foo': 'bar'}

    # Test is_dead
    e.energy = 0
    assert e.is_dead()
    e.energy = 10
    e.alive = False
    assert e.is_dead()

    # Test unique IDs
    e1 = Entity(0, 0, 'ant')
    e2 = Entity(0, 0, 'ant')
    assert e1.entity_id != e2.entity_id
    print("  Entity class: OK")

    # Test Species is abstract
    try:
        Species()  # type: ignore
        assert False, "Should not instantiate abstract class"
    except TypeError:
        pass
    print("  Species ABC: OK")

    print("All entity tests passed!")
