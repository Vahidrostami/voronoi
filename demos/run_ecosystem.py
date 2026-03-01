#!/usr/bin/env python3
"""
🌍 ECOSYSTEM SIMULATION — Live Demo
Colorful terminal visualization of emergent multi-species behavior.

Usage:
    python demos/run_ecosystem.py              # default 500 ticks
    python demos/run_ecosystem.py --ticks 300  # custom length
    python demos/run_ecosystem.py --seed 42    # reproducible
"""

import sys
import os
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.world import World
from src.world import config
from src.species.ants import AntSpecies
from src.species.birds import BirdSpecies
from src.species.fireflies import FireflySpecies
from src.species.wolves import WolfSpecies


# ── ANSI Color Codes ──────────────────────────────────────────────────────────
RESET   = '\033[0m'
BOLD    = '\033[1m'
DIM     = '\033[2m'

# Species colors
RED     = '\033[91m'    # wolves
GREEN   = '\033[92m'    # ants
YELLOW  = '\033[93m'    # fireflies
BLUE    = '\033[94m'    # birds
CYAN    = '\033[96m'    # water
WHITE   = '\033[97m'    # food
GRAY    = '\033[90m'    # obstacles
MAGENTA = '\033[95m'    # extinction events

# Background highlights for dense areas
BG_RED    = '\033[41m'
BG_GREEN  = '\033[42m'
BG_YELLOW = '\033[43m'
BG_BLUE   = '\033[44m'

# Species display config
SPECIES_STYLE = {
    'ant':     (GREEN,  'a', '🐜'),
    'bird':    (BLUE,   'b', '🐦'),
    'firefly': (YELLOW, 'f', '✨'),
    'wolf':    (RED,    'W', '🐺'),
}


def colored_render(world: World, width: int = 60, height: int = 30) -> str:
    """Render a colorful downsampled ASCII view."""
    x_scale = config.GRID_WIDTH / width
    y_scale = config.GRID_HEIGHT / height

    # Build display grid
    display = [[None for _ in range(width)] for _ in range(height)]

    # Terrain
    for dy in range(height):
        for dx in range(width):
            gx = int(dx * x_scale)
            gy = int(dy * y_scale)
            t = world.grid.terrain[gy][gx]
            if t == 1:
                display[dy][dx] = f'{GRAY}░{RESET}'
            elif t == 2:
                display[dy][dx] = f'{CYAN}~{RESET}'
            else:
                display[dy][dx] = f'{DIM}·{RESET}'

    # Food — bright dots
    for fx, fy in world.grid.food:
        dx = int(fx / x_scale)
        dy = int(fy / y_scale)
        if 0 <= dx < width and 0 <= dy < height:
            cur = display[dy][dx]
            if cur and '░' not in cur and 'a' not in cur and 'b' not in cur:
                display[dy][dx] = f'{WHITE}{BOLD}•{RESET}'

    # Entity density tracking per cell
    cell_entities: dict[tuple[int, int], list[str]] = {}
    for e in world.entities:
        if not e.alive:
            continue
        dx = int(e.x / x_scale)
        dy = int(e.y / y_scale)
        if 0 <= dx < width and 0 <= dy < height:
            key = (dx, dy)
            cell_entities.setdefault(key, []).append(e.species_name)

    # Render entities with color
    for (dx, dy), species_list in cell_entities.items():
        count = len(species_list)
        # Pick highest-priority species to show
        priority = {'wolf': 4, 'firefly': 3, 'bird': 2, 'ant': 1}
        top = max(species_list, key=lambda s: priority.get(s, 0))
        color, char, _emoji = SPECIES_STYLE[top]

        if count >= 5:
            display[dy][dx] = f'{color}{BOLD}{char.upper()}{RESET}'
        elif count >= 2:
            display[dy][dx] = f'{color}{BOLD}{char}{RESET}'
        else:
            display[dy][dx] = f'{color}{char}{RESET}'

    return '\n'.join(''.join(row) for row in display)


def population_bars(pops: dict, tick: int, max_bar: int = 20) -> str:
    """Render colored population bar chart."""
    lines = []
    species_info = [
        ('ant',     '🐜 Ants     ', GREEN),
        ('bird',    '🐦 Birds    ', BLUE),
        ('firefly', '✨ Fireflies', YELLOW),
        ('wolf',    '🐺 Wolves   ', RED),
    ]

    max_pop = max(max(pops.values(), default=1), 1)

    for key, label, color in species_info:
        count = pops.get(key, 0)
        bar_len = int((count / max_pop) * max_bar) if max_pop > 0 else 0
        bar = '█' * bar_len + '░' * (max_bar - bar_len)
        lines.append(f'  {color}{label} {bar} {BOLD}{count:4d}{RESET}')

    return '\n'.join(lines)


def run_demo(ticks: int = 500, seed: int | None = None, delay: float = 0.08):
    """Run the visual demo."""
    world = World(seed=seed)
    world.register_species('ant', AntSpecies(seed=seed))
    world.register_species('bird', BirdSpecies(seed=seed))
    world.register_species('firefly', FireflySpecies(seed=seed))
    world.register_species('wolf', WolfSpecies(seed=seed))

    world.spawn_species('ant', config.ANT_COUNT)
    world.spawn_species('bird', config.BIRD_COUNT)
    world.spawn_species('firefly', config.FIREFLY_COUNT)
    world.spawn_species('wolf', config.WOLF_COUNT)
    world.grid.spawn_food(config.MAX_FOOD // 2)

    extinctions: list[tuple[int, str]] = []
    was_alive = {'ant': True, 'bird': True, 'firefly': True, 'wolf': True}

    # Hide cursor
    print('\033[?25l', end='')

    try:
        for tick in range(1, ticks + 1):
            pops = world.tick()

            # Track extinctions
            for sp in ['ant', 'bird', 'firefly', 'wolf']:
                if was_alive[sp] and pops.get(sp, 0) == 0:
                    extinctions.append((tick, sp))
                    was_alive[sp] = False

            # Render every 2 ticks for smoother feel
            if tick % 2 != 0 and tick != 1:
                continue

            grid_view = colored_render(world)
            bars = population_bars(pops, tick)
            food_count = len(world.grid.food)
            total_pop = sum(pops.values())

            # Clear screen and draw
            print('\033[2J\033[H', end='')
            print(f'{BOLD}{"═" * 62}{RESET}')
            print(f'{BOLD}  🌍 ECOSYSTEM SIMULATION{RESET}   '
                  f'{DIM}Tick {tick:4d}/{ticks}  │  '
                  f'Pop: {total_pop:4d}  │  Food: {food_count:4d}{RESET}')
            print(f'{BOLD}{"═" * 62}{RESET}')
            print()
            print(grid_view)
            print()
            print(f'{BOLD}{"─" * 62}{RESET}')
            print(f'{BOLD}  Population{RESET}')
            print(bars)

            if extinctions:
                print()
                ext_str = '  '.join(
                    f'{MAGENTA}{BOLD}💀 {sp} extinct @ tick {t}{RESET}'
                    for t, sp in extinctions
                )
                print(f'  {ext_str}')

            print(f'{BOLD}{"─" * 62}{RESET}')
            print(f'{DIM}  Legend: {GREEN}a{RESET}{DIM}=ant  '
                  f'{BLUE}b{RESET}{DIM}=bird  '
                  f'{YELLOW}f{RESET}{DIM}=firefly  '
                  f'{RED}W{RESET}{DIM}=wolf  '
                  f'{WHITE}{BOLD}•{RESET}{DIM}=food  '
                  f'{GRAY}░{RESET}{DIM}=obstacle  '
                  f'{CYAN}~{RESET}{DIM}=water{RESET}')

            # Early stop
            if total_pop == 0:
                print()
                print(f'{MAGENTA}{BOLD}  ☠️  ALL SPECIES EXTINCT — '
                      f'Simulation ended at tick {tick}{RESET}')
                break

            time.sleep(delay)

    except KeyboardInterrupt:
        pass
    finally:
        # Show cursor
        print('\033[?25h')
        print()
        print(f'{BOLD}Simulation complete.{RESET}')
        if extinctions:
            print(f'{DIM}Extinction timeline:{RESET}')
            for t, sp in extinctions:
                _, _, emoji = SPECIES_STYLE[sp]
                print(f'  {emoji}  {sp:10s} went extinct at tick {t}')
        print()
        print(f'{DIM}Run "python src/main.py --ticks 500 --seed 42 --no-viz --fast" '
              f'for CSV + HTML report{RESET}')


def main():
    parser = argparse.ArgumentParser(description='Ecosystem Demo')
    parser.add_argument('--ticks', type=int, default=500)
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--delay', type=float, default=0.08,
                        help='Seconds between frames')
    args = parser.parse_args()
    run_demo(ticks=args.ticks, seed=args.seed, delay=args.delay)


if __name__ == '__main__':
    main()
