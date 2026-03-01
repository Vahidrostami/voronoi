"""Toroidal grid for the ecosystem simulation.

The grid wraps at all edges (toroidal topology) so entities moving off one
side reappear on the opposite side.  Each cell stores a :class:`Terrain`
value.  A separate overlay tracks food positions.
"""

from __future__ import annotations

import enum
import random
from typing import Iterator

from . import config


# ---------------------------------------------------------------------------
# Terrain enum
# ---------------------------------------------------------------------------

class Terrain(enum.Enum):
    """Terrain types that can occupy a grid cell."""

    OPEN = "open"
    """Passable open ground."""

    OBSTACLE = "obstacle"
    """Impassable obstacle (blocks movement and line-of-sight)."""

    WATER = "water"
    """Water — passable for some species; counts as open for food placement."""


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

class Grid:
    """A 2-D toroidal grid with terrain and food overlays.

    Parameters
    ----------
    width : int, optional
        Number of columns (default from ``config.GRID_WIDTH``).
    height : int, optional
        Number of rows (default from ``config.GRID_HEIGHT``).
    seed : int | None, optional
        Random seed for reproducible terrain generation.

    Examples
    --------
    >>> g = Grid(10, 10, seed=42)
    >>> g.get_cell(0, 0) in Terrain
    True
    >>> g.is_passable(0, 0) or g.get_cell(0, 0) == Terrain.OBSTACLE
    True
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        width: int = config.GRID_WIDTH,
        height: int = config.GRID_HEIGHT,
        *,
        seed: int | None = None,
    ) -> None:
        self.width = width
        self.height = height

        # flat list — index = y * width + x
        self._cells: list[Terrain] = [Terrain.OPEN] * (width * height)

        # food overlay — set of (x, y)
        self._food: set[tuple[int, int]] = set()

        self._generate_terrain(seed)

    # ------------------------------------------------------------------
    # Terrain generation
    # ------------------------------------------------------------------

    def _generate_terrain(self, seed: int | None) -> None:
        """Randomly assign obstacle / water cells."""
        rng = random.Random(seed)
        total = self.width * self.height
        num_obstacles = int(total * config.OBSTACLE_RATIO)
        num_water = int(total * config.WATER_RATIO)

        indices = list(range(total))
        rng.shuffle(indices)

        for i in indices[:num_obstacles]:
            self._cells[i] = Terrain.OBSTACLE
        for i in indices[num_obstacles : num_obstacles + num_water]:
            self._cells[i] = Terrain.WATER

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def wrap(self, x: int, y: int) -> tuple[int, int]:
        """Return *(x, y)* wrapped to valid grid coordinates (toroidal)."""
        return x % self.width, y % self.height

    def _index(self, x: int, y: int) -> int:
        """Flat index for wrapped coordinates."""
        wx, wy = self.wrap(x, y)
        return wy * self.width + wx

    # ------------------------------------------------------------------
    # Cell access
    # ------------------------------------------------------------------

    def get_cell(self, x: int, y: int) -> Terrain:
        """Return the :class:`Terrain` at *(x, y)* (wrapping)."""
        return self._cells[self._index(x, y)]

    def set_cell(self, x: int, y: int, val: Terrain) -> None:
        """Set the :class:`Terrain` at *(x, y)* (wrapping)."""
        self._cells[self._index(x, y)] = val

    def is_passable(self, x: int, y: int) -> bool:
        """Return ``True`` if the cell is *not* an obstacle."""
        return self.get_cell(x, y) != Terrain.OBSTACLE

    # ------------------------------------------------------------------
    # Neighbourhood queries
    # ------------------------------------------------------------------

    def get_neighbors(
        self, x: int, y: int, radius: int = 1
    ) -> list[tuple[int, int]]:
        """Return wrapped coordinates of all cells within *radius* (Chebyshev).

        The centre cell *(x, y)* is **excluded** from the result.
        """
        result: list[tuple[int, int]] = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                result.append(self.wrap(x + dx, y + dy))
        return result

    # ------------------------------------------------------------------
    # Line-of-sight (Bresenham)
    # ------------------------------------------------------------------

    def line_of_sight(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """Return ``True`` if no obstacle blocks the path from *(x1,y1)* to *(x2,y2)*.

        Uses Bresenham's line algorithm on **wrapped** coordinates.
        Obstacles at the start or end are ignored (only intermediate cells
        count as blocking).
        """
        # Unwrap — choose shortest toroidal path
        dx = (x2 - x1 + self.width // 2) % self.width - self.width // 2
        dy = (y2 - y1 + self.height // 2) % self.height - self.height // 2

        steps = max(abs(dx), abs(dy))
        if steps == 0:
            return True

        for i in range(1, steps):
            # Linearly interpolate
            ix = x1 + round(dx * i / steps)
            iy = y1 + round(dy * i / steps)
            if self.get_cell(ix, iy) == Terrain.OBSTACLE:
                return False
        return True

    # ------------------------------------------------------------------
    # Food overlay
    # ------------------------------------------------------------------

    def place_food(self, x: int, y: int) -> bool:
        """Place food at *(x, y)*.  Returns ``True`` if actually placed.

        Food is only placed on passable cells and respects :data:`config.MAX_FOOD`.
        """
        wx, wy = self.wrap(x, y)
        if not self.is_passable(wx, wy):
            return False
        if len(self._food) >= config.MAX_FOOD:
            return False
        self._food.add((wx, wy))
        return True

    def remove_food(self, x: int, y: int) -> bool:
        """Remove food at *(x, y)*.  Returns ``True`` if food was present."""
        pos = self.wrap(x, y)
        if pos in self._food:
            self._food.discard(pos)
            return True
        return False

    def has_food(self, x: int, y: int) -> bool:
        """Return ``True`` if food is present at *(x, y)*."""
        return self.wrap(x, y) in self._food

    def get_food_positions(self) -> frozenset[tuple[int, int]]:
        """Return an immutable snapshot of all food positions."""
        return frozenset(self._food)

    @property
    def food_count(self) -> int:
        """Current number of food items on the grid."""
        return len(self._food)

    # ------------------------------------------------------------------
    # Iteration helpers
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator[tuple[int, int, Terrain]]:
        """Yield *(x, y, terrain)* for every cell."""
        for idx, t in enumerate(self._cells):
            yield idx % self.width, idx // self.width, t

    def __repr__(self) -> str:  # pragma: no cover
        return f"Grid(width={self.width}, height={self.height})"
