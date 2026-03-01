"""Simulation configuration dataclass."""
from dataclasses import dataclass


@dataclass
class SimConfig:
    GRID_WIDTH: int = 100
    GRID_HEIGHT: int = 100
    FOOD_SPAWN_RATE: int = 5
    MAX_FOOD: int = 200
    ENERGY_PER_FOOD: float = 10
    ENERGY_LOSS_PER_TICK: float = 1
    REPRODUCE_THRESHOLD: float = 80
    REPRODUCE_COST: float = 40
    INITIAL_ANTS: int = 50
    INITIAL_BIRDS: int = 30
    INITIAL_FIREFLIES: int = 40
    INITIAL_WOLVES: int = 10
    OBSTACLE_DENSITY: float = 0.10
    WATER_DENSITY: float = 0.05
    WOLF_STARVATION_TICKS: int = 50
