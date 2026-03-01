"""Simulation configuration constants."""

# Grid
GRID_WIDTH = 100
GRID_HEIGHT = 100
OBSTACLE_RATIO = 0.15
WATER_RATIO = 0.05

# Food
FOOD_SPAWN_RATE = 5
MAX_FOOD = 200
ENERGY_PER_FOOD = 10
ENERGY_FROM_FOOD = ENERGY_PER_FOOD  # backward-compat alias

# Energy
ENERGY_START = 50
ENERGY_LOSS_PER_TICK = 1
ENERGY_COST_PER_TICK = ENERGY_LOSS_PER_TICK  # backward-compat alias
REPRODUCE_THRESHOLD = 80
REPRODUCE_COST = 40

# Initial species counts (canonical names)
INITIAL_ANTS = 50
INITIAL_BIRDS = 30
INITIAL_FIREFLIES = 40
INITIAL_WOLVES = 10
# backward-compat aliases
ANT_COUNT = INITIAL_ANTS
BIRD_COUNT = INITIAL_BIRDS
FIREFLY_COUNT = INITIAL_FIREFLIES
WOLF_COUNT = INITIAL_WOLVES

# Wolf-specific
WOLF_HUNGER_LIMIT = 50
WOLF_HUNT_ENERGY = 20
WOLF_SCENT_RANGE = 5
WOLF_SPEED = 2

# Ant-specific
ANT_PHEROMONE_DECAY = 0.02

# Communication ranges
BIRD_SIGNAL_RANGE = 15
BIRD_SOUND_RANGE = BIRD_SIGNAL_RANGE  # backward-compat alias
FIREFLY_FLASH_RANGE = 10


if __name__ == '__main__':
    print("=== Config Tests ===")
    # Verify all required constants exist with correct values
    assert GRID_WIDTH == 100
    assert GRID_HEIGHT == 100
    assert FOOD_SPAWN_RATE == 5
    assert MAX_FOOD == 200
    assert ENERGY_PER_FOOD == 10
    assert ENERGY_LOSS_PER_TICK == 1
    assert REPRODUCE_THRESHOLD == 80
    assert REPRODUCE_COST == 40
    assert WOLF_HUNGER_LIMIT == 50
    assert WOLF_HUNT_ENERGY == 20
    assert INITIAL_ANTS == 50
    assert INITIAL_BIRDS == 30
    assert INITIAL_FIREFLIES == 40
    assert INITIAL_WOLVES == 10
    assert ANT_PHEROMONE_DECAY == 0.02
    assert BIRD_SIGNAL_RANGE == 15
    assert FIREFLY_FLASH_RANGE == 10
    assert WOLF_SCENT_RANGE == 5
    assert WOLF_SPEED == 2
    # Backward-compat aliases
    assert ENERGY_FROM_FOOD == ENERGY_PER_FOOD
    assert ENERGY_COST_PER_TICK == ENERGY_LOSS_PER_TICK
    assert ANT_COUNT == INITIAL_ANTS
    assert BIRD_COUNT == INITIAL_BIRDS
    assert BIRD_SOUND_RANGE == BIRD_SIGNAL_RANGE
    assert OBSTACLE_RATIO == 0.15
    assert WATER_RATIO == 0.05
    print("All config tests passed!")
