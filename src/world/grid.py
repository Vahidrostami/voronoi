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

        # Entity position tracking: (x, y) -> list of entities
        self.entity_positions: dict[tuple[int, int], list] = {}

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

    # --- Cell access ---

    def get_cell(self, x: int, y: int) -> Terrain:
        """Get terrain type at (x, y) with toroidal wrapping."""
        wx, wy = self.wrap(x, y)
        return self.terrain[wy][wx]

    def set_cell(self, x: int, y: int, val: Terrain) -> None:
        """Set terrain type at (x, y) with toroidal wrapping."""
        wx, wy = self.wrap(x, y)
        self.terrain[wy][wx] = val

    def is_passable(self, x: int, y: int) -> bool:
        """Check if a cell can be walked on (not obstacle or water)."""
        return self.terrain[y % self.height][x % self.width] == Terrain.OPEN

    def wrap(self, x: int, y: int) -> tuple[int, int]:
        """Wrap coordinates toroidally."""
        return x % self.width, y % self.height

    def distance(self, x1: int, y1: int, x2: int, y2: int) -> int:
        """Toroidal Chebyshev distance."""
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        dx = min(dx, self.width - dx)
        dy = min(dy, self.height - dy)
        return max(dx, dy)

    # --- Food ---

    def add_food(self, x: int, y: int) -> None:
        """Add food at position (if cell is passable)."""
        wx, wy = self.wrap(x, y)
        if self.is_passable(wx, wy):
            self.food.add((wx, wy))

    def remove_food(self, x: int, y: int) -> None:
        """Remove food at position."""
        self.food.discard(self.wrap(x, y))

    def has_food(self, x: int, y: int) -> bool:
        return (x, y) in self.food

    def consume_food(self, x: int, y: int) -> bool:
        """Try to eat food at position. Returns True if food was there."""
        if (x, y) in self.food:
            self.food.discard((x, y))
            return True
        return False

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

    def find_nearest_food(self, x: int, y: int,
                          radius: int = 10) -> tuple[int, int] | None:
        """Find closest food within radius."""
        best = None
        best_dist = radius + 1
        for fx, fy in self.food:
            d = self.distance(x, y, fx, fy)
            if d <= radius and d < best_dist:
                best = (fx, fy)
                best_dist = d
        return best

    # --- Neighbors ---

    def get_neighbors(self, x: int, y: int,
                      radius: int = 1) -> list[tuple[int, int]]:
        """Get all passable cells within Chebyshev-distance radius (toroidal)."""
        result = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = self.wrap(x + dx, y + dy)
                if self.is_passable(nx, ny):
                    result.append((nx, ny))
        return result

    # --- Entity position tracking ---

    def place_entity(self, entity: object, x: int, y: int) -> None:
        """Register an entity at a position."""
        key = self.wrap(x, y)
        if key not in self.entity_positions:
            self.entity_positions[key] = []
        self.entity_positions[key].append(entity)

    def remove_entity(self, entity: object, x: int, y: int) -> None:
        """Remove an entity from a position."""
        key = self.wrap(x, y)
        if key in self.entity_positions:
            try:
                self.entity_positions[key].remove(entity)
            except ValueError:
                pass
            if not self.entity_positions[key]:
                del self.entity_positions[key]

    def get_entities_at(self, x: int, y: int) -> list:
        """Get entities at a position."""
        return list(self.entity_positions.get(self.wrap(x, y), []))

    # --- Line of sight ---

    def has_line_of_sight(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """Check line-of-sight between two points (Bresenham). Blocked by obstacles."""
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

    # --- Scent trails ---

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


if __name__ == '__main__':
    print("=== Grid Tests ===")

    # Test basic construction
    g = Grid(seed=42)
    assert g.width == 100 and g.height == 100
    print("  Construction: OK")

    # Test terrain ratios
    obs = sum(1 for row in g.terrain for c in row if c == Terrain.OBSTACLE)
    wat = sum(1 for row in g.terrain for c in row if c == Terrain.WATER)
    total = g.width * g.height
    assert abs(obs / total - 0.15) < 0.01, f"Obstacles: {obs/total:.2%}"
    assert abs(wat / total - 0.05) < 0.01, f"Water: {wat/total:.2%}"
    print(f"  Terrain ratios: obs={obs/total:.2%} wat={wat/total:.2%} OK")

    # Test wrap
    assert g.wrap(0, 0) == (0, 0)
    assert g.wrap(100, 100) == (0, 0)
    assert g.wrap(-1, -1) == (99, 99)
    assert g.wrap(105, -3) == (5, 97)
    print("  wrap(): OK")

    # Test get_cell / set_cell
    g2 = Grid(width=10, height=10, seed=0)
    g2.terrain = [[Terrain.OPEN]*10 for _ in range(10)]
    assert g2.get_cell(3, 4) == Terrain.OPEN
    g2.set_cell(3, 4, Terrain.OBSTACLE)
    assert g2.get_cell(3, 4) == Terrain.OBSTACLE
    g2.set_cell(3, 4, Terrain.OPEN)
    # Wrapping in get/set
    g2.set_cell(13, 14, Terrain.WATER)
    assert g2.get_cell(3, 4) == Terrain.WATER
    g2.set_cell(3, 4, Terrain.OPEN)
    print("  get_cell/set_cell: OK")

    # Test distance (toroidal Chebyshev)
    assert g.distance(0, 0, 5, 5) == 5
    assert g.distance(0, 0, 99, 99) == 1  # wraps around
    assert g.distance(0, 0, 50, 50) == 50
    assert g.distance(1, 1, 98, 1) == 3  # wraps in x
    print("  distance(): OK")

    # Test food operations
    g3 = Grid(width=10, height=10, seed=1)
    g3.terrain = [[Terrain.OPEN]*10 for _ in range(10)]
    g3.add_food(3, 3)
    assert g3.has_food(3, 3)
    assert (3, 3) in g3.food
    g3.remove_food(3, 3)
    assert not g3.has_food(3, 3)

    g3.add_food(5, 5)
    assert g3.consume_food(5, 5) is True
    assert g3.consume_food(5, 5) is False
    print("  Food add/remove/consume: OK")

    # Test spawn_food respects MAX_FOOD
    g3.food.clear()
    for _ in range(50):
        g3.spawn_food(count=10)
    assert len(g3.food) <= config.MAX_FOOD
    print(f"  spawn_food (cap at {config.MAX_FOOD}): {len(g3.food)} items OK")

    # Test find_nearest_food
    g3.food.clear()
    g3.add_food(2, 2)
    g3.add_food(7, 7)
    nearest = g3.find_nearest_food(3, 3, radius=5)
    assert nearest == (2, 2)
    print("  find_nearest_food: OK")

    # Test get_neighbors
    g4 = Grid(width=10, height=10, seed=2)
    g4.terrain = [[Terrain.OPEN]*10 for _ in range(10)]
    nbrs = g4.get_neighbors(0, 0, radius=1)
    # 8 neighbors for radius=1, all open, none is (0,0) itself
    assert len(nbrs) == 8
    assert (0, 0) not in nbrs
    # Corner wrapping: neighbor at (-1,-1) wraps to (9,9)
    assert (9, 9) in nbrs
    print("  get_neighbors: OK")

    # Test has_line_of_sight
    g5 = Grid(width=20, height=20, seed=3)
    g5.terrain = [[Terrain.OPEN]*20 for _ in range(20)]
    assert g5.has_line_of_sight(0, 0, 10, 10)
    g5.terrain[5][5] = Terrain.OBSTACLE
    assert not g5.has_line_of_sight(0, 0, 10, 10)
    # Same point
    assert g5.has_line_of_sight(5, 5, 5, 5)
    print("  has_line_of_sight: OK")

    # Test entity_positions tracking
    g6 = Grid(width=10, height=10, seed=4)
    g6.terrain = [[Terrain.OPEN]*10 for _ in range(10)]
    sentinel = object()
    g6.place_entity(sentinel, 3, 4)
    assert sentinel in g6.get_entities_at(3, 4)
    g6.remove_entity(sentinel, 3, 4)
    assert sentinel not in g6.get_entities_at(3, 4)
    # Remove non-existent is safe
    g6.remove_entity(sentinel, 3, 4)
    print("  entity_positions tracking: OK")

    # Test scent trails
    g7 = Grid(width=10, height=10, seed=5)
    g7.current_tick = 100
    g7.record_trail(1, 1, 'ant')
    g7.current_tick = 105
    g7.record_trail(1, 1, 'wolf')
    scent = g7.get_scent(1, 1, max_age=10)
    assert len(scent) == 2
    g7.current_tick = 200
    scent = g7.get_scent(1, 1, max_age=10)
    assert len(scent) == 0
    g7.cleanup_trails(max_age=10)
    assert (1, 1) not in g7.trails
    print("  Scent trails: OK")

    print("All grid tests passed!")
