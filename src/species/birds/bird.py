"""Sonic Birds — communicate via sound signals to coordinate flocking."""

from __future__ import annotations

import random
from src.world.entity import Entity, Species, Action
from src.world.config import SimConfig

SIGNAL_RANGE = 15
SIGNAL_LIFETIME = 3
SIGNAL_COOLDOWN = 5
FLOCK_RADIUS = 5
WOLF_DETECT = 8
OBSTACLE = 1


class BirdSpecies(Species):
    """Birds that emit and receive sound signals for food and danger."""

    def __init__(self) -> None:
        self.signals: list[tuple[int, int, str, int, int]] = []
        self._current_tick: int = 0

    # ── helpers ──────────────────────────────────────────────────────

    def _expire(self, tick: int) -> None:
        self.signals = [s for s in self.signals if tick - s[3] <= SIGNAL_LIFETIME]

    def _emit(self, entity: Entity, sig_type: str, tick: int) -> None:
        entity.extra['last_signal_tick'] = tick
        self.signals.append((entity.x, entity.y, sig_type, tick, entity.id))

    def _can_signal(self, entity: Entity, tick: int) -> bool:
        return tick - entity.extra.get('last_signal_tick', -10) >= SIGNAL_COOLDOWN

    @staticmethod
    def _line_clear(x0: int, y0: int, x1: int, y1: int, grid) -> bool:
        """Simple line-of-sight: step along axis-aligned bresenham, blocked by obstacles."""
        dx = x1 - x0
        dy = y1 - y0
        steps = max(abs(dx), abs(dy))
        if steps == 0:
            return True
        sx = dx / steps
        sy = dy / steps
        cx, cy = float(x0), float(y0)
        for _ in range(steps):
            cx += sx
            cy += sy
            rx, ry = grid.wrap(round(cx), round(cy))
            if grid.terrain[ry][rx] == OBSTACLE:
                return False
        return True

    @staticmethod
    def _manhattan(x0: int, y0: int, x1: int, y1: int, w: int, h: int) -> int:
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        return min(dx, w - dx) + min(dy, h - dy)

    @staticmethod
    def _dir_toward(src: int, dst: int, size: int) -> int:
        diff = dst - src
        if abs(diff) > size // 2:
            diff = -diff
        if diff > 0:
            return 1
        if diff < 0:
            return -1
        return 0

    @staticmethod
    def _clamp(v: int) -> int:
        return max(-1, min(1, round(v)))

    # ── Species interface ────────────────────────────────────────────

    def spawn(self, world, count: int) -> list[Entity]:
        birds: list[Entity] = []
        for _ in range(count):
            for _try in range(200):
                x = random.randint(0, world.config.GRID_WIDTH - 1)
                y = random.randint(0, world.config.GRID_HEIGHT - 1)
                if world.grid.is_passable(x, y):
                    e = Entity('bird', x, y, energy=50.0)
                    e.extra = {'flock_dx': 0, 'flock_dy': 0, 'last_signal_tick': -10}
                    birds.append(e)
                    break
        return birds

    def tick(self, entity: Entity, world) -> Action:
        tick = world.tick_count
        self._current_tick = tick
        grid = world.grid
        w, h = world.config.GRID_WIDTH, world.config.GRID_HEIGHT

        # 1. Expire old signals
        self._expire(tick)

        # 2. Receive signals within range with line-of-sight
        food_sigs: list[tuple[int, int]] = []
        danger_sigs: list[tuple[int, int]] = []
        for sx, sy, stype, _st, _sid in self.signals:
            if self._manhattan(entity.x, entity.y, sx, sy, w, h) > SIGNAL_RANGE:
                continue
            if not self._line_clear(sx, sy, entity.x, entity.y, grid):
                continue
            if stype == 'danger':
                danger_sigs.append((sx, sy))
            else:
                food_sigs.append((sx, sy))

        # 3. Compute signal-based direction
        sig_dx, sig_dy = 0.0, 0.0
        if danger_sigs:
            # Flee: move away from average danger source
            avg_x = sum(s[0] for s in danger_sigs) / len(danger_sigs)
            avg_y = sum(s[1] for s in danger_sigs) / len(danger_sigs)
            sig_dx = -self._dir_toward(entity.x, round(avg_x), w)
            sig_dy = -self._dir_toward(entity.y, round(avg_y), h)
        elif food_sigs:
            avg_x = sum(s[0] for s in food_sigs) / len(food_sigs)
            avg_y = sum(s[1] for s in food_sigs) / len(food_sigs)
            sig_dx = self._dir_toward(entity.x, round(avg_x), w)
            sig_dy = self._dir_toward(entity.y, round(avg_y), h)

        # Flocking: average direction of nearby birds
        flock_dx, flock_dy, flock_n = 0.0, 0.0, 0
        for other in world.entities:
            if other.id == entity.id or other.species_name != 'bird' or not other.alive:
                continue
            if self._manhattan(entity.x, entity.y, other.x, other.y, w, h) <= FLOCK_RADIUS:
                flock_dx += other.extra.get('flock_dx', 0)
                flock_dy += other.extra.get('flock_dy', 0)
                flock_n += 1
        if flock_n:
            flock_dx /= flock_n
            flock_dy /= flock_n

        # Blend: 60% signal + 40% flock
        final_dx = self._clamp(0.6 * sig_dx + 0.4 * flock_dx)
        final_dy = self._clamp(0.6 * sig_dy + 0.4 * flock_dy)

        entity.extra['flock_dx'] = final_dx
        entity.extra['flock_dy'] = final_dy

        # 4. Eat food if on top of it
        if grid.has_food(entity.x, entity.y):
            if self._can_signal(entity, tick):
                self._emit(entity, 'food', tick)
            return Action('eat', dx=0, dy=0)

        # 5. Detect wolves — emit danger, flee
        wolves = [
            e for e in world.entities
            if e.species_name == 'wolf' and e.alive
            and self._manhattan(entity.x, entity.y, e.x, e.y, w, h) <= WOLF_DETECT
        ]
        if wolves:
            if self._can_signal(entity, tick):
                self._emit(entity, 'danger', tick)
            wx = sum(wf.x for wf in wolves) / len(wolves)
            wy = sum(wf.y for wf in wolves) / len(wolves)
            dx = -self._dir_toward(entity.x, round(wx), w)
            dy = -self._dir_toward(entity.y, round(wy), h)
            return Action('move', dx=dx or random.choice([-1, 1]), dy=dy or random.choice([-1, 1]))

        # 7. Reproduction
        if entity.can_reproduce(world.config):
            return Action('reproduce')

        # 6. Move: follow signal/flock direction or wander
        if final_dx or final_dy:
            return Action('move', dx=final_dx, dy=final_dy)
        return Action('move', dx=random.choice([-1, 0, 1]), dy=random.choice([-1, 0, 1]))

    def render(self, entity: Entity) -> str:
        if self._current_tick - entity.extra.get('last_signal_tick', -10) <= 2:
            return 'B'
        return 'b'


