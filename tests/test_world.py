"""Tests for the World Engine module."""

from __future__ import annotations

import sys
import os
import unittest

# Ensure the src directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from world import config
from world.grid import Grid, Terrain
from world.entity import Action, Entity, Species, WorldState


# ======================================================================
# Config tests
# ======================================================================


class TestConfig(unittest.TestCase):
    """Verify config constants are the expected values."""

    def test_grid_dimensions(self):
        self.assertEqual(config.GRID_WIDTH, 100)
        self.assertEqual(config.GRID_HEIGHT, 100)

    def test_food_constants(self):
        self.assertEqual(config.FOOD_SPAWN_RATE, 5)
        self.assertEqual(config.MAX_FOOD, 200)
        self.assertEqual(config.ENERGY_PER_FOOD, 10)

    def test_energy_constants(self):
        self.assertEqual(config.ENERGY_PER_TICK, -1)
        self.assertEqual(config.STARTING_ENERGY, 50)

    def test_reproduction_constants(self):
        self.assertEqual(config.REPRODUCE_THRESHOLD, 80)
        self.assertEqual(config.REPRODUCE_COST, 40)

    def test_species_counts(self):
        self.assertEqual(config.ANT_COUNT, 50)
        self.assertEqual(config.BIRD_COUNT, 30)
        self.assertEqual(config.FIREFLY_COUNT, 40)
        self.assertEqual(config.WOLF_COUNT, 10)
        self.assertEqual(config.WOLF_HUNGER_LIMIT, 50)


# ======================================================================
# Grid tests
# ======================================================================


class TestGridBasics(unittest.TestCase):
    """Core grid functionality."""

    def setUp(self):
        self.grid = Grid(20, 20, seed=42)

    def test_dimensions(self):
        self.assertEqual(self.grid.width, 20)
        self.assertEqual(self.grid.height, 20)

    def test_all_cells_have_terrain(self):
        for x, y, t in self.grid:
            self.assertIsInstance(t, Terrain)

    def test_terrain_distribution(self):
        counts = {Terrain.OPEN: 0, Terrain.OBSTACLE: 0, Terrain.WATER: 0}
        for _, _, t in self.grid:
            counts[t] += 1
        total = 20 * 20
        # ~10% obstacles, ~5% water
        self.assertEqual(counts[Terrain.OBSTACLE], int(total * config.OBSTACLE_RATIO))
        self.assertEqual(counts[Terrain.WATER], int(total * config.WATER_RATIO))

    def test_set_and_get_cell(self):
        self.grid.set_cell(5, 5, Terrain.WATER)
        self.assertEqual(self.grid.get_cell(5, 5), Terrain.WATER)


class TestGridToroidal(unittest.TestCase):
    """Wrapping / toroidal topology."""

    def setUp(self):
        self.grid = Grid(10, 10, seed=0)

    def test_wrap_positive(self):
        self.assertEqual(self.grid.wrap(12, 15), (2, 5))

    def test_wrap_negative(self):
        self.assertEqual(self.grid.wrap(-1, -3), (9, 7))

    def test_get_cell_wraps(self):
        self.grid.set_cell(0, 0, Terrain.WATER)
        self.assertEqual(self.grid.get_cell(10, 10), Terrain.WATER)

    def test_is_passable(self):
        self.grid.set_cell(3, 3, Terrain.OBSTACLE)
        self.assertFalse(self.grid.is_passable(3, 3))
        self.grid.set_cell(3, 3, Terrain.OPEN)
        self.assertTrue(self.grid.is_passable(3, 3))
        self.grid.set_cell(3, 3, Terrain.WATER)
        self.assertTrue(self.grid.is_passable(3, 3))


class TestGridNeighbors(unittest.TestCase):

    def test_radius_1(self):
        g = Grid(10, 10, seed=0)
        nbrs = g.get_neighbors(5, 5, radius=1)
        self.assertEqual(len(nbrs), 8)
        self.assertNotIn((5, 5), nbrs)

    def test_wrapping_neighbors(self):
        g = Grid(10, 10, seed=0)
        nbrs = g.get_neighbors(0, 0, radius=1)
        self.assertEqual(len(nbrs), 8)
        self.assertIn((9, 9), nbrs)
        self.assertIn((1, 1), nbrs)


class TestGridLineOfSight(unittest.TestCase):

    def test_clear_path(self):
        g = Grid(20, 20, seed=99)
        # Clear a corridor
        for x in range(5, 10):
            g.set_cell(x, 5, Terrain.OPEN)
        self.assertTrue(g.line_of_sight(5, 5, 9, 5))

    def test_blocked_path(self):
        g = Grid(20, 20, seed=99)
        for x in range(5, 10):
            g.set_cell(x, 5, Terrain.OPEN)
        g.set_cell(7, 5, Terrain.OBSTACLE)
        self.assertFalse(g.line_of_sight(5, 5, 9, 5))

    def test_same_cell(self):
        g = Grid(10, 10, seed=0)
        self.assertTrue(g.line_of_sight(3, 3, 3, 3))


class TestGridFood(unittest.TestCase):

    def setUp(self):
        self.grid = Grid(10, 10, seed=0)
        # Ensure cell (1,1) is open
        self.grid.set_cell(1, 1, Terrain.OPEN)

    def test_place_and_remove(self):
        self.assertTrue(self.grid.place_food(1, 1))
        self.assertEqual(self.grid.food_count, 1)
        self.assertIn((1, 1), self.grid.get_food_positions())
        self.assertTrue(self.grid.has_food(1, 1))

        self.assertTrue(self.grid.remove_food(1, 1))
        self.assertEqual(self.grid.food_count, 0)

    def test_no_food_on_obstacle(self):
        self.grid.set_cell(2, 2, Terrain.OBSTACLE)
        self.assertFalse(self.grid.place_food(2, 2))

    def test_max_food_cap(self):
        # Use a small grid — fill to MAX_FOOD
        g = Grid(50, 50, seed=0)
        placed = 0
        for x in range(50):
            for y in range(50):
                if g.is_passable(x, y) and placed < config.MAX_FOOD:
                    if g.place_food(x, y):
                        placed += 1
        self.assertEqual(g.food_count, config.MAX_FOOD)
        # One more should fail
        # Find an open cell not already holding food
        for x in range(50):
            for y in range(50):
                if g.is_passable(x, y) and not g.has_food(x, y):
                    self.assertFalse(g.place_food(x, y))
                    return

    def test_remove_nonexistent(self):
        self.assertFalse(self.grid.remove_food(5, 5))


# ======================================================================
# Entity tests
# ======================================================================


class TestEntity(unittest.TestCase):

    def test_defaults(self):
        e = Entity(x=10, y=20)
        self.assertEqual(e.position, (10, 20))
        self.assertEqual(e.energy, config.STARTING_ENERGY)
        self.assertTrue(e.alive)
        self.assertTrue(e.is_alive())
        self.assertIsInstance(e.id, str)
        self.assertTrue(len(e.id) > 0)

    def test_unique_ids(self):
        ids = {Entity(x=0, y=0).id for _ in range(100)}
        self.assertEqual(len(ids), 100)

    def test_is_alive_with_zero_energy(self):
        e = Entity(x=0, y=0, energy=0)
        self.assertFalse(e.is_alive())

    def test_is_alive_when_dead(self):
        e = Entity(x=0, y=0, alive=False)
        self.assertFalse(e.is_alive())


class TestAction(unittest.TestCase):

    def test_all_actions(self):
        expected = {"move_n", "move_s", "move_e", "move_w", "eat", "reproduce", "idle"}
        actual = {a.value for a in Action}
        self.assertEqual(actual, expected)


# ======================================================================
# WorldState tests
# ======================================================================


class TestWorldState(unittest.TestCase):

    def setUp(self):
        self.grid = Grid(20, 20, seed=42)
        self.entities = [
            Entity(x=5, y=5, species_name="test"),
            Entity(x=6, y=5, species_name="test"),
            Entity(x=15, y=15, species_name="test"),
        ]
        self.ws = WorldState(grid=self.grid, entities=self.entities)

    def test_nearby_entities(self):
        near = self.ws.nearby_entities((5, 5), radius=2)
        self.assertIn(self.entities[1], near)
        self.assertNotIn(self.entities[0], near)  # self excluded
        self.assertNotIn(self.entities[2], near)  # too far

    def test_nearby_food(self):
        self.grid.set_cell(5, 6, Terrain.OPEN)
        self.grid.place_food(5, 6)
        food = self.ws.nearby_food((5, 5), radius=2)
        self.assertIn((5, 6), food)

    def test_terrain_at(self):
        self.grid.set_cell(3, 3, Terrain.WATER)
        self.assertEqual(self.ws.terrain_at((3, 3)), Terrain.WATER)

    def test_toroidal_nearby_entities(self):
        """Entities near grid edge should detect entities on the other side."""
        e_at_edge = Entity(x=0, y=0, species_name="test")
        e_wrapped = Entity(x=19, y=19, species_name="test")
        ws = WorldState(grid=self.grid, entities=[e_at_edge, e_wrapped])
        near = ws.nearby_entities((0, 0), radius=2)
        self.assertIn(e_wrapped, near)


# ======================================================================
# Species interface tests
# ======================================================================


class _DummySpecies(Species):
    """Minimal concrete species for testing the ABC."""

    name = "dummy"

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        return [Entity(x=0, y=0, species_name=self.name) for _ in range(count)]

    def tick(self, entity: Entity, world_state: WorldState) -> Action:
        return Action.IDLE

    def render(self, entity: Entity) -> str:
        return "D"


class TestSpecies(unittest.TestCase):

    def test_concrete_subclass(self):
        sp = _DummySpecies()
        entities = sp.spawn(Grid(10, 10, seed=0), 3)
        self.assertEqual(len(entities), 3)
        for e in entities:
            self.assertEqual(e.species_name, "dummy")

    def test_tick_returns_action(self):
        sp = _DummySpecies()
        grid = Grid(10, 10, seed=0)
        ws = WorldState(grid=grid, entities=[])
        e = Entity(x=0, y=0, species_name="dummy")
        self.assertEqual(sp.tick(e, ws), Action.IDLE)

    def test_render(self):
        sp = _DummySpecies()
        self.assertEqual(sp.render(Entity(x=0, y=0)), "D")

    def test_abstract_methods_enforced(self):
        with self.assertRaises(TypeError):

            class IncompleteSpecies(Species):  # type: ignore[abstract]
                name = "bad"

            IncompleteSpecies()  # type: ignore


# ======================================================================
# Package import tests
# ======================================================================


class TestPackageExports(unittest.TestCase):

    def test_imports(self):
        from world import Action, Entity, Grid, Species, Terrain, WorldState, config

        self.assertIsNotNone(Grid)
        self.assertIsNotNone(Entity)
        self.assertIsNotNone(Species)
        self.assertIsNotNone(Action)
        self.assertIsNotNone(WorldState)
        self.assertIsNotNone(Terrain)
        self.assertIsNotNone(config)


if __name__ == "__main__":
    unittest.main()
