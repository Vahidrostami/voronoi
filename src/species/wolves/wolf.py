"""Predator Wolves species — lone hunters that track prey by scent."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

from src.world.entity import Entity, Species, Action

if TYPE_CHECKING:
    from src.world.config import SimConfig


def _toroidal_dist(x1: int, y1: int, x2: int, y2: int, w: int, h: int) -> float:
    dx = min(abs(x1 - x2), w - abs(x1 - x2))
    dy = min(abs(y1 - y2), h - abs(y1 - y2))
    return math.hypot(dx, dy)


def _toroidal_step(fx: int, fy: int, tx: int, ty: int, w: int, h: int) -> tuple[int, int]:
    """Return (dx, dy) each in {-1, 0, 1} toward target on a toroidal grid."""
    def _best(f: int, t: int, size: int) -> int:
        diff = (t - f) % size
        return -1 if diff > size // 2 else (1 if diff > 0 else 0)
    return _best(fx, tx, w), _best(fy, ty, h)


class WolfSpecies(Species):
    """Lone predator hunters. Track prey via scent trails. Starve after 50 ticks."""

    def spawn(self, world, count: int) -> list[Entity]:
        entities: list[Entity] = []
        w, h = world.config.GRID_WIDTH, world.config.GRID_HEIGHT
        for _ in range(count):
            for _ in range(200):
                x, y = random.randint(0, w - 1), random.randint(0, h - 1)
                if world.grid.is_passable(x, y):
                    break
            e = Entity("wolf", x, y, energy=50.0)
            e.extra = {"ticks_since_eaten": 0, "tracking": None, "hunt_target_id": None}
            entities.append(e)
        return entities

    def tick(self, entity: Entity, world) -> Action:
        cfg = world.config
        w, h = cfg.GRID_WIDTH, cfg.GRID_HEIGHT
        extra = entity.extra

        # 1. Starvation check
        extra["ticks_since_eaten"] = extra.get("ticks_since_eaten", 0) + 1
        if extra["ticks_since_eaten"] >= cfg.WOLF_STARVATION_TICKS:
            entity.alive = False
            return Action("idle", 0, 0, None)

        # 2. Scan for prey within radius 5
        prey_list = []
        for e in world.entities:
            if e is entity or not e.alive or e.species_name == "wolf":
                continue
            d = _toroidal_dist(entity.x, entity.y, e.x, e.y, w, h)
            if d <= 5:
                prey_list.append((d, e))

        if prey_list:
            prey_list.sort(key=lambda t: t[0])
            dist, prey = prey_list[0]

            # Adjacent — kill and eat
            if dist <= 1.0:
                prey.alive = False
                prey.energy = 0
                extra["ticks_since_eaten"] = 0
                extra["hunt_target_id"] = None
                entity.eat(cfg.ENERGY_PER_FOOD)
                self._maybe_reproduce(entity, world)
                return Action("eat", 0, 0, {"prey_id": prey.id})

            # Chase closest prey (world handles the actual move)
            dx, dy = _toroidal_step(entity.x, entity.y, prey.x, prey.y, w, h)
            extra["hunt_target_id"] = prey.id
            return Action("move", dx, dy, None)

        # 3. Follow scent trails (radius 3)
        scent_trails = getattr(world, "scent_trails", {})
        best_scent = None
        best_tick = -1
        ex, ey = entity.x, entity.y
        for sx in range(-3, 4):
            for sy in range(-3, 4):
                cx, cy = (ex + sx) % w, (ey + sy) % h
                for species_name, tick_num in scent_trails.get((cx, cy), []):
                    if species_name != "wolf" and tick_num > best_tick:
                        best_tick = tick_num
                        best_scent = (cx, cy)

        if best_scent is not None:
            dx, dy = _toroidal_step(ex, ey, best_scent[0], best_scent[1], w, h)
            return Action("move", dx, dy, {"tracking_scent": True})

        # 4. Random movement
        dx, dy = random.choice([(0, 1), (0, -1), (1, 0), (-1, 0)])
        return Action("move", dx, dy, None)

    def render(self, entity: Entity) -> str:
        return "W"

    # --- helpers ---

    def _maybe_reproduce(self, entity: Entity, world) -> None:
        extra = entity.extra
        if entity.energy > world.config.REPRODUCE_THRESHOLD and extra.get("ticks_since_eaten", 50) < 25:
            entity.energy -= world.config.REPRODUCE_COST
            w, h = world.config.GRID_WIDTH, world.config.GRID_HEIGHT
            for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                nx, ny = (entity.x + dx) % w, (entity.y + dy) % h
                if world.grid.is_passable(nx, ny):
                    child = Entity("wolf", nx, ny, energy=50.0)
                    child.extra = {"ticks_since_eaten": 0, "tracking": None, "hunt_target_id": None}
                    world.entities.append(child)
                    return
