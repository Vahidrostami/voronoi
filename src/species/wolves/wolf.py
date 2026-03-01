"""Predator Wolves — lone hunters that track prey by scent."""

import random
from src.world.entity import Entity, Species, Action, ActionCommand, DIRECTION_DELTAS
from src.world.grid import Grid
from src.world.config import (
    GRID_WIDTH, GRID_HEIGHT, ENERGY_LOSS_PER_TICK,
    REPRODUCE_THRESHOLD, REPRODUCE_COST,
    WOLF_HUNGER_LIMIT, WOLF_HUNT_ENERGY, WOLF_SCENT_RANGE,
    WOLF_SPEED, INITIAL_WOLVES, ENERGY_START,
)


class WolfSpecies(Species):
    """Lone-hunter wolves that track prey by scent trails.

    Must eat every WOLF_HUNGER_LIMIT ticks or starve. Hunts any non-wolf
    entity on the same cell. Does NOT eat plant food. Ignores other wolves.
    """

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def spawn(self, grid: Grid, count: int) -> list[Entity]:
        entities: list[Entity] = []
        for _ in range(count):
            x, y = self._random_open(grid)
            e = Entity(x, y, 'wolf', energy=ENERGY_START)
            e.extra['ticks_since_last_meal'] = 0
            e.extra['current_target'] = None
            e.extra['hunting'] = False
            entities.append(e)
        return entities

    def tick(self, entity: Entity, grid: Grid,
             all_entities: list[Entity]) -> ActionCommand:
        # Ensure extra fields exist
        entity.extra.setdefault('ticks_since_last_meal', 0)
        entity.extra.setdefault('current_target', None)
        entity.extra.setdefault('hunting', False)

        entity.extra['ticks_since_last_meal'] += 1

        # Starvation: die if too many ticks without food
        if entity.extra['ticks_since_last_meal'] > WOLF_HUNGER_LIMIT:
            entity.alive = False
            return ActionCommand(type='idle')

        # Hunt: kill prey sharing same cell (any non-wolf entity)
        prey_here = [
            e for e in all_entities
            if e.alive and e.species_name != 'wolf'
            and e.x == entity.x and e.y == entity.y
        ]
        if prey_here:
            victim = prey_here[0]
            victim.alive = False
            entity.energy += WOLF_HUNT_ENERGY
            entity.extra['ticks_since_last_meal'] = 0
            entity.extra['hunting'] = False
            entity.extra['current_target'] = None
            return ActionCommand(type='idle')  # eating consumes the turn

        # Reproduce when energy exceeds threshold
        if entity.energy > REPRODUCE_THRESHOLD:
            entity.energy -= REPRODUCE_COST
            return ActionCommand(type='reproduce')

        # Chase visible prey within scent range * 2
        detection_range = WOLF_SCENT_RANGE * 2
        nearest_prey = None
        nearest_dist = detection_range + 1
        for e in all_entities:
            if e.alive and e.species_name != 'wolf':
                d = grid.distance(entity.x, entity.y, e.x, e.y)
                if d < nearest_dist:
                    nearest_prey = e
                    nearest_dist = d

        if nearest_prey and nearest_dist <= detection_range:
            entity.extra['hunting'] = True
            entity.extra['current_target'] = (nearest_prey.x, nearest_prey.y)
            dx, dy = self._direction_toward(
                entity.x, entity.y, nearest_prey.x, nearest_prey.y, grid)
            return ActionCommand(type='move',
                                 dx=dx * WOLF_SPEED, dy=dy * WOLF_SPEED)

        # Follow strongest scent trail within WOLF_SCENT_RANGE
        best_pos = None
        best_score = 0.0
        neighbors = grid.get_neighbors(entity.x, entity.y,
                                        radius=WOLF_SCENT_RANGE)
        for nx, ny in neighbors:
            scents = grid.get_scent(nx, ny, max_age=20)
            prey_scents = [(s, t) for s, t in scents if s != 'wolf']
            if prey_scents:
                score = sum(
                    1.0 / (grid.current_tick - t + 1) for _, t in prey_scents)
                if score > best_score:
                    best_score = score
                    best_pos = (nx, ny)

        if best_pos:
            entity.extra['hunting'] = True
            entity.extra['current_target'] = best_pos
            dx, dy = self._direction_toward(
                entity.x, entity.y, best_pos[0], best_pos[1], grid)
            return ActionCommand(type='move',
                                 dx=dx * WOLF_SPEED, dy=dy * WOLF_SPEED)

        # No prey or scent — random walk preferring unexplored areas
        entity.extra['hunting'] = False
        entity.extra['current_target'] = None
        dx, dy = self._random_wander(entity, grid)
        return ActionCommand(type='move', dx=dx, dy=dy)

    def render(self, entity: Entity) -> str:
        return 'W'

    # --- helpers --------------------------------------------------------

    def _random_open(self, grid: Grid) -> tuple[int, int]:
        """Find a random passable cell."""
        while True:
            x = self.rng.randint(0, grid.width - 1)
            y = self.rng.randint(0, grid.height - 1)
            if grid.is_passable(x, y):
                return x, y

    def _direction_toward(self, fx: int, fy: int, tx: int, ty: int,
                          grid: Grid) -> tuple[int, int]:
        """Unit direction from (fx,fy) toward (tx,ty) on torus."""
        dx = tx - fx
        dy = ty - fy
        if abs(dx) > grid.width // 2:
            dx = -1 if dx > 0 else 1
        else:
            dx = 1 if dx > 0 else (-1 if dx < 0 else 0)
        if abs(dy) > grid.height // 2:
            dy = -1 if dy > 0 else 1
        else:
            dy = 1 if dy > 0 else (-1 if dy < 0 else 0)
        return dx, dy

    def _random_wander(self, entity: Entity,
                       grid: Grid) -> tuple[int, int]:
        """Random walk biased toward cells without recent wolf scent."""
        candidates: list[tuple[int, int]] = []
        for ddx in range(-WOLF_SPEED, WOLF_SPEED + 1):
            for ddy in range(-WOLF_SPEED, WOLF_SPEED + 1):
                if ddx == 0 and ddy == 0:
                    continue
                if max(abs(ddx), abs(ddy)) > WOLF_SPEED:
                    continue
                nx, ny = grid.wrap(entity.x + ddx, entity.y + ddy)
                if grid.is_passable(nx, ny):
                    scents = grid.get_scent(nx, ny, max_age=20)
                    has_wolf = any(s == 'wolf' for s, _ in scents)
                    weight = 1 if has_wolf else 3
                    candidates.extend([(ddx, ddy)] * weight)
        if candidates:
            return self.rng.choice(candidates)
        return (self.rng.choice([-WOLF_SPEED, WOLF_SPEED]),
                self.rng.choice([-WOLF_SPEED, WOLF_SPEED]))


# ── Tests ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys, os
    # Ensure project root is on path when run directly
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

    from src.world.entity import Entity, ActionCommand
    from src.world.grid import Grid
    from src.world.config import (
        WOLF_HUNGER_LIMIT, WOLF_HUNT_ENERGY, REPRODUCE_THRESHOLD,
        WOLF_SCENT_RANGE, WOLF_SPEED, ENERGY_START,
    )

    print("=== Wolf Species Tests ===")

    # --- helper: build a small open grid ---
    def make_grid(w=20, h=20, seed=0):
        g = Grid(width=w, height=h, seed=seed)
        g.terrain = [[0] * w for _ in range(h)]  # all open
        g.current_tick = 0
        return g

    ws = WolfSpecies(seed=42)

    # 1. Spawn
    g = make_grid()
    wolves = ws.spawn(g, 5)
    assert len(wolves) == 5
    for w in wolves:
        assert w.species_name == 'wolf'
        assert w.extra['ticks_since_last_meal'] == 0
        assert w.extra['current_target'] is None
        assert w.extra['hunting'] is False
        assert w.energy == ENERGY_START
    print("  spawn: OK")

    # 2. Render
    assert ws.render(wolves[0]) == 'W'
    print("  render: OK")

    # 3. Hunger starvation
    g = make_grid()
    g.current_tick = 10
    wolf = Entity(5, 5, 'wolf', energy=100)
    # At limit-1, tick increments to limit which is NOT > limit => survives
    wolf.extra['ticks_since_last_meal'] = WOLF_HUNGER_LIMIT - 1
    cmd = ws.tick(wolf, g, [wolf])
    assert wolf.alive is True, "should survive at exactly the limit"

    # At limit, tick increments to limit+1 which IS > limit => dies
    wolf2 = Entity(5, 5, 'wolf', energy=100)
    wolf2.extra['ticks_since_last_meal'] = WOLF_HUNGER_LIMIT
    cmd = ws.tick(wolf2, g, [wolf2])
    assert wolf2.alive is False, "should die past the limit"
    assert cmd.type == 'idle'
    print("  hunger death: OK")

    # 4. Hunting — prey on same cell
    g = make_grid()
    g.current_tick = 10
    wolf = Entity(5, 5, 'wolf', energy=30)
    wolf.extra['ticks_since_last_meal'] = 10
    prey = Entity(5, 5, 'ant', energy=20)
    cmd = ws.tick(wolf, g, [wolf, prey])
    assert prey.alive is False, "prey should be dead"
    assert wolf.energy == 30 + WOLF_HUNT_ENERGY
    assert wolf.extra['ticks_since_last_meal'] == 0
    assert cmd.type == 'idle'
    print("  hunt kill: OK")

    # 5. Wolves do NOT eat other wolves
    g = make_grid()
    g.current_tick = 10
    wolf1 = Entity(5, 5, 'wolf', energy=30)
    wolf1.extra['ticks_since_last_meal'] = 5
    wolf2 = Entity(5, 5, 'wolf', energy=30)
    wolf2.extra['ticks_since_last_meal'] = 5
    cmd = ws.tick(wolf1, g, [wolf1, wolf2])
    assert wolf2.alive is True, "wolves should not eat each other"
    print("  no cannibalism: OK")

    # 6. Scent tracking — move toward prey scent
    g = make_grid()
    g.current_tick = 50
    g.record_trail(8, 5, 'ant')  # prey scent nearby
    wolf = Entity(5, 5, 'wolf', energy=40)
    wolf.extra['ticks_since_last_meal'] = 5
    cmd = ws.tick(wolf, g, [wolf])
    assert cmd.type == 'move'
    assert cmd.dx > 0, "should move toward scent (east)"
    assert wolf.extra['hunting'] is True
    print("  scent tracking: OK")

    # 7. Old scent ignored
    g = make_grid()
    g.current_tick = 100
    g.trails[(8, 5)] = [('ant', 50)]  # scent from 50 ticks ago (>20 max_age)
    wolf = Entity(5, 5, 'wolf', energy=40)
    wolf.extra['ticks_since_last_meal'] = 5
    cmd = ws.tick(wolf, g, [wolf])
    assert cmd.type == 'move'
    assert wolf.extra['hunting'] is False, "old scent should be ignored"
    print("  old scent ignored: OK")

    # 8. Reproduce when energy > threshold
    g = make_grid()
    g.current_tick = 10
    wolf = Entity(5, 5, 'wolf', energy=REPRODUCE_THRESHOLD + 10)
    wolf.extra['ticks_since_last_meal'] = 2
    cmd = ws.tick(wolf, g, [wolf])
    assert cmd.type == 'reproduce'
    print("  reproduce: OK")

    # 9. Movement speed — dx/dy magnitude matches WOLF_SPEED
    g = make_grid(w=50, h=50)
    g.current_tick = 10
    wolf = Entity(10, 10, 'wolf', energy=40)
    wolf.extra['ticks_since_last_meal'] = 5
    prey = Entity(20, 10, 'ant', energy=10)
    cmd = ws.tick(wolf, g, [wolf, prey])
    assert cmd.type == 'move'
    assert abs(cmd.dx) == WOLF_SPEED, f"dx should be ±{WOLF_SPEED}, got {cmd.dx}"
    print("  wolf speed: OK")

    # 10. Random wander when no targets
    g = make_grid()
    g.current_tick = 10
    wolf = Entity(10, 10, 'wolf', energy=40)
    wolf.extra['ticks_since_last_meal'] = 5
    cmd = ws.tick(wolf, g, [wolf])
    assert cmd.type == 'move'
    assert abs(cmd.dx) <= WOLF_SPEED and abs(cmd.dy) <= WOLF_SPEED
    print("  random wander: OK")

    # 11. tick returns ActionCommand
    assert isinstance(cmd, ActionCommand)
    print("  returns ActionCommand: OK")

    # 12. Hunts any non-wolf species (not just predefined set)
    g = make_grid()
    g.current_tick = 10
    wolf = Entity(5, 5, 'wolf', energy=30)
    wolf.extra['ticks_since_last_meal'] = 10
    alien = Entity(5, 5, 'alien_creature', energy=20)
    cmd = ws.tick(wolf, g, [wolf, alien])
    assert alien.alive is False, "should hunt any non-wolf"
    print("  hunts any species: OK")

    print("\nAll wolf tests passed!")
