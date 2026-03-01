"""Multi-species ecosystem simulation runner."""
from __future__ import annotations

import csv
import os
import sys
import time

from src.world import World
from src.world.config import SimConfig
from src.species.ants import AntSpecies
from src.species.birds import BirdSpecies
from src.species.fireflies import FireflySpecies
from src.species.wolves import WolfSpecies


def count_species(world: World) -> dict[str, int]:
    """Count alive entities per species."""
    counts: dict[str, int] = {}
    for e in world.entities:
        if e.is_alive():
            counts[e.species_name] = counts.get(e.species_name, 0) + 1
    return counts


def render_ascii(world: World, species_handlers: dict) -> str:
    """Render the world as a compact ASCII grid (scaled down for terminal)."""
    cfg = world.config
    scale = 2  # show every 2nd cell
    w, h = cfg.GRID_WIDTH // scale, cfg.GRID_HEIGHT // scale

    # Build entity lookup
    entity_map: dict[tuple[int, int], str] = {}
    for e in world.entities:
        if e.is_alive():
            handler = species_handlers.get(e.species_name)
            if handler:
                entity_map[(e.x, e.y)] = handler.render(e)

    food_set = world.grid.get_food_positions()
    lines = []
    for row in range(h):
        line = []
        for col in range(w):
            x, y = col * scale, row * scale
            # Check nearby cells in the scale block
            char = None
            for dx in range(scale):
                for dy in range(scale):
                    cx, cy = x + dx, y + dy
                    if (cx, cy) in entity_map:
                        char = entity_map[(cx, cy)]
                        break
                    if (cx, cy) in food_set:
                        char = '.'
                if char:
                    break
            if char is None:
                terrain = world.grid.get_terrain(x, y)
                if terrain == 1:
                    char = '#'
                elif terrain == 2:
                    char = '~'
                else:
                    char = ' '
            line.append(char)
        lines.append(''.join(line))
    return '\n'.join(lines)


def build_header(world: World, counts: dict[str, int]) -> str:
    """Build status header."""
    total = sum(counts.values())
    food = len(world.grid.get_food_positions())
    parts = [
        f"Tick: {world.tick_count:>5}",
        f"Pop: {total:>4}",
        f"Food: {food:>3}",
        f"| Ants:{counts.get('ant', 0):>3}",
        f"Birds:{counts.get('bird', 0):>3}",
        f"Flies:{counts.get('fireflies', 0):>3}",
        f"Wolves:{counts.get('wolf', 0):>3}",
    ]
    return '  '.join(parts)


def run_simulation(
    max_ticks: int = 500,
    output_dir: str = 'output',
    viz_mode: str = 'ascii',
    tick_delay: float = 0.05,
) -> list[dict]:
    """Run the full simulation loop."""
    os.makedirs(output_dir, exist_ok=True)

    config = SimConfig()
    world = World(config)

    # Register species — key must match entity.species_name AND config INITIAL_{KEY.upper()}
    # Config has INITIAL_ANTS, but entities use species_name='ant', so we register
    # with the config-compatible name and map entity species_names in the handler lookup
    species_map = {
        'ants': ('ant', AntSpecies()),
        'birds': ('bird', BirdSpecies()),
        'fireflies': ('fireflies', FireflySpecies()),
        'wolves': ('wolf', WolfSpecies()),
    }
    handlers = {}
    for config_name, (entity_name, handler) in species_map.items():
        world.register_species(config_name, handler)
        # Also register with entity species_name for tick() lookup
        if entity_name != config_name:
            world.species_handlers[entity_name] = handler
        handlers[entity_name] = handler

    world.spawn_all()

    # CSV output
    csv_path = os.path.join(output_dir, 'population.csv')
    csv_file = open(csv_path, 'w', newline='')
    writer = csv.writer(csv_file)
    writer.writerow(['tick', 'ants', 'birds', 'fireflies', 'wolves', 'total_food'])

    history: list[dict] = []
    extinctions: list[tuple[int, str]] = []
    prev_counts: dict[str, int] = {}

    # Territory tracking: count how many ticks each species occupies each cell
    territory: dict[str, dict[tuple[int, int], int]] = {
        'ant': {}, 'bird': {}, 'fireflies': {}, 'wolf': {}
    }

    try:
        for tick in range(max_ticks):
            world.tick()
            counts = count_species(world)

            # Record history
            row = {
                'tick': world.tick_count,
                'ants': counts.get('ant', 0),
                'birds': counts.get('bird', 0),
                'fireflies': counts.get('fireflies', 0),
                'wolves': counts.get('wolf', 0),
                'total_food': len(world.grid.get_food_positions()),
            }
            history.append(row)
            writer.writerow([
                row['tick'], row['ants'], row['birds'],
                row['fireflies'], row['wolves'], row['total_food'],
            ])

            # Detect extinctions
            for species_key in ['ant', 'bird', 'fireflies', 'wolf']:
                if prev_counts.get(species_key, 1) > 0 and counts.get(species_key, 0) == 0:
                    label = {'ant': 'Ants', 'bird': 'Birds', 'fireflies': 'Fireflies', 'wolf': 'Wolves'}
                    extinctions.append((world.tick_count, label.get(species_key, species_key)))
            prev_counts = counts.copy()

            # Track territory
            for e in world.entities:
                if e.is_alive() and e.species_name in territory:
                    pos = (e.x, e.y)
                    territory[e.species_name][pos] = territory[e.species_name].get(pos, 0) + 1

            # ASCII visualization
            if viz_mode == 'ascii':
                header = build_header(world, counts)
                grid_str = render_ascii(world, handlers)
                sys.stdout.write(f"\033[2J\033[H{header}\n{grid_str}\n")
                sys.stdout.flush()
                time.sleep(tick_delay)

            # Early stop if all species extinct
            if sum(counts.values()) == 0:
                print(f"\nAll species extinct at tick {world.tick_count}")
                break

    except KeyboardInterrupt:
        print("\nSimulation interrupted.")
    finally:
        csv_file.close()

    print(f"\nSimulation complete: {world.tick_count} ticks")
    print(f"CSV saved to: {csv_path}")

    return history, extinctions, territory


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Multi-Species Ecosystem Simulation')
    parser.add_argument('--ticks', type=int, default=500, help='Number of ticks to simulate')
    parser.add_argument('--output', type=str, default='output', help='Output directory')
    parser.add_argument('--delay', type=float, default=0.05, help='Delay between ticks (seconds)')
    parser.add_argument('--no-viz', action='store_true', help='Disable ASCII visualization')
    parser.add_argument('--report', action='store_true', help='Generate HTML report after simulation')
    args = parser.parse_args()

    viz_mode = 'none' if args.no_viz else 'ascii'
    history, extinctions, territory = run_simulation(
        max_ticks=args.ticks,
        output_dir=args.output,
        viz_mode=viz_mode,
        tick_delay=args.delay,
    )

    if args.report:
        from src.visualize import generate_report
        generate_report(history, extinctions, territory, args.output)


if __name__ == '__main__':
    main()
