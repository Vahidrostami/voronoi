"""Tests for the Pheromone Ants species module."""

from __future__ import annotations

import sys
import os
import unittest

# Ensure repo root is on the path so `src.world` is importable.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.world.entity import Action, Entity, WorldState
from src.world.grid import Grid, Terrain
from src.world import config
from src.species.ants.ant import AntSpecies, _PHEROMONE_DECAY, _PHEROMONE_DEPOSIT, _PHEROMONE_MIN


class TestAntSpeciesSpawn(unittest.TestCase):
    """Tests for AntSpecies.spawn."""

    def test_spawn_returns_correct_count(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=1)
        ants = sp.spawn(grid, 10)
        self.assertEqual(len(ants), 10)

    def test_spawned_ants_on_passable_cells(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=1)
        ants = sp.spawn(grid, 15)
        for e in ants:
            self.assertTrue(grid.is_passable(e.x, e.y))

    def test_spawned_ants_have_correct_species_name(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=1)
        ants = sp.spawn(grid, 5)
        for e in ants:
            self.assertEqual(e.species_name, "ant")

    def test_spawned_ants_have_starting_energy(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=1)
        ants = sp.spawn(grid, 5)
        for e in ants:
            self.assertEqual(e.energy, config.STARTING_ENERGY)

    def test_colony_centre_computed(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=1)
        sp.spawn(grid, 10)
        # Colony is set to some non-default value
        self.assertIsInstance(sp._colony, tuple)
        self.assertEqual(len(sp._colony), 2)


class TestRender(unittest.TestCase):
    def test_render_returns_a(self):
        sp = AntSpecies()
        e = Entity(x=0, y=0, species_name="ant")
        self.assertEqual(sp.render(e), "a")


class TestPheromoneDecay(unittest.TestCase):
    """Tests for pheromone decay mechanics."""

    def test_decay_reduces_strength(self):
        sp = AntSpecies()
        sp.pheromones[(5, 5)] = 10.0
        sp._decay_pheromones()
        self.assertAlmostEqual(sp.pheromones[(5, 5)], 10.0 * _PHEROMONE_DECAY)

    def test_decay_prunes_negligible(self):
        sp = AntSpecies()
        sp.pheromones[(5, 5)] = _PHEROMONE_MIN * 0.5  # below threshold after decay
        sp._decay_pheromones()
        self.assertNotIn((5, 5), sp.pheromones)

    def test_decay_preserves_strong_trails(self):
        sp = AntSpecies()
        sp.pheromones[(1, 1)] = 100.0
        sp.pheromones[(2, 2)] = 0.001  # will be pruned
        sp._decay_pheromones()
        self.assertIn((1, 1), sp.pheromones)
        self.assertNotIn((2, 2), sp.pheromones)


class TestPheromoneDeposit(unittest.TestCase):
    """Test that ants deposit pheromone when they tick."""

    def _make_world(self, grid: Grid, entities: list[Entity]) -> WorldState:
        return WorldState(grid=grid, entities=entities)

    def test_tick_deposits_pheromone(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=42)
        # Place ant on a passable cell
        e = Entity(x=5, y=5, energy=30, species_name="ant")
        # Make sure cell is passable
        grid.set_cell(5, 5, Terrain.OPEN)
        ws = self._make_world(grid, [e])
        sp.tick(e, ws)
        self.assertIn((5, 5), sp.pheromones)
        self.assertGreaterEqual(sp.pheromones[(5, 5)], _PHEROMONE_DEPOSIT * _PHEROMONE_DECAY)


class TestTickBehavior(unittest.TestCase):
    """Tests for tick decision priority."""

    def _make_world(self, grid: Grid, entities: list[Entity]) -> WorldState:
        return WorldState(grid=grid, entities=entities)

    def test_eat_when_food_present(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=42)
        grid.set_cell(5, 5, Terrain.OPEN)
        grid.place_food(5, 5)
        e = Entity(x=5, y=5, energy=30, species_name="ant")
        ws = self._make_world(grid, [e])
        action = sp.tick(e, ws)
        self.assertEqual(action, Action.EAT)

    def test_reproduce_when_energy_high(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=42)
        grid.set_cell(5, 5, Terrain.OPEN)
        e = Entity(x=5, y=5, energy=config.REPRODUCE_THRESHOLD, species_name="ant")
        ws = self._make_world(grid, [e])
        action = sp.tick(e, ws)
        self.assertEqual(action, Action.REPRODUCE)

    def test_move_toward_food(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=42)
        grid.set_cell(5, 5, Terrain.OPEN)
        grid.set_cell(7, 5, Terrain.OPEN)
        grid.place_food(7, 5)
        e = Entity(x=5, y=5, energy=30, species_name="ant")
        ws = self._make_world(grid, [e])
        action = sp.tick(e, ws)
        # Should move east toward food at (7,5)
        self.assertEqual(action, Action.MOVE_E)

    def test_follow_pheromone_gradient(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=42)
        grid.set_cell(5, 5, Terrain.OPEN)
        grid.set_cell(5, 4, Terrain.OPEN)
        grid.set_cell(5, 6, Terrain.OPEN)
        grid.set_cell(6, 5, Terrain.OPEN)
        grid.set_cell(4, 5, Terrain.OPEN)
        # Strong pheromone to the north
        sp.pheromones[(5, 4)] = 50.0
        e = Entity(x=5, y=5, energy=30, species_name="ant")
        ws = self._make_world(grid, [e])
        action = sp.tick(e, ws)
        self.assertEqual(action, Action.MOVE_N)

    def test_random_walk_no_food_no_pheromone(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=42)
        # Clear area around (10,10)
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                grid.set_cell(10 + dx, 10 + dy, Terrain.OPEN)
        e = Entity(x=10, y=10, energy=30, species_name="ant")
        ws = self._make_world(grid, [e])
        action = sp.tick(e, ws)
        self.assertIn(action, [Action.MOVE_N, Action.MOVE_S, Action.MOVE_E, Action.MOVE_W, Action.IDLE])

    def test_idle_when_surrounded_by_obstacles(self):
        sp = AntSpecies()
        grid = Grid(10, 10, seed=0)
        # Clear center, block all neighbours
        grid.set_cell(5, 5, Terrain.OPEN)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            grid.set_cell(5 + dx, 5 + dy, Terrain.OBSTACLE)
        e = Entity(x=5, y=5, energy=30, species_name="ant")
        ws = self._make_world(grid, [e])
        action = sp.tick(e, ws)
        # No valid move direction — should fall through to IDLE
        self.assertEqual(action, Action.IDLE)


class TestReinforceTrail(unittest.TestCase):
    """Tests for trail reinforcement toward colony."""

    def test_reinforce_adds_pheromone_along_path(self):
        sp = AntSpecies()
        sp._colony = (0, 0)
        grid = Grid(20, 20, seed=42)
        e = Entity(x=5, y=5, energy=30, species_name="ant")
        sp._reinforce_trail_to_colony(e, grid)
        # Path from (5,5) to (0,0) should have pheromone deposits
        self.assertGreater(len(sp.pheromones), 0)
        # Colony and entity positions should have pheromone
        self.assertIn((0, 0), sp.pheromones)
        self.assertIn((5, 5), sp.pheromones)


class TestMoveToward(unittest.TestCase):
    """Test directional movement helper."""

    def test_move_east(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=42)
        grid.set_cell(5, 5, Terrain.OPEN)
        grid.set_cell(6, 5, Terrain.OPEN)
        e = Entity(x=5, y=5, species_name="ant")
        action = sp._move_toward(e, (8, 5), grid)
        self.assertEqual(action, Action.MOVE_E)

    def test_move_north(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=42)
        grid.set_cell(5, 5, Terrain.OPEN)
        grid.set_cell(5, 4, Terrain.OPEN)
        e = Entity(x=5, y=5, species_name="ant")
        action = sp._move_toward(e, (5, 2), grid)
        self.assertEqual(action, Action.MOVE_N)


class TestFollowPheromone(unittest.TestCase):
    """Test pheromone gradient following."""

    def test_returns_none_when_no_pheromone(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=42)
        e = Entity(x=5, y=5, species_name="ant")
        result = sp._follow_pheromone(e, grid)
        self.assertIsNone(result)

    def test_returns_direction_of_strongest(self):
        sp = AntSpecies()
        grid = Grid(20, 20, seed=42)
        grid.set_cell(5, 5, Terrain.OPEN)
        grid.set_cell(6, 5, Terrain.OPEN)
        grid.set_cell(4, 5, Terrain.OPEN)
        sp.pheromones[(6, 5)] = 10.0
        sp.pheromones[(4, 5)] = 2.0
        e = Entity(x=5, y=5, species_name="ant")
        result = sp._follow_pheromone(e, grid)
        self.assertEqual(result, Action.MOVE_E)


class TestDefaultAntCount(unittest.TestCase):
    """Verify the config matches requirements."""

    def test_ant_count_is_50(self):
        self.assertEqual(config.ANT_COUNT, 50)


class TestImportFromInit(unittest.TestCase):
    """Test that __init__.py exports AntSpecies."""

    def test_import(self):
        from src.species.ants import AntSpecies as Imported
        self.assertIs(Imported, AntSpecies)


if __name__ == "__main__":
    unittest.main()
