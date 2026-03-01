"""Toroidal grid with terrain and food."""
from __future__ import annotations

import random
from .config import SimConfig

OPEN = 0
OBSTACLE = 1
WATER = 2


class Grid:
    def __init__(self, config: SimConfig | None = None):
        self.config = config or SimConfig()
        self.width = self.config.GRID_WIDTH
        self.height = self.config.GRID_HEIGHT
        self.terrain: list[list[int]] = []
        self._food: set[tuple[int, int]] = set()
        self._generate_terrain()

    def _generate_terrain(self) -> None:
        for y in range(self.height):
            row = []
            for x in range(self.width):
                r = random.random()
                if r < self.config.OBSTACLE_DENSITY:
                    row.append(OBSTACLE)
                elif r < self.config.OBSTACLE_DENSITY + self.config.WATER_DENSITY:
                    row.append(WATER)
                else:
                    row.append(OPEN)
            self.terrain.append(row)

    def wrap(self, x: int, y: int) -> tuple[int, int]:
        return x % self.width, y % self.height

    def get_terrain(self, x: int, y: int) -> int:
        wx, wy = self.wrap(x, y)
        return self.terrain[wy][wx]

    def is_passable(self, x: int, y: int) -> bool:
        return self.get_terrain(x, y) != OBSTACLE

    def get_neighbors(self, x: int, y: int, radius: int = 1) -> list[tuple[int, int]]:
        result = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = self.wrap(x + dx, y + dy)
                if self.is_passable(nx, ny):
                    result.append((nx, ny))
        return result

    def spawn_food(self) -> bool:
        if len(self._food) >= self.config.MAX_FOOD:
            return False
        attempts = 0
        while attempts < 50:
            x = random.randint(0, self.width - 1)
            y = random.randint(0, self.height - 1)
            if self.terrain[y][x] == OPEN and (x, y) not in self._food:
                self._food.add((x, y))
                return True
            attempts += 1
        return False

    def remove_food(self, x: int, y: int) -> bool:
        pos = self.wrap(x, y)
        if pos in self._food:
            self._food.discard(pos)
            return True
        return False

    def get_food_positions(self) -> set[tuple[int, int]]:
        return set(self._food)

    def has_food(self, x: int, y: int) -> bool:
        return self.wrap(x, y) in self._food
