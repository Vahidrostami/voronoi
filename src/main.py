"""Main simulation loop for the ecosystem simulation.

Usage::

    python -m src.main [--ticks N] [--no-display] [--seed N]

Initialises the grid, spawns all four species, and runs the tick loop.
Each tick: shuffle entities, execute species logic, apply actions, spawn
food, cull dead entities, and record data for visualisation.
"""

from __future__ import annotations

import argparse
import os
import random
import sys

# Bird module uses ``from world.entity import ...`` (no ``src.`` prefix).
# Add ``src/`` to sys.path so that bare ``import world`` resolves correctly.
sys.path.insert(0, os.path.dirname(__file__))

from src.world.grid import Grid
from src.world.entity import Action, Entity, WorldState
from src.world import config
from src.species.ants import AntSpecies
from src.species.birds import BirdSpecies
from src.species.fireflies import FireflySpecies
from src.species.wolves import WolfSpecies

from src.visualize import ascii_frame, write_csv_row, generate_report

# Direction deltas for movement actions
_MOVE_DELTAS: dict[Action, tuple[int, int]] = {
    Action.MOVE_N: (0, -1),
    Action.MOVE_S: (0, 1),
    Action.MOVE_E: (1, 0),
    Action.MOVE_W: (-1, 0),
}

# Ordered species names for consistent reporting
SPECIES_NAMES = ("ant", "bird", "firefly", "wolf")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Ecosystem simulation runner")
    parser.add_argument("--ticks", type=int, default=500, help="Number of ticks to run")
    parser.add_argument("--no-display", action="store_true", help="Skip ASCII display")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Food spawning
# ---------------------------------------------------------------------------

def spawn_food(grid: Grid, rng: random.Random) -> None:
    """Spawn up to FOOD_SPAWN_RATE food items on random passable cells."""
    for _ in range(config.FOOD_SPAWN_RATE):
        if grid.food_count >= config.MAX_FOOD:
            break
        for _ in range(50):
            x = rng.randint(0, grid.width - 1)
            y = rng.randint(0, grid.height - 1)
            if grid.place_food(x, y):
                break


# ---------------------------------------------------------------------------
# Action application
# ---------------------------------------------------------------------------

def apply_action(
    action: Action,
    entity: Entity,
    grid: Grid,
    species_instance: object,
    new_entities: list[Entity],
    rng: random.Random,
) -> None:
    """Apply *action* returned by ``species.tick()`` for *entity*.

    New offspring are appended to *new_entities* (not the main list
    mid-iteration).
    """
    if action in _MOVE_DELTAS:
        dx, dy = _MOVE_DELTAS[action]
        nx, ny = grid.wrap(entity.x + dx, entity.y + dy)
        if grid.is_passable(nx, ny):
            entity.x, entity.y = nx, ny

    elif action is Action.EAT:
        if grid.has_food(entity.x, entity.y):
            grid.remove_food(entity.x, entity.y)
            entity.energy += config.ENERGY_PER_FOOD

    elif action is Action.REPRODUCE:
        if entity.energy >= config.REPRODUCE_THRESHOLD:
            neighbors = grid.get_neighbors(entity.x, entity.y)
            rng.shuffle(neighbors)
            for nx, ny in neighbors:
                if grid.is_passable(nx, ny):
                    child = Entity(
                        x=nx,
                        y=ny,
                        energy=config.STARTING_ENERGY,
                        species_name=entity.species_name,
                    )
                    entity.energy -= config.REPRODUCE_COST
                    new_entities.append(child)
                    # Register with species if it tracks per-entity state
                    if hasattr(species_instance, "register_entity"):
                        species_instance.register_entity(child)
                    break


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def run_simulation(args: argparse.Namespace) -> str:
    """Execute the simulation and return the CSV output path."""
    rng = random.Random(args.seed)
    if args.seed is not None:
        random.seed(args.seed)

    grid = Grid(seed=args.seed)

    # Instantiate species
    ant_species = AntSpecies()
    bird_species = BirdSpecies(seed=args.seed)
    firefly_species = FireflySpecies()
    wolf_species = WolfSpecies()

    species_map: dict[str, object] = {
        "ant": ant_species,
        "bird": bird_species,
        "firefly": firefly_species,
        "wolf": wolf_species,
    }

    # Spawn initial populations
    entities: list[Entity] = []
    entities.extend(ant_species.spawn(grid, config.ANT_COUNT))
    entities.extend(bird_species.spawn(grid, config.BIRD_COUNT))
    entities.extend(firefly_species.spawn(grid, config.FIREFLY_COUNT))
    entities.extend(wolf_species.spawn(grid, config.WOLF_COUNT))

    # CSV setup
    csv_path = os.path.join("output", "simulation.csv")
    write_csv_row(csv_path, tick=0, counts={}, header=True)

    # Track extinctions for the report
    extinctions: dict[str, int] = {}

    for tick in range(1, args.ticks + 1):
        rng.shuffle(entities)

        # Build world state snapshot (living entities only)
        alive_entities = [e for e in entities if e.is_alive()]
        world_state = WorldState(grid=grid, entities=alive_entities)

        new_entities: list[Entity] = []

        for entity in entities:
            if not entity.is_alive():
                continue

            species = species_map.get(entity.species_name)
            if species is None:
                continue

            action = species.tick(entity, world_state)  # type: ignore[arg-type]
            apply_action(action, entity, grid, species, new_entities, rng)

        # Energy drain for non-wolf entities (wolves handle it in tick())
        for entity in entities:
            if entity.is_alive() and entity.species_name != "wolf":
                entity.energy += config.ENERGY_PER_TICK
                if entity.energy <= 0:
                    entity.alive = False

        # Add newborns
        entities.extend(new_entities)

        # Spawn food
        spawn_food(grid, rng)

        # Remove dead entities
        entities = [e for e in entities if e.is_alive()]

        # Clear bird pending signals between ticks
        bird_species.clear_pending_signals()

        # Count populations
        counts: dict[str, int] = {name: 0 for name in SPECIES_NAMES}
        for e in entities:
            if e.species_name in counts:
                counts[e.species_name] += 1

        # Track extinctions
        for name in SPECIES_NAMES:
            if counts[name] == 0 and name not in extinctions:
                extinctions[name] = tick

        # Visualise
        if not args.no_display:
            ascii_frame(grid, entities, counts, tick)

        write_csv_row(csv_path, tick, counts, food_count=grid.food_count)

    # Final report
    print(f"\nSimulation complete after {args.ticks} ticks.")
    for name in SPECIES_NAMES:
        cnt = sum(1 for e in entities if e.species_name == name)
        print(f"  {name}: {cnt}")
    if extinctions:
        for name, t in sorted(extinctions.items(), key=lambda x: x[1]):
            print(f"  {name} went extinct at tick {t}")
    print(f"  Food remaining: {grid.food_count}")

    generate_report(csv_path, "output")
    return csv_path


def main() -> None:
    args = parse_args()
    os.makedirs("output", exist_ok=True)
    run_simulation(args)


if __name__ == "__main__":
    main()
