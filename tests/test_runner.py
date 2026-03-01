"""Tests for the simulation runner and visualisation utilities."""

from __future__ import annotations

import csv
import os
import random
import tempfile

import pytest

from src.world.grid import Grid
from src.world.entity import Action, Entity, WorldState
from src.world import config

# Import the runner functions (not species — those have their own tests)
from src.main import apply_action, spawn_food, parse_args, SPECIES_NAMES
from src.visualize import write_csv_row


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def small_grid() -> Grid:
    """A small 10×10 grid with a fixed seed for deterministic tests."""
    return Grid(10, 10, seed=42)


@pytest.fixture
def rng() -> random.Random:
    return random.Random(123)


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------

class TestParseArgs:
    def test_defaults(self) -> None:
        args = parse_args([])
        assert args.ticks == 500
        assert args.no_display is False
        assert args.seed is None

    def test_custom(self) -> None:
        args = parse_args(["--ticks", "100", "--no-display", "--seed", "7"])
        assert args.ticks == 100
        assert args.no_display is True
        assert args.seed == 7


# ---------------------------------------------------------------------------
# Food spawning
# ---------------------------------------------------------------------------

class TestSpawnFood:
    def test_food_spawned(self, small_grid: Grid, rng: random.Random) -> None:
        """Food count should increase after spawning."""
        assert small_grid.food_count == 0
        spawn_food(small_grid, rng)
        assert small_grid.food_count > 0

    def test_food_respects_max(self, small_grid: Grid, rng: random.Random) -> None:
        """Food count must not exceed MAX_FOOD."""
        for _ in range(500):
            spawn_food(small_grid, rng)
        assert small_grid.food_count <= config.MAX_FOOD

    def test_food_on_passable(self, small_grid: Grid, rng: random.Random) -> None:
        """All food should be on passable cells."""
        for _ in range(50):
            spawn_food(small_grid, rng)
        for x, y in small_grid.get_food_positions():
            assert small_grid.is_passable(x, y)


# ---------------------------------------------------------------------------
# Action application
# ---------------------------------------------------------------------------

class TestApplyAction:
    def _make_entity(self, x: int = 5, y: int = 5, energy: int = 50, species: str = "ant") -> Entity:
        return Entity(x=x, y=y, energy=energy, species_name=species)

    def test_move_north(self, small_grid: Grid, rng: random.Random) -> None:
        e = self._make_entity()
        new_ents: list[Entity] = []
        apply_action(Action.MOVE_N, e, small_grid, None, new_ents, rng)
        assert e.y == 4
        assert e.x == 5

    def test_move_south_wraps(self, small_grid: Grid, rng: random.Random) -> None:
        e = self._make_entity(y=9)
        new_ents: list[Entity] = []
        apply_action(Action.MOVE_S, e, small_grid, None, new_ents, rng)
        assert e.y == 0  # wrapped

    def test_move_east(self, small_grid: Grid, rng: random.Random) -> None:
        e = self._make_entity()
        new_ents: list[Entity] = []
        apply_action(Action.MOVE_E, e, small_grid, None, new_ents, rng)
        assert e.x == 6

    def test_move_west(self, small_grid: Grid, rng: random.Random) -> None:
        e = self._make_entity()
        new_ents: list[Entity] = []
        apply_action(Action.MOVE_W, e, small_grid, None, new_ents, rng)
        assert e.x == 4

    def test_move_blocked_by_obstacle(self, small_grid: Grid, rng: random.Random) -> None:
        """Entity should not move into an obstacle cell."""
        from src.world.grid import Terrain
        # Force the cell north to be an obstacle
        small_grid.set_cell(5, 4, Terrain.OBSTACLE)
        e = self._make_entity()
        new_ents: list[Entity] = []
        apply_action(Action.MOVE_N, e, small_grid, None, new_ents, rng)
        assert e.x == 5 and e.y == 5  # didn't move

    def test_eat_food(self, small_grid: Grid, rng: random.Random) -> None:
        small_grid.place_food(5, 5)
        e = self._make_entity(energy=30)
        new_ents: list[Entity] = []
        apply_action(Action.EAT, e, small_grid, None, new_ents, rng)
        assert e.energy == 30 + config.ENERGY_PER_FOOD
        assert not small_grid.has_food(5, 5)

    def test_eat_no_food(self, small_grid: Grid, rng: random.Random) -> None:
        """Eating when no food present should be a no-op."""
        e = self._make_entity(energy=30)
        new_ents: list[Entity] = []
        apply_action(Action.EAT, e, small_grid, None, new_ents, rng)
        assert e.energy == 30

    def test_reproduce(self, small_grid: Grid, rng: random.Random) -> None:
        e = self._make_entity(energy=config.REPRODUCE_THRESHOLD + 10)
        original_energy = e.energy
        new_ents: list[Entity] = []
        apply_action(Action.REPRODUCE, e, small_grid, None, new_ents, rng)
        assert len(new_ents) == 1
        child = new_ents[0]
        assert child.species_name == "ant"
        assert child.energy == config.STARTING_ENERGY
        assert e.energy == original_energy - config.REPRODUCE_COST

    def test_reproduce_insufficient_energy(self, small_grid: Grid, rng: random.Random) -> None:
        """No reproduction if below threshold."""
        e = self._make_entity(energy=config.REPRODUCE_THRESHOLD - 1)
        new_ents: list[Entity] = []
        apply_action(Action.REPRODUCE, e, small_grid, None, new_ents, rng)
        assert len(new_ents) == 0

    def test_idle_noop(self, small_grid: Grid, rng: random.Random) -> None:
        e = self._make_entity()
        new_ents: list[Entity] = []
        apply_action(Action.IDLE, e, small_grid, None, new_ents, rng)
        assert e.x == 5 and e.y == 5
        assert e.energy == 50


# ---------------------------------------------------------------------------
# CSV writing
# ---------------------------------------------------------------------------

class TestCSV:
    def test_write_header_and_rows(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = f.name

        try:
            write_csv_row(path, tick=0, counts={}, header=True)
            write_csv_row(path, tick=1, counts={"ant": 10, "bird": 5, "firefly": 8, "wolf": 2}, food_count=50)
            write_csv_row(path, tick=2, counts={"ant": 9, "bird": 4, "firefly": 7, "wolf": 1}, food_count=55)

            with open(path, newline="") as fh:
                reader = list(csv.DictReader(fh))
            assert len(reader) == 2
            assert reader[0]["tick"] == "1"
            assert reader[0]["ants"] == "10"
            assert reader[1]["wolves"] == "1"
            assert reader[1]["total_food"] == "55"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Species names constant
# ---------------------------------------------------------------------------

class TestConstants:
    def test_species_names(self) -> None:
        assert set(SPECIES_NAMES) == {"ant", "bird", "firefly", "wolf"}


# ---------------------------------------------------------------------------
# Energy drain logic (integration-style)
# ---------------------------------------------------------------------------

class TestEnergyDrain:
    def test_entity_dies_at_zero_energy(self) -> None:
        e = Entity(x=0, y=0, energy=1, species_name="ant")
        e.energy += config.ENERGY_PER_TICK  # -1 → energy = 0
        if e.energy <= 0:
            e.alive = False
        assert not e.is_alive()

    def test_alive_entity_check(self) -> None:
        e = Entity(x=0, y=0, energy=10, species_name="bird")
        assert e.is_alive()
        e.alive = False
        assert not e.is_alive()
