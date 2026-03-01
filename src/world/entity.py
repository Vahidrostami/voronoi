"""Entity base class, Action namedtuple, and Species ABC."""
from __future__ import annotations
from abc import ABC, abstractmethod
from collections import namedtuple
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import World
    from .config import SimConfig
    from .grid import Grid

Action = namedtuple('Action', ['type', 'dx', 'dy', 'data'], defaults=['idle', 0, 0, None])


class Entity:
    _next_id: int = 0

    def __init__(self, species_name: str, x: int, y: int, energy: float = 50.0):
        Entity._next_id += 1
        self.id: int = Entity._next_id
        self.species_name: str = species_name
        self.x: int = x
        self.y: int = y
        self.energy: float = energy
        self.alive: bool = True
        self.direction: int = 0
        self.extra: dict = {}

    def move(self, dx: int, dy: int, grid: Grid) -> None:
        self.x, self.y = grid.wrap(self.x + dx, self.y + dy)

    def eat(self, amount: float) -> None:
        self.energy += amount

    def lose_energy(self, amount: float) -> None:
        self.energy -= amount
        if self.energy <= 0:
            self.alive = False

    def is_alive(self) -> bool:
        return self.alive

    def can_reproduce(self, config: SimConfig) -> bool:
        return self.energy > config.REPRODUCE_THRESHOLD


class Species(ABC):
    @abstractmethod
    def spawn(self, world: World, count: int) -> list[Entity]:
        pass

    @abstractmethod
    def tick(self, entity: Entity, world: World) -> Action:
        pass

    @abstractmethod
    def render(self, entity: Entity) -> str:
        pass
