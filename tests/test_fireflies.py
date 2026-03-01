"""Tests for the Visual Fireflies species module."""

from __future__ import annotations

import random
import sys
import os
import unittest

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.world.grid import Grid, Terrain
from src.world.entity import Action, Entity, WorldState
from src.world import config
from src.species.fireflies import FireflySpecies
from src.species.fireflies.firefly import FlashSignal, FireflyState, _FLASH_COOLDOWN_TICKS


class TestFireflySpeciesInit(unittest.TestCase):
    """FireflySpecies basic attributes."""

    def test_name(self):
        sp = FireflySpecies()
        self.assertEqual(sp.name, "firefly")

    def test_render_char(self):
        sp = FireflySpecies()
        e = Entity(x=0, y=0, species_name="firefly")
        self.assertEqual(sp.render(e), "f")


class TestSpawn(unittest.TestCase):
    """Spawn method places entities on passable cells."""

    def test_spawn_count(self):
        sp = FireflySpecies()
        grid = Grid(20, 20, seed=42)
        entities = sp.spawn(grid, 10)
        self.assertEqual(len(entities), 10)

    def test_spawn_on_passable(self):
        sp = FireflySpecies()
        grid = Grid(20, 20, seed=42)
        entities = sp.spawn(grid, 10)
        for e in entities:
            self.assertTrue(grid.is_passable(e.x, e.y))

    def test_spawn_species_name(self):
        sp = FireflySpecies()
        grid = Grid(20, 20, seed=42)
        entities = sp.spawn(grid, 5)
        for e in entities:
            self.assertEqual(e.species_name, "firefly")

    def test_spawn_registers_state(self):
        sp = FireflySpecies()
        grid = Grid(20, 20, seed=42)
        entities = sp.spawn(grid, 3)
        for e in entities:
            self.assertIn(e.id, sp._states)


class TestDirectionHelpers(unittest.TestCase):
    """Movement direction helpers."""

    def test_toward_east(self):
        a = FireflySpecies._direction_toward(0, 0, 5, 0, 100, 100)
        self.assertEqual(a, Action.MOVE_E)

    def test_toward_west(self):
        a = FireflySpecies._direction_toward(5, 0, 0, 0, 100, 100)
        self.assertEqual(a, Action.MOVE_W)

    def test_toward_south(self):
        a = FireflySpecies._direction_toward(0, 0, 0, 5, 100, 100)
        self.assertEqual(a, Action.MOVE_S)

    def test_toward_north(self):
        a = FireflySpecies._direction_toward(0, 5, 0, 0, 100, 100)
        self.assertEqual(a, Action.MOVE_N)

    def test_away_from_east(self):
        a = FireflySpecies._direction_away(0, 0, 5, 0, 100, 100)
        self.assertEqual(a, Action.MOVE_W)

    def test_away_from_north(self):
        a = FireflySpecies._direction_away(0, 5, 0, 0, 100, 100)
        self.assertEqual(a, Action.MOVE_S)


class _BaseTickTest(unittest.TestCase):
    """Helper: build a small all-open grid + world state."""

    def _make_grid(self, w: int = 20, h: int = 20) -> Grid:
        g = Grid(w, h, seed=0)
        # Clear obstacles for deterministic tests
        for i in range(len(g._cells)):
            g._cells[i] = Terrain.OPEN
        return g

    def _world(self, grid: Grid, entities: list[Entity]) -> WorldState:
        return WorldState(grid=grid, entities=entities)


class TestTickEat(_BaseTickTest):
    """Firefly eats food at current cell and emits DOUBLE_FLASH."""

    def test_eat_when_food_present(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        e = Entity(x=5, y=5, energy=30, species_name="firefly")
        sp._states[e.id] = FireflyState()
        grid.place_food(5, 5)
        ws = self._world(grid, [e])
        action = sp.tick(e, ws)
        self.assertEqual(action, Action.EAT)

    def test_eat_emits_double_flash(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        e = Entity(x=5, y=5, energy=30, species_name="firefly")
        sp._states[e.id] = FireflyState()
        grid.place_food(5, 5)
        ws = self._world(grid, [e])
        sp.tick(e, ws)
        self.assertEqual(sp._states[e.id].flash_state, FlashSignal.DOUBLE_FLASH)

    def test_eat_sets_cooldown(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        e = Entity(x=5, y=5, energy=30, species_name="firefly")
        sp._states[e.id] = FireflyState()
        grid.place_food(5, 5)
        ws = self._world(grid, [e])
        sp.tick(e, ws)
        self.assertEqual(sp._states[e.id].flash_cooldown, _FLASH_COOLDOWN_TICKS)


class TestTickDanger(_BaseTickTest):
    """Firefly flees wolves and emits RAPID_FLASH."""

    def test_flee_wolf(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        ff = Entity(x=5, y=5, energy=30, species_name="firefly")
        wolf = Entity(x=6, y=5, energy=50, species_name="wolf")
        sp._states[ff.id] = FireflyState()
        ws = self._world(grid, [ff, wolf])
        action = sp.tick(ff, ws)
        # Should flee west (away from wolf at x=6)
        self.assertEqual(action, Action.MOVE_W)

    def test_wolf_emits_rapid_flash(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        ff = Entity(x=5, y=5, energy=30, species_name="firefly")
        wolf = Entity(x=6, y=5, energy=50, species_name="wolf")
        sp._states[ff.id] = FireflyState()
        ws = self._world(grid, [ff, wolf])
        sp.tick(ff, ws)
        self.assertEqual(sp._states[ff.id].flash_state, FlashSignal.RAPID_FLASH)

    def test_wolf_behind_obstacle_not_visible(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        # Place obstacle between firefly and wolf
        grid.set_cell(6, 5, Terrain.OBSTACLE)
        ff = Entity(x=5, y=5, energy=30, species_name="firefly")
        wolf = Entity(x=7, y=5, energy=50, species_name="wolf")
        sp._states[ff.id] = FireflyState()
        ws = self._world(grid, [ff, wolf])
        action = sp.tick(ff, ws)
        # Wolf not visible — should NOT flee (random walk or other)
        self.assertNotEqual(sp._states[ff.id].flash_state, FlashSignal.RAPID_FLASH)


class TestTickFlashSignalResponse(_BaseTickTest):
    """Firefly responds to flash signals from visible peers."""

    def test_move_toward_double_flash(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        ff1 = Entity(x=5, y=5, energy=30, species_name="firefly")
        ff2 = Entity(x=8, y=5, energy=30, species_name="firefly")
        sp._states[ff1.id] = FireflyState()
        sp._states[ff2.id] = FireflyState(flash_state=FlashSignal.DOUBLE_FLASH)
        ws = self._world(grid, [ff1, ff2])
        action = sp.tick(ff1, ws)
        self.assertEqual(action, Action.MOVE_E)

    def test_move_away_from_rapid_flash(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        ff1 = Entity(x=5, y=5, energy=30, species_name="firefly")
        ff2 = Entity(x=8, y=5, energy=30, species_name="firefly")
        sp._states[ff1.id] = FireflyState()
        sp._states[ff2.id] = FireflyState(flash_state=FlashSignal.RAPID_FLASH)
        ws = self._world(grid, [ff1, ff2])
        action = sp.tick(ff1, ws)
        self.assertEqual(action, Action.MOVE_W)

    def test_flash_not_visible_through_obstacle(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        grid.set_cell(6, 5, Terrain.OBSTACLE)
        ff1 = Entity(x=5, y=5, energy=30, species_name="firefly")
        ff2 = Entity(x=8, y=5, energy=30, species_name="firefly")
        sp._states[ff1.id] = FireflyState()
        sp._states[ff2.id] = FireflyState(flash_state=FlashSignal.DOUBLE_FLASH)
        ws = self._world(grid, [ff1, ff2])
        action = sp.tick(ff1, ws)
        # ff2 not visible — should NOT move east toward it
        self.assertNotEqual(action, Action.MOVE_E)


class TestTickFoodNearby(_BaseTickTest):
    """Firefly moves toward visible food."""

    def test_move_toward_food(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        ff = Entity(x=5, y=5, energy=30, species_name="firefly")
        sp._states[ff.id] = FireflyState()
        grid.place_food(8, 5)
        ws = self._world(grid, [ff])
        action = sp.tick(ff, ws)
        self.assertEqual(action, Action.MOVE_E)

    def test_food_behind_obstacle_ignored(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        grid.set_cell(6, 5, Terrain.OBSTACLE)
        ff = Entity(x=5, y=5, energy=30, species_name="firefly")
        sp._states[ff.id] = FireflyState()
        grid.place_food(8, 5)
        ws = self._world(grid, [ff])
        action = sp.tick(ff, ws)
        # Food not visible, should not move east
        self.assertNotEqual(action, Action.MOVE_E)


class TestTickReproduce(_BaseTickTest):
    """Firefly reproduces when energy is high enough."""

    def test_reproduce_at_threshold(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        ff = Entity(x=5, y=5, energy=config.REPRODUCE_THRESHOLD, species_name="firefly")
        sp._states[ff.id] = FireflyState()
        ws = self._world(grid, [ff])
        action = sp.tick(ff, ws)
        self.assertEqual(action, Action.REPRODUCE)

    def test_no_reproduce_below_threshold(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        ff = Entity(x=5, y=5, energy=config.REPRODUCE_THRESHOLD - 1, species_name="firefly")
        sp._states[ff.id] = FireflyState()
        ws = self._world(grid, [ff])
        action = sp.tick(ff, ws)
        self.assertNotEqual(action, Action.REPRODUCE)


class TestTickRandomWalk(_BaseTickTest):
    """Firefly performs random walk when nothing else to do."""

    def test_random_walk_returns_move(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        ff = Entity(x=5, y=5, energy=30, species_name="firefly")
        sp._states[ff.id] = FireflyState()
        ws = self._world(grid, [ff])
        action = sp.tick(ff, ws)
        self.assertIn(action, [Action.MOVE_N, Action.MOVE_S, Action.MOVE_E, Action.MOVE_W])


class TestCooldown(_BaseTickTest):
    """Flash cooldown prevents spamming signals."""

    def test_cooldown_prevents_flash(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        ff = Entity(x=5, y=5, energy=30, species_name="firefly")
        sp._states[ff.id] = FireflyState(flash_cooldown=3)
        grid.place_food(5, 5)
        ws = self._world(grid, [ff])
        sp.tick(ff, ws)
        # Still eats, but no flash emitted due to cooldown
        self.assertEqual(sp._states[ff.id].flash_state, FlashSignal.NONE)

    def test_cooldown_decrements(self):
        sp = FireflySpecies()
        grid = self._make_grid()
        ff = Entity(x=5, y=5, energy=30, species_name="firefly")
        sp._states[ff.id] = FireflyState(flash_cooldown=3)
        ws = self._world(grid, [ff])
        sp.tick(ff, ws)
        self.assertEqual(sp._states[ff.id].flash_cooldown, 2)


class TestFlashSignalEnum(unittest.TestCase):
    """FlashSignal enum values."""

    def test_double_flash_value(self):
        self.assertEqual(FlashSignal.DOUBLE_FLASH.value, "double_flash")

    def test_rapid_flash_value(self):
        self.assertEqual(FlashSignal.RAPID_FLASH.value, "rapid_flash")


class TestExports(unittest.TestCase):
    """Module exports."""

    def test_init_exports_firefly_species(self):
        from src.species.fireflies import FireflySpecies as FS
        self.assertTrue(issubclass(FS, object))

    def test_is_species_subclass(self):
        from src.world.entity import Species
        self.assertTrue(issubclass(FireflySpecies, Species))


if __name__ == "__main__":
    unittest.main()
