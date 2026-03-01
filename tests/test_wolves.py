"""Tests for the Predator Wolves species module."""

from __future__ import annotations

import sys
import os
import unittest

# Ensure repo root is on sys.path so `src.*` imports work
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from src.world.entity import Action, Entity, WorldState
from src.world.grid import Grid
from src.world import config
from src.species.wolves import WolfSpecies


def _make_grid(width: int = 20, height: int = 20) -> Grid:
    """Small all-open grid for testing."""
    g = Grid(width, height, seed=0)
    # Make all cells open for deterministic tests
    from src.world.grid import Terrain
    for i in range(len(g._cells)):
        g._cells[i] = Terrain.OPEN
    return g


def _make_world(grid: Grid, entities: list[Entity]) -> WorldState:
    return WorldState(grid=grid, entities=entities)


class TestWolfSpeciesInit(unittest.TestCase):
    def test_name(self):
        ws = WolfSpecies()
        self.assertEqual(ws.name, "wolf")

    def test_initial_maps_empty(self):
        ws = WolfSpecies()
        self.assertEqual(ws.scent_map, {})
        self.assertEqual(ws.ticks_since_last_meal, {})


class TestSpawn(unittest.TestCase):
    def test_spawn_correct_count(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolves = ws.spawn(grid, 10)
        self.assertEqual(len(wolves), 10)

    def test_spawn_sets_species_name(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolves = ws.spawn(grid, 3)
        for w in wolves:
            self.assertEqual(w.species_name, "wolf")

    def test_spawn_initialises_hunger(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolves = ws.spawn(grid, 5)
        for w in wolves:
            self.assertIn(w.id, ws.ticks_since_last_meal)
            self.assertEqual(ws.ticks_since_last_meal[w.id], 0)

    def test_spawn_on_passable_cells(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolves = ws.spawn(grid, 10)
        for w in wolves:
            self.assertTrue(grid.is_passable(w.x, w.y))


class TestRender(unittest.TestCase):
    def test_render_char(self):
        ws = WolfSpecies()
        e = Entity(x=0, y=0, species_name="wolf")
        self.assertEqual(ws.render(e), "W")


class TestScentSystem(unittest.TestCase):
    def test_scent_deposited_from_prey(self):
        ws = WolfSpecies()
        grid = _make_grid()
        prey = Entity(x=5, y=5, species_name="rabbit")
        wolf = Entity(x=0, y=0, species_name="wolf")
        ws.ticks_since_last_meal[wolf.id] = 0
        world = _make_world(grid, [wolf, prey])

        ws.tick(wolf, world)
        self.assertIn((5, 5), ws.scent_map)
        self.assertAlmostEqual(ws.scent_map[(5, 5)], 1.0)

    def test_scent_decays(self):
        ws = WolfSpecies()
        ws.scent_map[(3, 3)] = 1.0
        grid = _make_grid()
        wolf = Entity(x=0, y=0, species_name="wolf")
        ws.ticks_since_last_meal[wolf.id] = 0
        world = _make_world(grid, [wolf])

        ws.tick(wolf, world)
        self.assertAlmostEqual(ws.scent_map.get((3, 3), 0.0), 0.9)

    def test_weak_scent_removed(self):
        ws = WolfSpecies()
        ws.scent_map[(3, 3)] = 0.005  # below _SCENT_MIN after decay
        grid = _make_grid()
        wolf = Entity(x=0, y=0, species_name="wolf")
        ws.ticks_since_last_meal[wolf.id] = 0
        world = _make_world(grid, [wolf])

        ws.tick(wolf, world)
        self.assertNotIn((3, 3), ws.scent_map)

    def test_wolf_scent_not_deposited(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolf1 = Entity(x=0, y=0, species_name="wolf")
        wolf2 = Entity(x=5, y=5, species_name="wolf")
        ws.ticks_since_last_meal[wolf1.id] = 0
        ws.ticks_since_last_meal[wolf2.id] = 0
        world = _make_world(grid, [wolf1, wolf2])

        ws.tick(wolf1, world)
        # wolf positions should NOT have scent deposited
        self.assertNotIn((5, 5), ws.scent_map)
        self.assertNotIn((0, 0), ws.scent_map)


class TestAttackBehaviour(unittest.TestCase):
    def test_attack_adjacent_prey(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolf = Entity(x=5, y=5, energy=30, species_name="wolf")
        prey = Entity(x=5, y=6, energy=20, species_name="rabbit")
        ws.ticks_since_last_meal[wolf.id] = 10
        world = _make_world(grid, [wolf, prey])

        ws.tick(wolf, world)
        self.assertFalse(prey.alive)
        # Wolf should gain energy (30 + ENERGY_PER_TICK + _ENERGY_FROM_PREY = 39)
        self.assertEqual(wolf.energy, 30 + config.ENERGY_PER_TICK + 10)
        # Hunger reset
        self.assertEqual(ws.ticks_since_last_meal[wolf.id], 0)


class TestHungerDeath(unittest.TestCase):
    def test_wolf_dies_when_hunger_exceeded(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolf = Entity(x=0, y=0, energy=100, species_name="wolf")
        ws.ticks_since_last_meal[wolf.id] = config.WOLF_HUNGER_LIMIT  # next tick exceeds

        world = _make_world(grid, [wolf])
        action = ws.tick(wolf, world)

        self.assertFalse(wolf.alive)
        self.assertEqual(action, Action.IDLE)

    def test_wolf_survives_at_hunger_limit(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolf = Entity(x=0, y=0, energy=100, species_name="wolf")
        ws.ticks_since_last_meal[wolf.id] = config.WOLF_HUNGER_LIMIT - 1

        world = _make_world(grid, [wolf])
        action = ws.tick(wolf, world)

        self.assertTrue(wolf.is_alive())
        self.assertNotEqual(action, Action.IDLE)


class TestEnergyDrain(unittest.TestCase):
    def test_energy_drains_per_tick(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolf = Entity(x=0, y=0, energy=50, species_name="wolf")
        ws.ticks_since_last_meal[wolf.id] = 0

        world = _make_world(grid, [wolf])
        ws.tick(wolf, world)

        self.assertEqual(wolf.energy, 50 + config.ENERGY_PER_TICK)

    def test_wolf_dies_at_zero_energy(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolf = Entity(x=0, y=0, energy=1, species_name="wolf")
        ws.ticks_since_last_meal[wolf.id] = 0

        world = _make_world(grid, [wolf])
        action = ws.tick(wolf, world)

        # Energy should be 0 after -1 drain
        self.assertFalse(wolf.alive)
        self.assertEqual(action, Action.IDLE)


class TestReproduction(unittest.TestCase):
    def test_reproduce_when_energy_high(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolf = Entity(x=5, y=5, energy=config.REPRODUCE_THRESHOLD, species_name="wolf")
        ws.ticks_since_last_meal[wolf.id] = 0

        world = _make_world(grid, [wolf])
        action = ws.tick(wolf, world)

        # After energy drain, energy = REPRODUCE_THRESHOLD - 1
        # which is below threshold, so no reproduce
        # Need energy = REPRODUCE_THRESHOLD + 1 so after drain it's still >=
        wolf2 = Entity(x=5, y=5, energy=config.REPRODUCE_THRESHOLD + 1, species_name="wolf")
        ws.ticks_since_last_meal[wolf2.id] = 0
        world2 = _make_world(grid, [wolf2])
        action2 = ws.tick(wolf2, world2)
        self.assertEqual(action2, Action.REPRODUCE)


class TestScentFollowing(unittest.TestCase):
    def test_follows_strongest_scent(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolf = Entity(x=5, y=5, energy=50, species_name="wolf")
        ws.ticks_since_last_meal[wolf.id] = 0

        # Place scent east (strongest)
        ws.scent_map[(6, 5)] = 0.8
        ws.scent_map[(4, 5)] = 0.3

        world = _make_world(grid, [wolf])
        action = ws.tick(wolf, world)

        # After scent update (decay), (6,5) should still be strongest
        # Wolf should move east
        self.assertEqual(action, Action.MOVE_E)

    def test_random_patrol_when_no_scent(self):
        ws = WolfSpecies()
        grid = _make_grid()
        wolf = Entity(x=5, y=5, energy=50, species_name="wolf")
        ws.ticks_since_last_meal[wolf.id] = 0

        world = _make_world(grid, [wolf])
        action = ws.tick(wolf, world)

        self.assertIn(action, [Action.MOVE_N, Action.MOVE_S, Action.MOVE_E, Action.MOVE_W])


class TestDeadEntityHandling(unittest.TestCase):
    def test_dead_wolf_returns_idle(self):
        ws = WolfSpecies()
        wolf = Entity(x=0, y=0, energy=0, alive=False, species_name="wolf")
        grid = _make_grid()
        world = _make_world(grid, [wolf])
        action = ws.tick(wolf, world)
        self.assertEqual(action, Action.IDLE)


class TestExport(unittest.TestCase):
    def test_module_exports(self):
        from src.species.wolves import WolfSpecies as WS
        self.assertIs(WS, WolfSpecies)


if __name__ == "__main__":
    unittest.main()
