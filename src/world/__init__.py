"""World engine — ties grid, entities, and species together."""
from __future__ import annotations
import random
from .config import SimConfig
from .grid import Grid
from .entity import Entity, Action, Species


class World:
    def __init__(self, config: SimConfig | None = None):
        self.config = config or SimConfig()
        self.grid = Grid(self.config)
        self.entities: list[Entity] = []
        self.species_handlers: dict[str, Species] = {}
        self.tick_count: int = 0
        self.scent_trails: dict[tuple[int, int], list[tuple[str, int]]] = {}

    def register_species(self, name: str, handler: Species) -> None:
        self.species_handlers[name] = handler

    def spawn_all(self) -> None:
        for name, handler in self.species_handlers.items():
            count_attr = f"INITIAL_{name.upper()}"
            count = getattr(self.config, count_attr, 0)
            if count > 0:
                new_entities = handler.spawn(self, count)
                self.entities.extend(new_entities)

    def tick(self) -> None:
        self.tick_count += 1
        random.shuffle(self.entities)

        for entity in self.entities:
            if not entity.is_alive():
                continue
            handler = self.species_handlers.get(entity.species_name)
            if handler is None:
                continue
            action = handler.tick(entity, self)
            self.process_action(entity, action)
            entity.lose_energy(self.config.ENERGY_LOSS_PER_TICK)

        for _ in range(self.config.FOOD_SPAWN_RATE):
            self.grid.spawn_food()

        self.entities = [e for e in self.entities if e.is_alive()]

    def process_action(self, entity: Entity, action: Action) -> None:
        if action.type == 'move':
            old_x, old_y = entity.x, entity.y
            entity.move(action.dx, action.dy, self.grid)
            pos = (entity.x, entity.y)
            self.scent_trails.setdefault(pos, []).append(
                (entity.species_name, self.tick_count)
            )
        elif action.type == 'eat':
            if self.grid.has_food(entity.x, entity.y):
                self.grid.remove_food(entity.x, entity.y)
                entity.eat(self.config.ENERGY_PER_FOOD)
        elif action.type == 'reproduce':
            if entity.can_reproduce(self.config):
                entity.energy -= self.config.REPRODUCE_COST
                child = Entity(entity.species_name, entity.x, entity.y, self.config.REPRODUCE_COST)
                # Copy parent's extra dict structure for species-specific state
                if entity.extra:
                    child.extra = {k: (v if not isinstance(v, (list, dict)) else type(v)())
                                   for k, v in entity.extra.items()}
                    # Reset numeric values to defaults
                    for k, v in child.extra.items():
                        if isinstance(v, (int, float)):
                            child.extra[k] = 0
                        elif v is None:
                            child.extra[k] = None
                self.entities.append(child)
        elif action.type == 'signal':
            pos = (entity.x, entity.y)
            self.scent_trails.setdefault(pos, []).append(
                (f"{entity.species_name}:signal", self.tick_count)
            )
        # 'idle' — do nothing

    def get_nearby_entities(self, x: int, y: int, radius: int = 5) -> list[Entity]:
        result = []
        for e in self.entities:
            if not e.is_alive():
                continue
            dx = abs(e.x - x)
            dy = abs(e.y - y)
            dx = min(dx, self.grid.width - dx)
            dy = min(dy, self.grid.height - dy)
            if dx + dy <= radius:
                result.append(e)
        return result

    def get_world_state(self, entity: Entity) -> dict:
        nearby = self.get_nearby_entities(entity.x, entity.y)
        food_positions = self.grid.get_food_positions()
        nearby_food = [
            (fx, fy) for fx, fy in food_positions
            if min(abs(fx - entity.x), self.grid.width - abs(fx - entity.x))
             + min(abs(fy - entity.y), self.grid.height - abs(fy - entity.y)) <= 5
        ]
        return {
            'nearby_entities': [e for e in nearby if e.id != entity.id],
            'nearby_food': nearby_food,
            'local_terrain': self.grid.get_terrain(entity.x, entity.y),
            'entity': {
                'id': entity.id,
                'species': entity.species_name,
                'x': entity.x,
                'y': entity.y,
                'energy': entity.energy,
                'direction': entity.direction,
                'extra': entity.extra,
            },
        }
