"""100x100 toroidal grid with terrain, food, and spatial queries."""

import random
from enum import IntEnum
from src.world import config


class Terrain(IntEnum):
    OPEN = 0
    OBSTACLE = 1
    WATER = 2


class Grid:
    """Toroidal grid world with terrain and food."""

    def __init__(self, width: int = config.GRID_WIDTH,
                 height: int = config.GRID_HEIGHT, seed: int | None = None):
        self.width = width
        self.height = height
        self.rng = random.Random(seed)

        # Initialize terrain
        self.terrain: list[list[Terrain]] = [
            [Terrain.OPEN for _ in range(width)] for _ in range(height)
        ]
        self._place_terrain()

        # Food positions: set of (x, y)
        self.food: set[tuple[int, int]] = set()

        # Movement trails for wolf scent tracking: (x,y) -> list of (species, tick)
        self.trails: dict[tuple[int, int], list[tuple[str, int]]] = {}
        self.current_tick = 0

    def _place_terrain(self) -> None:
        """Randomly place obstacles and water."""
        total = self.width * self.height
        obstacle_count = int(total * config.OBSTACLE_RATIO)
        water_count = int(total * config.WATER_RATIO)

        all_cells = [(x, y) for y in range(self.height) for x in range(self.width)]
        self.rng.shuffle(all_cells)

        for i in range(obstacle_count):
            x, y = all_cells[i]
            self.terrain[y][x] = Terrain.OBSTACLE

        for i in range(obstacle_count, obstacle_count + water_count):
            x, y = all_cells[i]
            self.terrain[y][x] = Terrain.WATER

    def is_passable(self, x: int, y: int) -> bool:
        """Check if a cell can be walked on (not obstacle or water)."""
        return self.terrain[y % self.height][x % self.width] == Terrain.OPEN

    def wrap(self, x: int, y: int) -> tuple[int, int]:
        """Wrap coordinates toroidally."""
        return x % self.width, y % self.height

    def spawn_food(self, count: int = config.FOOD_SPAWN_RATE) -> None:
        """Spawn food on random open cells up to MAX_FOOD."""
        if len(self.food) >= config.MAX_FOOD:
            return
        budget = min(count, config.MAX_FOOD - len(self.food))
        attempts = 0
        placed = 0
        while placed < budget and attempts < budget * 10:
            x = self.rng.randint(0, self.width - 1)
            y = self.rng.randint(0, self.height - 1)
            if self.is_passable(x, y) and (x, y) not in self.food:
                self.food.add((x, y))
                placed += 1
            attempts += 1

    def has_food(self, x: int, y: int) -> bool:
        return (x, y) in self.food

    def consume_food(self, x: int, y: int) -> bool:
        """Try to eat food at position. Returns True if food was there."""
        if (x, y) in self.food:
            self.food.discard((x, y))
            return True
        return False

    def get_neighbors(self, x: int, y: int, radius: int = 1) -> list[tuple[int, int]]:
        """Get all passable cells within Manhattan-distance radius (toroidal)."""
        result = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = self.wrap(x + dx, y + dy)
                if self.is_passable(nx, ny):
                    result.append((nx, ny))
        return result

    def has_line_of_sight(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """Check line-of-sight between two points (Bresenham). Blocked by obstacles."""
        # Use direct (non-wrapped) distance to pick shortest path
        dx = x2 - x1
        dy = y2 - y1
        # Handle toroidal: pick shortest direction
        if abs(dx) > self.width // 2:
            dx = dx - self.width if dx > 0 else dx + self.width
        if abs(dy) > self.height // 2:
            dy = dy - self.height if dy > 0 else dy + self.height

        steps = max(abs(dx), abs(dy))
        if steps == 0:
            return True

        for i in range(1, steps):
            t = i / steps
            cx = int(round(x1 + dx * t)) % self.width
            cy = int(round(y1 + dy * t)) % self.height
            if self.terrain[cy][cx] == Terrain.OBSTACLE:
                return False
        return True

    def distance(self, x1: int, y1: int, x2: int, y2: int) -> int:
        """Toroidal Chebyshev distance."""
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        dx = min(dx, self.width - dx)
        dy = min(dy, self.height - dy)
        return max(dx, dy)

    def record_trail(self, x: int, y: int, species_name: str) -> None:
        """Record a movement trail for scent tracking."""
        key = (x, y)
        if key not in self.trails:
            self.trails[key] = []
        self.trails[key].append((species_name, self.current_tick))

    def get_scent(self, x: int, y: int, max_age: int = 20) -> list[tuple[str, int]]:
        """Get recent scent trails at a position."""
        key = (x, y)
        if key not in self.trails:
            return []
        cutoff = self.current_tick - max_age
        return [(s, t) for s, t in self.trails[key] if t >= cutoff]

    def cleanup_trails(self, max_age: int = 30) -> None:
        """Remove old trail entries to save memory."""
        cutoff = self.current_tick - max_age
        to_delete = []
        for key, entries in self.trails.items():
            filtered = [(s, t) for s, t in entries if t >= cutoff]
            if filtered:
                self.trails[key] = filtered
            else:
                to_delete.append(key)
        for key in to_delete:
            del self.trails[key]

    def find_nearest_food(self, x: int, y: int, radius: int = 10) -> tuple[int, int] | None:
        """Find closest food within radius."""
        best = None
        best_dist = radius + 1
        for fx, fy in self.food:
            d = self.distance(x, y, fx, fy)
            if d <= radius and d < best_dist:
                best = (fx, fy)
                best_dist = d
        return best
