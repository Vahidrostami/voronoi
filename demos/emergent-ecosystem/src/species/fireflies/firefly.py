"""Visual Fireflies — flash light patterns to signal food or danger.

Flash patterns:
  DOUBLE_FLASH (food):  2 ticks on, 1 off, 2 on  → attracts nearby fireflies
  RAPID_FLASH (danger): 1 on, 1 off, repeated     → causes nearby fireflies to flee

Visibility is limited to FIREFLY_FLASH_RANGE cells with line-of-sight checks
(blocked by OBSTACLE terrain).
"""

import random
from src.world.entity import Entity, Species, Action, ActionCommand, DIRECTION_DELTAS
from src.world.grid import Grid, Terrain
from src.world.config import (
    GRID_WIDTH, GRID_HEIGHT, ENERGY_PER_FOOD, ENERGY_LOSS_PER_TICK,
    REPRODUCE_THRESHOLD, REPRODUCE_COST, FIREFLY_FLASH_RANGE,
    INITIAL_FIREFLIES, ENERGY_START,
)

# Flash pattern definitions: sequence of booleans (True = light ON)
DOUBLE_FLASH = [True, True, False, True, True]  # food signal
RAPID_FLASH = [True, False, True, False]         # danger signal

FLASH_PATTERNS: dict[str, list[bool]] = {
    'DOUBLE_FLASH': DOUBLE_FLASH,
    'RAPID_FLASH': RAPID_FLASH,
}

DETECTION_RANGE = 6  # range for spotting food / wolves directly


class FireflySpecies(Species):
    """Fireflies communicate via light flashes, blocked by obstacles (line-of-sight)."""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        # Shared flash registry: entity_id -> flash state dict
        self._flash_registry: dict[int, dict] = {}

    # ------------------------------------------------------------------
    # Species interface
    # ------------------------------------------------------------------

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        self._flash_registry.clear()
        entities: list[Entity] = []
        for _ in range(count):
            x, y = self._random_open(grid)
            e = Entity(x, y, 'firefly', energy=ENERGY_START)
            e.extra['flash_pattern'] = None
            e.extra['flash_tick'] = 0
            e.extra['is_flashing'] = False
            entities.append(e)
        return entities

    def tick(self, entity: Entity, grid: Grid,
             all_entities: list[Entity]) -> ActionCommand:
        # Advance any in-progress flash pattern for this entity
        self._advance_flash(entity)

        # --- Detect wolves within DETECTION_RANGE → RAPID_FLASH + flee ---
        for e in all_entities:
            if e.alive and e.species_type == 'wolf':
                if grid.distance(entity.x, entity.y, e.x, e.y) <= DETECTION_RANGE:
                    self._start_flash(entity, 'RAPID_FLASH')
                    dx, dy = self._flee_delta(entity, e.x, e.y, grid)
                    return ActionCommand(type='move', dx=dx, dy=dy)

        # --- On food → eat + DOUBLE_FLASH ---
        if grid.has_food(entity.x, entity.y):
            self._start_flash(entity, 'DOUBLE_FLASH')
            return ActionCommand(type='eat')

        # --- Spot food within DETECTION_RANGE → DOUBLE_FLASH + approach ---
        food = grid.find_nearest_food(entity.x, entity.y, radius=DETECTION_RANGE)
        if food:
            self._start_flash(entity, 'DOUBLE_FLASH')
            dx, dy = self._toward_delta(entity, food[0], food[1], grid)
            return ActionCommand(type='move', dx=dx, dy=dy)

        # --- Reproduce ---
        if entity.energy > REPRODUCE_THRESHOLD:
            return ActionCommand(type='reproduce')

        # --- React to visible flashes from other fireflies ---
        food_signals: list[tuple[int, int, int]] = []
        danger_signals: list[tuple[int, int, int]] = []
        for eid, fstate in self._flash_registry.items():
            if eid == entity.entity_id:
                continue
            if not fstate.get('is_on', False):
                continue
            fx, fy = fstate['x'], fstate['y']
            dist = grid.distance(entity.x, entity.y, fx, fy)
            if 0 < dist <= FIREFLY_FLASH_RANGE:
                if grid.has_line_of_sight(entity.x, entity.y, fx, fy):
                    if fstate['pattern'] == 'DOUBLE_FLASH':
                        food_signals.append((fx, fy, dist))
                    elif fstate['pattern'] == 'RAPID_FLASH':
                        danger_signals.append((fx, fy, dist))

        if danger_signals:
            closest = min(danger_signals, key=lambda s: s[2])
            dx, dy = self._flee_delta(entity, closest[0], closest[1], grid)
            return ActionCommand(type='move', dx=dx, dy=dy)

        if food_signals:
            closest = min(food_signals, key=lambda s: s[2])
            dx, dy = self._toward_delta(entity, closest[0], closest[1], grid)
            return ActionCommand(type='move', dx=dx, dy=dy)

        # --- Wander ---
        action = self.rng.choice(
            [Action.MOVE_N, Action.MOVE_S, Action.MOVE_E, Action.MOVE_W])
        dx, dy = DIRECTION_DELTAS[action]
        return ActionCommand(type='move', dx=dx, dy=dy)

    def render(self, entity: Entity) -> str:
        return 'F' if entity.extra.get('is_flashing', False) else 'f'

    # ------------------------------------------------------------------
    # Flash-pattern state machine
    # ------------------------------------------------------------------

    def _start_flash(self, entity: Entity, pattern_name: str) -> None:
        """Begin a flash pattern (no-op if already flashing)."""
        if entity.extra.get('flash_pattern') is not None:
            return
        pattern = FLASH_PATTERNS[pattern_name]
        entity.extra['flash_pattern'] = pattern_name
        entity.extra['flash_tick'] = 0
        entity.extra['is_flashing'] = pattern[0]
        self._flash_registry[entity.entity_id] = {
            'pattern': pattern_name,
            'flash_tick': 0,
            'x': entity.x,
            'y': entity.y,
            'is_on': pattern[0],
        }

    def _advance_flash(self, entity: Entity) -> None:
        """Advance the entity's flash pattern by one tick."""
        pattern_name = entity.extra.get('flash_pattern')
        if pattern_name is None:
            entity.extra['is_flashing'] = False
            return
        pattern = FLASH_PATTERNS[pattern_name]
        tick = entity.extra['flash_tick'] + 1
        if tick >= len(pattern):
            # Pattern complete
            entity.extra['flash_pattern'] = None
            entity.extra['flash_tick'] = 0
            entity.extra['is_flashing'] = False
            self._flash_registry.pop(entity.entity_id, None)
        else:
            entity.extra['flash_tick'] = tick
            entity.extra['is_flashing'] = pattern[tick]
            if entity.entity_id in self._flash_registry:
                self._flash_registry[entity.entity_id].update({
                    'flash_tick': tick,
                    'x': entity.x,
                    'y': entity.y,
                    'is_on': pattern[tick],
                })

    # ------------------------------------------------------------------
    # Movement helpers
    # ------------------------------------------------------------------

    def _toward_delta(self, entity: Entity, tx: int, ty: int,
                      grid: Grid) -> tuple[int, int]:
        dx = tx - entity.x
        dy = ty - entity.y
        if abs(dx) > grid.width // 2:
            dx = -1 if dx > 0 else 1
        else:
            dx = 1 if dx > 0 else (-1 if dx < 0 else 0)
        if abs(dy) > grid.height // 2:
            dy = -1 if dy > 0 else 1
        else:
            dy = 1 if dy > 0 else (-1 if dy < 0 else 0)
        return dx, dy

    def _flee_delta(self, entity: Entity, fx: int, fy: int,
                    grid: Grid) -> tuple[int, int]:
        dx = entity.x - fx
        dy = entity.y - fy
        if abs(dx) > grid.width // 2:
            dx = -dx
        if abs(dy) > grid.height // 2:
            dy = -dy
        dx = 1 if dx > 0 else (-1 if dx < 0 else 0)
        dy = 1 if dy > 0 else (-1 if dy < 0 else 0)
        if dx == 0 and dy == 0:
            return self.rng.choice([(0, -1), (0, 1), (1, 0), (-1, 0)])
        return dx, dy

    def _random_open(self, grid: Grid) -> tuple[int, int]:
        while True:
            x = self.rng.randint(0, grid.width - 1)
            y = self.rng.randint(0, grid.height - 1)
            if grid.is_passable(x, y):
                return x, y


# ======================================================================
# Tests
# ======================================================================
if __name__ == '__main__':
    from src.world.grid import Grid, Terrain
    from src.world.entity import Entity, ActionCommand

    def _make_grid(w: int = 20, h: int = 20) -> Grid:
        """Small all-open grid for deterministic tests."""
        g = Grid(width=w, height=h, seed=0)
        g.terrain = [[Terrain.OPEN] * w for _ in range(h)]
        g.current_tick = 0
        return g

    print("=== Firefly Tests ===")

    # ---- 1. Flash pattern sequences ----
    species = FireflySpecies(seed=1)
    grid = _make_grid()
    e = Entity(5, 5, 'firefly', energy=50)
    e.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)

    # Start DOUBLE_FLASH
    species._start_flash(e, 'DOUBLE_FLASH')
    assert e.extra['flash_pattern'] == 'DOUBLE_FLASH'
    assert e.extra['flash_tick'] == 0
    assert e.extra['is_flashing'] is True  # tick 0: ON

    # Advance through pattern: [True, True, False, True, True]
    expected = [True, False, True, True]  # ticks 1-4
    for i, exp in enumerate(expected):
        species._advance_flash(e)
        assert e.extra['is_flashing'] is exp, \
            f"DOUBLE_FLASH tick {i+1}: expected {exp}, got {e.extra['is_flashing']}"

    # After tick 4, next advance should clear the pattern
    species._advance_flash(e)
    assert e.extra['flash_pattern'] is None
    assert e.extra['is_flashing'] is False
    print("  DOUBLE_FLASH pattern: OK")

    # Start RAPID_FLASH
    species._start_flash(e, 'RAPID_FLASH')
    assert e.extra['is_flashing'] is True  # tick 0: ON
    expected_rapid = [False, True, False]  # ticks 1-3
    for i, exp in enumerate(expected_rapid):
        species._advance_flash(e)
        assert e.extra['is_flashing'] is exp, \
            f"RAPID_FLASH tick {i+1}: expected {exp}, got {e.extra['is_flashing']}"
    species._advance_flash(e)
    assert e.extra['flash_pattern'] is None
    print("  RAPID_FLASH pattern: OK")

    # ---- 2. Render char ----
    e.extra['is_flashing'] = False
    assert species.render(e) == 'f'
    e.extra['is_flashing'] = True
    assert species.render(e) == 'F'
    e.extra['is_flashing'] = False
    print("  Render char (f/F): OK")

    # ---- 3. Flash registry ----
    species._flash_registry.clear()
    e.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)
    species._start_flash(e, 'DOUBLE_FLASH')
    assert e.entity_id in species._flash_registry
    reg = species._flash_registry[e.entity_id]
    assert reg['pattern'] == 'DOUBLE_FLASH'
    assert reg['is_on'] is True
    assert reg['x'] == e.x and reg['y'] == e.y

    # Advance — tick 1 still ON
    species._advance_flash(e)
    assert species._flash_registry[e.entity_id]['is_on'] is True

    # Advance — tick 2 OFF
    species._advance_flash(e)
    assert species._flash_registry[e.entity_id]['is_on'] is False

    # Finish pattern
    species._advance_flash(e)  # tick 3 ON
    species._advance_flash(e)  # tick 4 ON
    species._advance_flash(e)  # done
    assert e.entity_id not in species._flash_registry
    print("  Flash registry lifecycle: OK")

    # ---- 4. Line-of-sight signaling ----
    grid2 = _make_grid()
    species2 = FireflySpecies(seed=2)

    emitter = Entity(3, 5, 'firefly', energy=50)
    emitter.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)
    observer = Entity(8, 5, 'firefly', energy=50)
    observer.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)

    # Emitter starts flashing food signal
    species2._start_flash(emitter, 'DOUBLE_FLASH')
    assert emitter.entity_id in species2._flash_registry

    # Observer should see flash (no obstacles, within range)
    fstate = species2._flash_registry[emitter.entity_id]
    dist = grid2.distance(observer.x, observer.y, fstate['x'], fstate['y'])
    has_los = grid2.has_line_of_sight(observer.x, observer.y, fstate['x'], fstate['y'])
    assert dist <= FIREFLY_FLASH_RANGE
    assert has_los is True

    # Place obstacle between them
    grid2.terrain[5][5] = Terrain.OBSTACLE
    has_los_blocked = grid2.has_line_of_sight(observer.x, observer.y, fstate['x'], fstate['y'])
    assert has_los_blocked is False
    grid2.terrain[5][5] = Terrain.OPEN  # restore
    print("  Line-of-sight flash visibility: OK")

    # ---- 5. Response to food flash (DOUBLE_FLASH → move toward) ----
    grid3 = _make_grid()
    species3 = FireflySpecies(seed=3)

    src_e = Entity(3, 5, 'firefly', energy=50)
    src_e.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)
    resp_e = Entity(8, 5, 'firefly', energy=50)
    resp_e.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)

    species3._start_flash(src_e, 'DOUBLE_FLASH')
    cmd = species3.tick(resp_e, grid3, [src_e, resp_e])
    assert isinstance(cmd, ActionCommand)
    assert cmd.type == 'move'
    assert cmd.dx == -1, f"Expected dx=-1 (toward x=3), got {cmd.dx}"
    print("  Response to DOUBLE_FLASH (move toward): OK")

    # ---- 6. Response to danger flash (RAPID_FLASH → flee) ----
    grid4 = _make_grid()
    species4 = FireflySpecies(seed=4)

    danger_src = Entity(3, 5, 'firefly', energy=50)
    danger_src.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)
    flee_e = Entity(8, 5, 'firefly', energy=50)
    flee_e.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)

    species4._start_flash(danger_src, 'RAPID_FLASH')
    cmd = species4.tick(flee_e, grid4, [danger_src, flee_e])
    assert isinstance(cmd, ActionCommand)
    assert cmd.type == 'move'
    assert cmd.dx == 1, f"Expected dx=1 (flee from x=3), got {cmd.dx}"
    print("  Response to RAPID_FLASH (flee): OK")

    # ---- 7. Wolf detection triggers RAPID_FLASH ----
    grid5 = _make_grid()
    species5 = FireflySpecies(seed=5)

    ff = Entity(5, 5, 'firefly', energy=50)
    ff.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)
    wolf = Entity(8, 5, 'wolf', energy=50)

    cmd = species5.tick(ff, grid5, [ff, wolf])
    assert cmd.type == 'move'
    assert ff.extra['flash_pattern'] == 'RAPID_FLASH'
    assert ff.extra['is_flashing'] is True
    print("  Wolf detection → RAPID_FLASH: OK")

    # ---- 8. Food detection triggers DOUBLE_FLASH ----
    grid6 = _make_grid()
    species6 = FireflySpecies(seed=6)

    ff2 = Entity(5, 5, 'firefly', energy=50)
    ff2.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)
    grid6.add_food(7, 5)

    cmd = species6.tick(ff2, grid6, [ff2])
    assert ff2.extra['flash_pattern'] == 'DOUBLE_FLASH'
    assert ff2.extra['is_flashing'] is True
    print("  Food detection → DOUBLE_FLASH: OK")

    # ---- 9. Eating returns eat command ----
    grid7 = _make_grid()
    species7 = FireflySpecies(seed=7)

    ff3 = Entity(5, 5, 'firefly', energy=50)
    ff3.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)
    grid7.add_food(5, 5)

    cmd = species7.tick(ff3, grid7, [ff3])
    assert cmd.type == 'eat'
    print("  Eating on food cell: OK")

    # ---- 10. Reproduce when energy high ----
    grid8 = _make_grid()
    species8 = FireflySpecies(seed=8)

    ff4 = Entity(5, 5, 'firefly', energy=REPRODUCE_THRESHOLD + 1)
    ff4.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)

    cmd = species8.tick(ff4, grid8, [ff4])
    assert cmd.type == 'reproduce'
    print("  Reproduce at high energy: OK")

    # ---- 11. Spawn creates correct entities ----
    grid9 = _make_grid()
    species9 = FireflySpecies(seed=9)
    spawned = species9.spawn(grid9, 5)
    assert len(spawned) == 5
    for s in spawned:
        assert s.species_name == 'firefly'
        assert s.energy == ENERGY_START
        assert s.extra['flash_pattern'] is None
        assert s.extra['flash_tick'] == 0
        assert s.extra['is_flashing'] is False
        assert grid9.is_passable(s.x, s.y)
    print("  Spawn: OK")

    # ---- 12. No-op when already flashing ----
    species10 = FireflySpecies(seed=10)
    e10 = Entity(5, 5, 'firefly', energy=50)
    e10.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)
    species10._start_flash(e10, 'DOUBLE_FLASH')
    species10._start_flash(e10, 'RAPID_FLASH')  # should be ignored
    assert e10.extra['flash_pattern'] == 'DOUBLE_FLASH'
    print("  No interrupt of active flash: OK")

    # ---- 13. LOS blocked → flash not visible to observer ----
    grid11 = _make_grid()
    species11 = FireflySpecies(seed=11)

    src11 = Entity(3, 5, 'firefly', energy=50)
    src11.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)
    obs11 = Entity(8, 5, 'firefly', energy=50)
    obs11.extra.update(flash_pattern=None, flash_tick=0, is_flashing=False)

    species11._start_flash(src11, 'DOUBLE_FLASH')
    grid11.terrain[5][5] = Terrain.OBSTACLE  # block LOS

    cmd = species11.tick(obs11, grid11, [src11, obs11])
    # Observer should NOT move toward source (LOS blocked) → random wander
    assert cmd.type == 'move'
    # The observer should not have started a flash pattern (no direct stimulus)
    assert obs11.extra['flash_pattern'] is None
    print("  LOS blocked prevents flash reception: OK")

    print("\nAll firefly tests passed!")
