"""Ecosystem simulation runner — main entry point."""

import sys
import os
import time
import csv
import argparse

# Add demo root (demos/emergent-ecosystem/) to path so `import src.*` works
_DEMO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_ROOT)
_OUTPUT_DIR = os.path.join(_DEMO_ROOT, 'output')

from src.world import World
from src.world import config
from src.species.ants import AntSpecies
from src.species.birds import BirdSpecies
from src.species.fireflies import FireflySpecies
from src.species.wolves import WolfSpecies


def render_ascii(world: World, width: int = 50, height: int = 50) -> str:
    """Render a downsampled ASCII view of the world."""
    x_scale = config.GRID_WIDTH / width
    y_scale = config.GRID_HEIGHT / height

    # Build display grid: space = empty
    display = [[' ' for _ in range(width)] for _ in range(height)]

    # Place terrain (downsampled)
    for dy in range(height):
        for dx in range(width):
            gx = int(dx * x_scale)
            gy = int(dy * y_scale)
            t = world.grid.terrain[gy][gx]
            if t == 1:  # OBSTACLE
                display[dy][dx] = '#'
            elif t == 2:  # WATER
                display[dy][dx] = '~'

    # Place food
    for fx, fy in world.grid.food:
        dx = int(fx / x_scale)
        dy = int(fy / y_scale)
        if 0 <= dx < width and 0 <= dy < height:
            if display[dy][dx] == ' ':
                display[dy][dx] = '.'

    # Place entities (later ones overwrite)
    render_priority = {'ant': 1, 'bird': 2, 'firefly': 3, 'wolf': 4}
    entity_chars = {'ant': 'a', 'bird': 'b', 'firefly': 'f', 'wolf': 'W'}

    entity_map: dict[tuple[int, int], tuple[int, str]] = {}
    for e in world.entities:
        if not e.alive:
            continue
        dx = int(e.x / x_scale)
        dy = int(e.y / y_scale)
        if 0 <= dx < width and 0 <= dy < height:
            prio = render_priority.get(e.species_name, 0)
            current = entity_map.get((dx, dy))
            if current is None or prio > current[0]:
                entity_map[(dx, dy)] = (prio, entity_chars.get(e.species_name, '?'))

    for (dx, dy), (_, ch) in entity_map.items():
        display[dy][dx] = ch

    return '\n'.join(''.join(row) for row in display)


def run_simulation(ticks: int = 500, seed: int | None = None,
                   visual: bool = True, fast: bool = False,
                   csv_path: str = '', report_path: str = '') -> None:
    """Run the ecosystem simulation."""
    if not csv_path:
        csv_path = os.path.join(_OUTPUT_DIR, 'population.csv')
    if not report_path:
        report_path = os.path.join(_OUTPUT_DIR, 'report.html')
    world = World(seed=seed)

    # Register species
    world.register_species('ant', AntSpecies(seed=seed))
    world.register_species('bird', BirdSpecies(seed=seed))
    world.register_species('firefly', FireflySpecies(seed=seed))
    world.register_species('wolf', WolfSpecies(seed=seed))

    # Spawn initial populations
    world.spawn_species('ant', config.ANT_COUNT)
    world.spawn_species('bird', config.BIRD_COUNT)
    world.spawn_species('firefly', config.FIREFLY_COUNT)
    world.spawn_species('wolf', config.WOLF_COUNT)

    # Seed initial food
    world.grid.spawn_food(config.MAX_FOOD // 2)

    # CSV setup
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    csv_file = open(csv_path, 'w', newline='')
    writer = csv.writer(csv_file)
    writer.writerow(['tick', 'ants', 'birds', 'fireflies', 'wolves', 'total_food'])

    # History for charts
    history: list[dict] = []
    extinction_events: list[tuple[int, str]] = []
    was_alive: dict[str, bool] = {'ant': True, 'bird': True, 'firefly': True, 'wolf': True}

    # Cumulative territory heatmaps: species -> 2D array of visit counts
    heatmaps: dict[str, list[list[int]]] = {
        sp: [[0] * config.GRID_WIDTH for _ in range(config.GRID_HEIGHT)]
        for sp in ['ant', 'bird', 'firefly', 'wolf']
    }

    print(f"Starting ecosystem simulation: {ticks} ticks, seed={seed}")
    print(f"Initial: {config.ANT_COUNT} ants, {config.BIRD_COUNT} birds, "
          f"{config.FIREFLY_COUNT} fireflies, {config.WOLF_COUNT} wolves")
    print()

    try:
        for tick in range(1, ticks + 1):
            pops = world.tick()

            # Record positions for cumulative heatmaps
            for e in world.entities:
                if e.alive and e.species_name in heatmaps:
                    heatmaps[e.species_name][e.y][e.x] += 1

            ant_c = pops.get('ant', 0)
            bird_c = pops.get('bird', 0)
            firefly_c = pops.get('firefly', 0)
            wolf_c = pops.get('wolf', 0)
            food_c = len(world.grid.food)

            writer.writerow([tick, ant_c, bird_c, firefly_c, wolf_c, food_c])

            record = {'tick': tick, 'ant': ant_c, 'bird': bird_c,
                      'firefly': firefly_c, 'wolf': wolf_c, 'food': food_c}
            history.append(record)

            # Track extinctions
            for sp in ['ant', 'bird', 'firefly', 'wolf']:
                if was_alive[sp] and record[sp] == 0:
                    extinction_events.append((tick, sp))
                    was_alive[sp] = False

            # Visual output
            if visual and tick % 5 == 0:
                ascii_view = render_ascii(world)
                print('\033[2J\033[H', end='')
                print(f"=== Ecosystem Simulation — Tick {tick}/{ticks} ===")
                print(f"  Ants: {ant_c:4d}  Birds: {bird_c:4d}  "
                      f"Fireflies: {firefly_c:4d}  Wolves: {wolf_c:4d}  "
                      f"Food: {food_c:4d}")
                if extinction_events:
                    ext_str = ', '.join(f"{sp}@t{t}" for t, sp in extinction_events)
                    print(f"  Extinctions: {ext_str}")
                print()
                print(ascii_view)
                print()
                print("Legend: a=ant b=bird f=firefly W=wolf .=food #=obstacle ~=water")
                if not fast:
                    time.sleep(0.05)
            elif not visual and tick % 50 == 0:
                print(f"Tick {tick:4d}: ants={ant_c} birds={bird_c} "
                      f"fireflies={firefly_c} wolves={wolf_c} food={food_c}")

            # Early stop if all species dead
            total = ant_c + bird_c + firefly_c + wolf_c
            if total == 0:
                print(f"\nAll species extinct at tick {tick}!")
                break

    except KeyboardInterrupt:
        print("\nSimulation interrupted.")

    csv_file.close()
    print(f"\nPopulation data saved to {csv_path}")

    # Generate HTML report
    try:
        from src.visualize import generate_report
        generate_report(history, extinction_events, heatmaps, report_path)
        print(f"HTML report saved to {report_path}")
    except ImportError as e:
        print(f"Could not generate report: {e}")


def main():
    parser = argparse.ArgumentParser(description='Ecosystem Simulation')
    parser.add_argument('--ticks', type=int, default=500, help='Number of ticks')
    parser.add_argument('--seed', type=int, default=None, help='Random seed')
    parser.add_argument('--no-viz', action='store_true', help='Disable ASCII viz')
    parser.add_argument('--fast', action='store_true', help='No delay between frames')
    parser.add_argument('--csv', default='', help='CSV output path')
    parser.add_argument('--report', default='', help='HTML report path')
    args = parser.parse_args()

    run_simulation(
        ticks=args.ticks,
        seed=args.seed,
        visual=not args.no_viz,
        fast=args.fast,
        csv_path=args.csv,
        report_path=args.report,
    )


if __name__ == '__main__':
    main()
