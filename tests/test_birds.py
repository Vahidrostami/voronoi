"""Tests for the Sonic Birds species module."""

from __future__ import annotations

import os
import sys
import unittest

# Ensure the src directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from world import config
from world.grid import Grid, Terrain
from world.entity import Action, Entity, WorldState
from species.birds.bird import (
    BirdSpecies,
    SignalType,
    SoundSignal,
    SIGNAL_RANGE,
    SIGNAL_MEMORY,
    WOLF_DETECTION_RADIUS,
    FOOD_DETECTION_RADIUS,
)


# ======================================================================
# Helper to build a minimal WorldState
# ======================================================================

def _make_world(
    grid: Grid,
    entities: list[Entity] | None = None,
) -> WorldState:
    return WorldState(grid=grid, entities=entities or [])


def _open_grid(width: int = 30, height: int = 30) -> Grid:
    """Return a grid with no obstacles or water."""
    g = Grid(width, height, seed=0)
    # Clear all cells to OPEN
    for x in range(width):
        for y in range(height):
            g.set_cell(x, y, Terrain.OPEN)
    return g


# ======================================================================
# Spawn tests
# ======================================================================

class TestSpawn(unittest.TestCase):
    def test_spawn_correct_count(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        birds = sp.spawn(grid, 30)
        self.assertEqual(len(birds), 30)

    def test_spawn_species_name(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        birds = sp.spawn(grid, 5)
        for b in birds:
            self.assertEqual(b.species_name, "bird")

    def test_spawn_starting_energy(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        birds = sp.spawn(grid, 5)
        for b in birds:
            self.assertEqual(b.energy, config.STARTING_ENERGY)

    def test_spawn_on_passable_cells(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        # Add some obstacles
        for x in range(0, 15):
            grid.set_cell(x, 0, Terrain.OBSTACLE)
        birds = sp.spawn(grid, 20)
        for b in birds:
            self.assertTrue(grid.is_passable(b.x, b.y))


# ======================================================================
# Render tests
# ======================================================================

class TestRender(unittest.TestCase):
    def test_render_char(self):
        sp = BirdSpecies(seed=42)
        entity = Entity(x=5, y=5, species_name="bird")
        self.assertEqual(sp.render(entity), "b")


# ======================================================================
# Signal system tests
# ======================================================================

class TestSignalSystem(unittest.TestCase):
    def test_emit_signal_creates_pending(self):
        sp = BirdSpecies(seed=42)
        bird = Entity(x=10, y=10, species_name="bird")
        sp._emit_signal(SignalType.FOOD_CALL, bird)
        self.assertEqual(len(sp._pending_signals), 1)
        self.assertEqual(sp._pending_signals[0].signal_type, SignalType.FOOD_CALL)

    def test_signal_received_within_range(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        emitter = Entity(x=10, y=10, species_name="bird")
        receiver = Entity(x=15, y=10, species_name="bird")
        sp.register_entity(emitter)
        sp.register_entity(receiver)

        sp._current_tick = 1
        sp._emit_signal(SignalType.FOOD_CALL, emitter)
        world = _make_world(grid, [emitter, receiver])
        sp._receive_signals(receiver, world)

        mem = sp._memories[receiver.id]
        self.assertEqual(len(mem.signals_heard), 1)
        self.assertEqual(mem.signals_heard[0].signal_type, SignalType.FOOD_CALL)

    def test_signal_blocked_by_obstacle(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        # Place obstacle between emitter and receiver
        grid.set_cell(12, 10, Terrain.OBSTACLE)

        emitter = Entity(x=10, y=10, species_name="bird")
        receiver = Entity(x=14, y=10, species_name="bird")
        sp.register_entity(emitter)
        sp.register_entity(receiver)

        sp._current_tick = 1
        sp._emit_signal(SignalType.FOOD_CALL, emitter)
        world = _make_world(grid, [emitter, receiver])
        sp._receive_signals(receiver, world)

        mem = sp._memories[receiver.id]
        self.assertEqual(len(mem.signals_heard), 0)

    def test_signal_not_received_beyond_range(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid(50, 50)

        emitter = Entity(x=0, y=0, species_name="bird")
        receiver = Entity(x=25, y=25, species_name="bird")
        sp.register_entity(emitter)
        sp.register_entity(receiver)

        sp._current_tick = 1
        sp._emit_signal(SignalType.FOOD_CALL, emitter)
        world = _make_world(grid, [emitter, receiver])
        sp._receive_signals(receiver, world)

        mem = sp._memories[receiver.id]
        self.assertEqual(len(mem.signals_heard), 0)

    def test_signal_not_received_by_emitter(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        emitter = Entity(x=10, y=10, species_name="bird")
        sp.register_entity(emitter)

        sp._current_tick = 1
        sp._emit_signal(SignalType.FOOD_CALL, emitter)
        world = _make_world(grid, [emitter])
        sp._receive_signals(emitter, world)

        mem = sp._memories[emitter.id]
        self.assertEqual(len(mem.signals_heard), 0)

    def test_clear_pending_signals(self):
        sp = BirdSpecies(seed=42)
        bird = Entity(x=10, y=10, species_name="bird")
        sp._emit_signal(SignalType.DANGER_CALL, bird)
        self.assertEqual(len(sp._pending_signals), 1)
        sp.clear_pending_signals()
        self.assertEqual(len(sp._pending_signals), 0)

    def test_old_signals_pruned(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        emitter = Entity(x=10, y=10, species_name="bird")
        receiver = Entity(x=12, y=10, species_name="bird")
        sp.register_entity(emitter)
        sp.register_entity(receiver)

        # Emit signal at tick 1
        sp._current_tick = 1
        sp._emit_signal(SignalType.FOOD_CALL, emitter)
        world = _make_world(grid, [emitter, receiver])
        sp._receive_signals(receiver, world)

        # Advance past memory window
        sp._current_tick = 1 + SIGNAL_MEMORY + 5
        sp.clear_pending_signals()
        # Tick the receiver to trigger pruning
        sp.tick(receiver, world)

        mem = sp._memories[receiver.id]
        food_signals = [s for s in mem.signals_heard if s.signal_type == SignalType.FOOD_CALL and s.tick == 1]
        self.assertEqual(len(food_signals), 0)


# ======================================================================
# Behaviour tests
# ======================================================================

class TestBehaviourEating(unittest.TestCase):
    def test_eat_when_on_food(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        bird = Entity(x=5, y=5, species_name="bird")
        grid.place_food(5, 5)
        sp.register_entity(bird)

        world = _make_world(grid, [bird])
        action = sp.tick(bird, world)
        self.assertEqual(action, Action.EAT)

    def test_move_toward_nearby_food(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        bird = Entity(x=5, y=5, species_name="bird")
        grid.place_food(7, 5)  # food to the east
        sp.register_entity(bird)

        world = _make_world(grid, [bird])
        action = sp.tick(bird, world)
        self.assertIn(action, [Action.MOVE_E, Action.MOVE_N, Action.MOVE_S])

    def test_emit_food_call_on_eat(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        bird = Entity(x=5, y=5, species_name="bird")
        grid.place_food(5, 5)
        sp.register_entity(bird)

        world = _make_world(grid, [bird])
        sp.tick(bird, world)
        food_signals = [s for s in sp._pending_signals if s.signal_type == SignalType.FOOD_CALL]
        self.assertGreaterEqual(len(food_signals), 1)


class TestBehaviourDanger(unittest.TestCase):
    def test_flee_from_wolf(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        bird = Entity(x=10, y=10, species_name="bird")
        wolf = Entity(x=12, y=10, species_name="wolf")
        sp.register_entity(bird)

        world = _make_world(grid, [bird, wolf])
        action = sp.tick(bird, world)
        # Should flee west (away from wolf at east)
        self.assertEqual(action, Action.MOVE_W)

    def test_emit_danger_call_on_wolf(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        bird = Entity(x=10, y=10, species_name="bird")
        wolf = Entity(x=12, y=10, species_name="wolf")
        sp.register_entity(bird)

        world = _make_world(grid, [bird, wolf])
        sp.tick(bird, world)
        danger_signals = [s for s in sp._pending_signals if s.signal_type == SignalType.DANGER_CALL]
        self.assertGreaterEqual(len(danger_signals), 1)


class TestBehaviourReproduction(unittest.TestCase):
    def test_reproduce_when_energy_high(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        bird = Entity(x=10, y=10, energy=config.REPRODUCE_THRESHOLD, species_name="bird")
        sp.register_entity(bird)

        world = _make_world(grid, [bird])
        action = sp.tick(bird, world)
        self.assertEqual(action, Action.REPRODUCE)


class TestBehaviourFlocking(unittest.TestCase):
    def test_idle_when_surrounded_by_obstacles(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        bird = Entity(x=5, y=5, species_name="bird")
        # Surround with obstacles
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            grid.set_cell(5 + dx, 5 + dy, Terrain.OBSTACLE)
        sp.register_entity(bird)

        world = _make_world(grid, [bird])
        action = sp.tick(bird, world)
        self.assertEqual(action, Action.IDLE)

    def test_random_move_no_stimuli(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        bird = Entity(x=15, y=15, species_name="bird")
        sp.register_entity(bird)

        world = _make_world(grid, [bird])
        action = sp.tick(bird, world)
        self.assertIn(action, [
            Action.MOVE_N, Action.MOVE_S, Action.MOVE_E, Action.MOVE_W,
        ])


# ======================================================================
# Movement helper tests
# ======================================================================

class TestMovementHelpers(unittest.TestCase):
    def test_move_toward(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        bird = Entity(x=5, y=5, species_name="bird")
        action = sp._move_toward(bird, 8, 5, grid)
        self.assertEqual(action, Action.MOVE_E)

    def test_move_away(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        bird = Entity(x=5, y=5, species_name="bird")
        action = sp._move_away(bird, 8, 5, grid)
        self.assertEqual(action, Action.MOVE_W)

    def test_action_dest(self):
        grid = _open_grid()
        bird = Entity(x=0, y=0, species_name="bird")
        # Moving north from (0,0) should wrap to (0, height-1)
        nx, ny = BirdSpecies._action_dest(bird, Action.MOVE_N, grid)
        self.assertEqual(nx, 0)
        self.assertEqual(ny, grid.height - 1)

    def test_closest(self):
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        bird = Entity(x=5, y=5, species_name="bird")
        positions = [(10, 10), (6, 5), (20, 20)]
        closest = sp._closest(bird, positions, grid)
        self.assertEqual(closest, (6, 5))


# ======================================================================
# Integration: full tick cycle
# ======================================================================

class TestIntegration(unittest.TestCase):
    def test_full_tick_cycle(self):
        """Spawn birds and run several ticks without errors."""
        sp = BirdSpecies(seed=42)
        grid = _open_grid(50, 50)
        # Place some food
        for x in range(0, 50, 5):
            for y in range(0, 50, 5):
                grid.place_food(x, y)

        birds = sp.spawn(grid, config.BIRD_COUNT)
        self.assertEqual(len(birds), config.BIRD_COUNT)

        for _ in range(20):
            for bird in birds:
                if bird.is_alive():
                    action = sp.tick(bird, _make_world(grid, birds))
                    self.assertIsInstance(action, Action)
            sp.clear_pending_signals()

    def test_food_call_propagates(self):
        """One bird eats, nearby bird hears FOOD_CALL and moves toward it."""
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        eater = Entity(x=10, y=10, species_name="bird")
        listener = Entity(x=15, y=10, species_name="bird")
        grid.place_food(10, 10)
        sp.register_entity(eater)
        sp.register_entity(listener)

        world = _make_world(grid, [eater, listener])

        # Tick 1: eater eats and emits FOOD_CALL
        action1 = sp.tick(eater, world)
        self.assertEqual(action1, Action.EAT)

        # Tick 2: listener processes signals and should move toward eater
        action2 = sp.tick(listener, world)
        self.assertEqual(action2, Action.MOVE_W)  # toward (10,10) from (15,10)

    def test_danger_call_propagates(self):
        """One bird sees wolf, nearby bird hears DANGER_CALL and moves away."""
        sp = BirdSpecies(seed=42)
        grid = _open_grid()
        sentry = Entity(x=10, y=10, species_name="bird")
        listener = Entity(x=15, y=10, species_name="bird")
        wolf = Entity(x=12, y=10, species_name="wolf")
        sp.register_entity(sentry)
        sp.register_entity(listener)

        world = _make_world(grid, [sentry, listener, wolf])

        # Tick 1: sentry sees wolf, emits DANGER_CALL
        sp.tick(sentry, world)
        danger = [s for s in sp._pending_signals if s.signal_type == SignalType.DANGER_CALL]
        self.assertTrue(len(danger) > 0)

        # Tick 2: listener hears DANGER_CALL and should move away from source
        action2 = sp.tick(listener, world)
        # Should move east (away from sentry at x=10)
        self.assertEqual(action2, Action.MOVE_E)


# ======================================================================
# Config value tests
# ======================================================================

class TestConfigValues(unittest.TestCase):
    def test_bird_count(self):
        self.assertEqual(config.BIRD_COUNT, 30)

    def test_energy_values(self):
        self.assertEqual(config.ENERGY_PER_FOOD, 10)
        self.assertEqual(config.ENERGY_PER_TICK, -1)
        self.assertEqual(config.REPRODUCE_THRESHOLD, 80)
        self.assertEqual(config.REPRODUCE_COST, 40)


if __name__ == "__main__":
    unittest.main()
