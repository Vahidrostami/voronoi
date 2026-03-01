"""World engine — ties grid, entities, and simulation tick together."""

import random
from src.world.grid import Grid
from src.world.entity import Entity, Species, Action, DIRECTION_DELTAS
from src.world import config


class World:
    """Main simulation world that manages all entities and the tick loop."""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.grid = Grid(seed=seed)
        self.entities: list[Entity] = []
        self.species_handlers: dict[str, Species] = {}
        self.tick_count = 0

    def register_species(self, name: str, handler: Species) -> None:
        """Register a species handler."""
        self.species_handlers[name] = handler

    def spawn_species(self, name: str, count: int) -> None:
        """Spawn entities for a registered species."""
        handler = self.species_handlers[name]
        new_entities = handler.spawn(self.grid, count)
        self.entities.extend(new_entities)

    def tick(self) -> dict[str, int]:
        """Run one simulation tick. Returns population counts."""
        self.tick_count += 1
        self.grid.current_tick = self.tick_count

        # Randomize creature order
        self.rng.shuffle(self.entities)

        # Each creature acts
        new_entities: list[Entity] = []
        for entity in self.entities:
            if entity.is_dead():
                continue

            handler = self.species_handlers.get(entity.species_name)
            if handler is None:
                continue

            action = handler.tick(entity, self.grid, self.entities)
            self._apply_action(entity, action, new_entities)

            # Age and energy cost
            entity.age += 1
            entity.energy -= config.ENERGY_COST_PER_TICK

            # Record trail for scent tracking
            self.grid.record_trail(entity.x, entity.y, entity.species_name)

            # Die if no energy
            if entity.energy <= 0:
                entity.alive = False

        # Add newborns
        self.entities.extend(new_entities)

        # Spawn food
        self.grid.spawn_food()

        # Cleanup dead
        self.entities = [e for e in self.entities if e.alive]

        # Periodic trail cleanup
        if self.tick_count % 10 == 0:
            self.grid.cleanup_trails()

        return self.get_populations()

    def _apply_action(self, entity: Entity, action: Action,
                      new_entities: list[Entity]) -> None:
        """Apply an action to an entity."""
        if action in DIRECTION_DELTAS:
            dx, dy = DIRECTION_DELTAS[action]
            entity.move(dx, dy, self.grid)
        elif action == Action.EAT:
            if self.grid.consume_food(entity.x, entity.y):
                entity.energy += config.ENERGY_FROM_FOOD
        elif action == Action.REPRODUCE:
            if entity.energy > config.REPRODUCE_THRESHOLD:
                entity.energy -= config.REPRODUCE_COST
                child = Entity(entity.x, entity.y, entity.species_name,
                               energy=config.ENERGY_START)
                # Copy species-specific extra data defaults
                child.extra = {k: v for k, v in entity.extra.items()
                               if k.startswith('init_')}
                new_entities.append(child)

    def get_populations(self) -> dict[str, int]:
        """Count living entities per species."""
        counts: dict[str, int] = {}
        for e in self.entities:
            if e.alive:
                counts[e.species_name] = counts.get(e.species_name, 0) + 1
        return counts

    def get_entities_at(self, x: int, y: int) -> list[Entity]:
        """Get all living entities at a position."""
        return [e for e in self.entities if e.alive and e.x == x and e.y == y]

    def get_entities_near(self, x: int, y: int, radius: int,
                          exclude: Entity | None = None) -> list[Entity]:
        """Get living entities within Chebyshev distance radius."""
        result = []
        for e in self.entities:
            if e.alive and e is not exclude:
                if self.grid.distance(x, y, e.x, e.y) <= radius:
                    result.append(e)
        return result
