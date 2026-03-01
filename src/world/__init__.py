"""World engine — ties grid, entities, and simulation tick together."""

import random
from src.world.grid import Grid, Terrain
from src.world.entity import Entity, Species, Action, ActionCommand, DIRECTION_DELTAS
from src.world import config

__all__ = [
    'World', 'Grid', 'Terrain', 'Entity', 'Species', 'Action',
    'ActionCommand', 'DIRECTION_DELTAS', 'config',
]


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
            entity.energy -= config.ENERGY_LOSS_PER_TICK

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
                entity.energy += config.ENERGY_PER_FOOD
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


if __name__ == '__main__':
    print("=== World Integration Tests ===")

    # Test construction
    w = World(seed=42)
    assert w.grid.width == 100
    assert w.grid.height == 100
    assert w.tick_count == 0
    print("  World construction: OK")

    # Test tick with no entities (just food spawning)
    pops = w.tick()
    assert pops == {}
    assert w.tick_count == 1
    assert len(w.grid.food) > 0
    print("  Empty tick (food spawning): OK")

    # Test exports
    assert Grid is not None
    assert Terrain is not None
    assert Entity is not None
    assert Species is not None
    assert Action is not None
    assert ActionCommand is not None
    assert DIRECTION_DELTAS is not None
    assert config.GRID_WIDTH == 100
    print("  Exports: OK")

    # Test get_entities_at / get_entities_near
    e1 = Entity(10, 10, 'test', energy=50)
    e2 = Entity(11, 10, 'test', energy=50)
    e3 = Entity(50, 50, 'test', energy=50)
    w.entities = [e1, e2, e3]
    at_10 = w.get_entities_at(10, 10)
    assert e1 in at_10 and e2 not in at_10
    near_10 = w.get_entities_near(10, 10, radius=2, exclude=e1)
    assert e2 in near_10 and e3 not in near_10 and e1 not in near_10
    print("  get_entities_at/near: OK")

    # Test multi-tick food accumulation
    w2 = World(seed=99)
    for _ in range(20):
        w2.tick()
    assert len(w2.grid.food) > 10
    print(f"  Food after 20 ticks: {len(w2.grid.food)} OK")

    print("All world tests passed!")
