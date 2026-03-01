"""Simulation configuration constants.

All tunable parameters for the ecosystem simulation live here.
Import this module to access grid dimensions, energy values, spawn rates,
and species population counts.
"""

# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------
GRID_WIDTH: int = 100
"""Number of columns in the toroidal grid."""

GRID_HEIGHT: int = 100
"""Number of rows in the toroidal grid."""

OBSTACLE_RATIO: float = 0.10
"""Fraction of cells that are obstacles (~10%)."""

WATER_RATIO: float = 0.05
"""Fraction of cells that are water (~5%)."""

# ---------------------------------------------------------------------------
# Food
# ---------------------------------------------------------------------------
FOOD_SPAWN_RATE: int = 5
"""Number of new food items placed per tick (on open cells)."""

MAX_FOOD: int = 200
"""Hard cap on total food items on the grid at any time."""

ENERGY_PER_FOOD: int = 10
"""Energy an entity gains from eating one food item."""

# ---------------------------------------------------------------------------
# Entity energy
# ---------------------------------------------------------------------------
ENERGY_PER_TICK: int = -1
"""Energy change applied to every living entity each tick (negative = drain)."""

STARTING_ENERGY: int = 50
"""Energy a newly spawned entity begins with."""

# ---------------------------------------------------------------------------
# Reproduction
# ---------------------------------------------------------------------------
REPRODUCE_THRESHOLD: int = 80
"""Minimum energy required before an entity may reproduce."""

REPRODUCE_COST: int = 40
"""Energy deducted from the parent upon successful reproduction."""

# ---------------------------------------------------------------------------
# Species population counts (initial spawn)
# ---------------------------------------------------------------------------
ANT_COUNT: int = 50
"""Initial number of pheromone ants."""

BIRD_COUNT: int = 30
"""Initial number of sonic birds."""

FIREFLY_COUNT: int = 40
"""Initial number of visual fireflies."""

WOLF_COUNT: int = 10
"""Initial number of predator wolves."""

WOLF_HUNGER_LIMIT: int = 50
"""Ticks a wolf can survive without eating before dying."""
