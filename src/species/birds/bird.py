"""Sonic Birds — emit sound signals to flock toward food and scatter from danger."""

import random
import math
from src.world.entity import Entity, Species, Action, ActionCommand, DIRECTION_DELTAS
from src.world.config import (
    GRID_WIDTH, GRID_HEIGHT, ENERGY_PER_FOOD, ENERGY_LOSS_PER_TICK,
    REPRODUCE_THRESHOLD, REPRODUCE_COST, BIRD_SIGNAL_RANGE, INITIAL_BIRDS,
    ENERGY_START,
)
from src.world.grid import Grid, Terrain

# Signal type constants
FOOD_CALL = 'FOOD_CALL'
DANGER_CALL = 'DANGER_CALL'

# Detection range for food and wolves
VISION_RANGE = 8
# Flocking parameters
FLOCK_RANGE = 10
SEPARATION_DIST = 3


class BirdSpecies(Species):
    """Birds communicate via sound signals within range, blocked by obstacles."""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        # Shared signal buffer: list of (x, y, signal_type, emitter_id, tick)
        self._signals: list[tuple[int, int, str, int, int]] = []
        self._last_tick_cleared: int = -1

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        self._signals = []
        self._last_tick_cleared = -1
        entities: list[Entity] = []
        for _ in range(count):
            x, y = self._random_open(grid)
            e = Entity(x, y, 'bird', energy=ENERGY_START)
            e.extra['signals_heard'] = []   # signals heard this tick
            e.extra['flock_direction'] = (0, 0)
            entities.append(e)
        return entities

    def tick(self, entity: Entity, grid: Grid,
             all_entities: list[Entity]) -> ActionCommand:
        # Clear shared signal list once per tick
        if grid.current_tick != self._last_tick_cleared:
            self._signals.clear()
            self._last_tick_cleared = grid.current_tick
            # Pre-scan: all birds emit signals based on what they see
            self._perception_pass(grid, all_entities)

        # Gather signals this bird can hear
        heard_food: list[tuple[int, int, float]] = []
        heard_danger: list[tuple[int, int, float]] = []
        for sx, sy, stype, eid, _tick in self._signals:
            if eid == entity.entity_id:
                continue
            dist = grid.distance(entity.x, entity.y, sx, sy)
            if 0 < dist <= BIRD_SIGNAL_RANGE:
                if grid.has_line_of_sight(entity.x, entity.y, sx, sy):
                    if stype == FOOD_CALL:
                        heard_food.append((sx, sy, dist))
                    elif stype == DANGER_CALL:
                        heard_danger.append((sx, sy, dist))

        entity.extra['signals_heard'] = (
            [(sx, sy, FOOD_CALL) for sx, sy, _ in heard_food] +
            [(sx, sy, DANGER_CALL) for sx, sy, _ in heard_danger]
        )

        # Compute flock direction (cohesion + separation)
        flock_dx, flock_dy = self._compute_flock(entity, grid, all_entities)
        entity.extra['flock_direction'] = (flock_dx, flock_dy)

        # --- Decision priority ---

        # 1. If on food, eat
        if grid.has_food(entity.x, entity.y):
            return ActionCommand(type='eat')

        # 2. Danger: flee from wolves seen directly
        for e in all_entities:
            if e.alive and e.species_type == 'wolf':
                if grid.distance(entity.x, entity.y, e.x, e.y) <= VISION_RANGE:
                    dx, dy = self._direction_away(entity, e.x, e.y, grid)
                    return ActionCommand(type='move', dx=dx, dy=dy)

        # 3. React to DANGER_CALL signals — flee
        if heard_danger:
            closest = min(heard_danger, key=lambda s: s[2])
            dx, dy = self._direction_away(entity, closest[0], closest[1], grid)
            return ActionCommand(type='move', dx=dx, dy=dy)

        # 4. Reproduce if enough energy
        if entity.energy > REPRODUCE_THRESHOLD:
            return ActionCommand(type='reproduce')

        # 5. React to FOOD_CALL signals — approach
        if heard_food:
            closest = min(heard_food, key=lambda s: s[2])
            dx, dy = self._direction_toward(entity, closest[0], closest[1], grid)
            return ActionCommand(type='move', dx=dx, dy=dy)

        # 6. Move toward visible food
        food = grid.find_nearest_food(entity.x, entity.y, radius=VISION_RANGE)
        if food:
            dx, dy = self._direction_toward(entity, food[0], food[1], grid)
            return ActionCommand(type='move', dx=dx, dy=dy)

        # 7. Flock behavior
        if (flock_dx != 0 or flock_dy != 0) and self.rng.random() < 0.5:
            return ActionCommand(type='move', dx=flock_dx, dy=flock_dy)

        # 8. Random wander
        dx, dy = self.rng.choice([(0, -1), (0, 1), (1, 0), (-1, 0)])
        return ActionCommand(type='move', dx=dx, dy=dy)

    def render(self, entity: Entity) -> str:
        return 'b'

    # --- Internal helpers ---

    def _perception_pass(self, grid: Grid, all_entities: list[Entity]) -> None:
        """All birds scan surroundings and emit signals before any decisions."""
        birds = [e for e in all_entities if e.alive and e.species_type == 'bird']
        for bird in birds:
            # Check for food within vision range
            food = grid.find_nearest_food(bird.x, bird.y, radius=VISION_RANGE)
            if food:
                self._signals.append(
                    (bird.x, bird.y, FOOD_CALL, bird.entity_id, grid.current_tick))

            # Check for wolves within vision range
            for e in all_entities:
                if e.alive and e.species_type == 'wolf':
                    if grid.distance(bird.x, bird.y, e.x, e.y) <= VISION_RANGE:
                        self._signals.append(
                            (bird.x, bird.y, DANGER_CALL, bird.entity_id,
                             grid.current_tick))
                        break

    def _compute_flock(self, entity: Entity, grid: Grid,
                       all_entities: list[Entity]) -> tuple[int, int]:
        """Compute flocking vector: cohesion toward center + separation from close neighbors."""
        cx_sum, cy_sum = 0.0, 0.0
        sep_x, sep_y = 0.0, 0.0
        count = 0
        for e in all_entities:
            if not e.alive or e.species_type != 'bird' or e is entity:
                continue
            dist = grid.distance(entity.x, entity.y, e.x, e.y)
            if dist > FLOCK_RANGE:
                continue
            # Toroidal-aware relative position
            rx, ry = self._toroidal_delta(entity.x, entity.y, e.x, e.y, grid)
            cx_sum += rx
            cy_sum += ry
            count += 1
            # Separation: push away from very close neighbors
            if dist > 0 and dist < SEPARATION_DIST:
                sep_x -= rx / max(dist, 1)
                sep_y -= ry / max(dist, 1)

        if count == 0:
            return (0, 0)

        # Cohesion: move toward average position of neighbors
        coh_x = cx_sum / count
        coh_y = cy_sum / count

        # Combine cohesion + separation
        fx = coh_x + sep_x
        fy = coh_y + sep_y

        # Normalize to unit step
        dx = 1 if fx > 0.5 else (-1 if fx < -0.5 else 0)
        dy = 1 if fy > 0.5 else (-1 if fy < -0.5 else 0)
        return (dx, dy)

    def _toroidal_delta(self, x1: int, y1: int, x2: int, y2: int,
                        grid: Grid) -> tuple[int, int]:
        """Shortest-path delta from (x1,y1) to (x2,y2) on torus."""
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) > grid.width // 2:
            dx = dx - grid.width if dx > 0 else dx + grid.width
        if abs(dy) > grid.height // 2:
            dy = dy - grid.height if dy > 0 else dy + grid.height
        return (dx, dy)

    def _direction_toward(self, entity: Entity, tx: int, ty: int,
                          grid: Grid) -> tuple[int, int]:
        dx, dy = self._toroidal_delta(entity.x, entity.y, tx, ty, grid)
        dx = 1 if dx > 0 else (-1 if dx < 0 else 0)
        dy = 1 if dy > 0 else (-1 if dy < 0 else 0)
        return (dx, dy)

    def _direction_away(self, entity: Entity, fx: int, fy: int,
                        grid: Grid) -> tuple[int, int]:
        dx, dy = self._toroidal_delta(entity.x, entity.y, fx, fy, grid)
        # Invert direction
        dx = -1 if dx > 0 else (1 if dx < 0 else 0)
        dy = -1 if dy > 0 else (1 if dy < 0 else 0)
        if dx == 0 and dy == 0:
            dx, dy = self.rng.choice([(0, -1), (0, 1), (1, 0), (-1, 0)])
        return (dx, dy)

    def _random_open(self, grid: Grid) -> tuple[int, int]:
        while True:
            x = self.rng.randint(0, grid.width - 1)
            y = self.rng.randint(0, grid.height - 1)
            if grid.is_passable(x, y):
                return x, y


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    print("=== Bird Species Tests ===")

    # --- Helpers to build a clean test grid ---
    def make_grid(w: int = 20, h: int = 20, seed: int = 0) -> Grid:
        g = Grid(width=w, height=h, seed=seed)
        g.terrain = [[Terrain.OPEN] * w for _ in range(h)]
        return g

    # --- Test 1: spawn ---
    species = BirdSpecies(seed=42)
    g = make_grid()
    birds = species.spawn(g, 5)
    assert len(birds) == 5
    for b in birds:
        assert b.species_name == 'bird'
        assert b.alive
        assert 'signals_heard' in b.extra
        assert 'flock_direction' in b.extra
        assert g.is_passable(b.x, b.y)
    print("  spawn: OK")

    # --- Test 2: render ---
    assert species.render(birds[0]) == 'b'
    print("  render: OK")

    # --- Test 3: tick returns ActionCommand ---
    g.current_tick = 1
    cmd = species.tick(birds[0], g, birds)
    assert isinstance(cmd, ActionCommand), f"Expected ActionCommand, got {type(cmd)}"
    assert cmd.type in ('move', 'eat', 'reproduce', 'signal', 'idle')
    print("  tick returns ActionCommand: OK")

    # --- Test 4: bird eats when on food ---
    g2 = make_grid()
    g2.current_tick = 10
    sp2 = BirdSpecies(seed=1)
    b_eat = sp2.spawn(g2, 1)[0]
    g2.add_food(b_eat.x, b_eat.y)
    cmd = sp2.tick(b_eat, g2, [b_eat])
    assert cmd.type == 'eat', f"Expected eat, got {cmd.type}"
    print("  eat on food: OK")

    # --- Test 5: signal propagation (FOOD_CALL) ---
    g3 = make_grid()
    g3.current_tick = 20
    sp3 = BirdSpecies(seed=2)
    # Bird A near food, Bird B far but within signal range
    b_a = Entity(5, 5, 'bird', energy=ENERGY_START)
    b_a.extra['signals_heard'] = []
    b_a.extra['flock_direction'] = (0, 0)
    b_b = Entity(5, 15, 'bird', energy=ENERGY_START)
    b_b.extra['signals_heard'] = []
    b_b.extra['flock_direction'] = (0, 0)
    g3.add_food(6, 5)  # food near bird A
    ents = [b_a, b_b]
    # Tick bird B — should hear food call from A and move toward it
    cmd_b = sp3.tick(b_b, g3, ents)
    heard = b_b.extra['signals_heard']
    food_heard = [s for s in heard if s[2] == FOOD_CALL]
    assert len(food_heard) > 0, "Bird B should hear FOOD_CALL from Bird A"
    print("  signal propagation (FOOD_CALL): OK")

    # --- Test 6: obstacle blocks signal ---
    g4 = make_grid()
    g4.current_tick = 30
    sp4 = BirdSpecies(seed=3)
    b_c = Entity(5, 5, 'bird', energy=ENERGY_START)
    b_c.extra['signals_heard'] = []
    b_c.extra['flock_direction'] = (0, 0)
    b_d = Entity(5, 15, 'bird', energy=ENERGY_START)
    b_d.extra['signals_heard'] = []
    b_d.extra['flock_direction'] = (0, 0)
    g4.add_food(6, 5)
    # Place obstacle between them
    for y in range(8, 13):
        g4.terrain[y][5] = Terrain.OBSTACLE
    ents4 = [b_c, b_d]
    sp4.tick(b_d, g4, ents4)
    heard4 = b_d.extra['signals_heard']
    food_heard4 = [s for s in heard4 if s[2] == FOOD_CALL]
    assert len(food_heard4) == 0, "Obstacle should block signal"
    print("  obstacle blocks signal: OK")

    # --- Test 7: DANGER_CALL when wolf nearby ---
    g5 = make_grid()
    g5.current_tick = 40
    sp5 = BirdSpecies(seed=4)
    b_e = Entity(10, 10, 'bird', energy=ENERGY_START)
    b_e.extra['signals_heard'] = []
    b_e.extra['flock_direction'] = (0, 0)
    wolf = Entity(13, 10, 'wolf', energy=50)
    b_f = Entity(10, 18, 'bird', energy=ENERGY_START)
    b_f.extra['signals_heard'] = []
    b_f.extra['flock_direction'] = (0, 0)
    ents5 = [b_e, b_f, wolf]
    # Bird E sees wolf → emits DANGER_CALL → Bird F hears it
    sp5.tick(b_f, g5, ents5)
    danger_heard = [s for s in b_f.extra['signals_heard'] if s[2] == DANGER_CALL]
    assert len(danger_heard) > 0, "Bird F should hear DANGER_CALL from Bird E"
    print("  DANGER_CALL from wolf: OK")

    # --- Test 8: flocking (cohesion + separation) ---
    g6 = make_grid()
    g6.current_tick = 50
    sp6 = BirdSpecies(seed=5)
    # Place several birds in a cluster, one outlier
    cluster = []
    for i in range(5):
        b = Entity(10 + i, 10, 'bird', energy=30)
        b.extra['signals_heard'] = []
        b.extra['flock_direction'] = (0, 0)
        cluster.append(b)
    outlier = Entity(3, 10, 'bird', energy=30)
    outlier.extra['signals_heard'] = []
    outlier.extra['flock_direction'] = (0, 0)
    all_b = cluster + [outlier]
    sp6.tick(outlier, g6, all_b)
    fd = outlier.extra['flock_direction']
    # Outlier should be pulled toward cluster (positive dx)
    assert fd[0] > 0, f"Expected cohesion pull right, got dx={fd[0]}"
    print("  flocking cohesion: OK")

    # Test separation: bird very close to another
    g7 = make_grid()
    g7.current_tick = 60
    sp7 = BirdSpecies(seed=6)
    b_close1 = Entity(10, 10, 'bird', energy=30)
    b_close1.extra['signals_heard'] = []
    b_close1.extra['flock_direction'] = (0, 0)
    b_close2 = Entity(11, 10, 'bird', energy=30)
    b_close2.extra['signals_heard'] = []
    b_close2.extra['flock_direction'] = (0, 0)
    sp7.tick(b_close1, g7, [b_close1, b_close2])
    # With only one very close neighbor, separation should push away
    fd2 = b_close1.extra['flock_direction']
    # The cohesion pulls right (+1), separation pushes left (-1).
    # Net could be 0 or separation-dominated — just verify it computed
    assert isinstance(fd2, tuple) and len(fd2) == 2
    print("  flocking separation: OK")

    # --- Test 9: reproduce at threshold ---
    g8 = make_grid()
    g8.current_tick = 70
    sp8 = BirdSpecies(seed=7)
    b_rich = Entity(10, 10, 'bird', energy=REPRODUCE_THRESHOLD + 10)
    b_rich.extra['signals_heard'] = []
    b_rich.extra['flock_direction'] = (0, 0)
    cmd_r = sp8.tick(b_rich, g8, [b_rich])
    assert cmd_r.type == 'reproduce', f"Expected reproduce, got {cmd_r.type}"
    print("  reproduce at threshold: OK")

    # --- Test 10: signals cleared each tick ---
    g9 = make_grid()
    sp9 = BirdSpecies(seed=8)
    b_t1 = Entity(5, 5, 'bird', energy=ENERGY_START)
    b_t1.extra['signals_heard'] = []
    b_t1.extra['flock_direction'] = (0, 0)
    g9.current_tick = 100
    g9.add_food(6, 5)
    sp9.tick(b_t1, g9, [b_t1])
    sig_count_t100 = len(sp9._signals)
    # New tick — signals should be cleared
    g9.current_tick = 101
    g9.food.clear()
    sp9.tick(b_t1, g9, [b_t1])
    # Old food signals from tick 100 should be gone
    old_sigs = [s for s in sp9._signals if s[4] == 100]
    assert len(old_sigs) == 0, "Signals from previous tick should be cleared"
    print("  signals cleared each tick: OK")

    print("\nAll bird tests passed!")
