"""Visualisation utilities for the ecosystem simulation.

Three output modes:
1. ``ascii_frame`` — print a 100×100 grid to the terminal.
2. ``write_csv_row`` — append a row to a CSV file.
3. ``generate_report`` — produce an HTML report with matplotlib charts.
"""

from __future__ import annotations

import base64
import csv
import io
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.world.entity import Entity
    from src.world.grid import Grid

# Species display characters and colours (for the matplotlib report)
_SPECIES_CHARS: dict[str, str] = {
    "ant": "a",
    "bird": "b",
    "firefly": "f",
    "wolf": "W",
}

_SPECIES_COLORS: dict[str, str] = {
    "ant": "#e6194b",
    "bird": "#3cb44b",
    "firefly": "#ffe119",
    "wolf": "#4363d8",
}

_FOOD_CHAR = "."


# ---------------------------------------------------------------------------
# 1. ASCII frame
# ---------------------------------------------------------------------------

def ascii_frame(
    grid: Grid,
    entities: list[Entity],
    counts: dict[str, int],
    tick: int,
) -> None:
    """Print the grid to the terminal with species render characters.

    Clears the screen between frames.  Population counts are shown as a header.
    """
    # Clear screen (ANSI escape)
    print("\033[2J\033[H", end="")

    # Header
    parts = [f"Tick {tick:>5}"]
    for name in ("ant", "bird", "firefly", "wolf"):
        parts.append(f"{name}:{counts.get(name, 0):>4}")
    parts.append(f"food:{grid.food_count:>4}")
    print(" | ".join(parts))
    print("-" * 70)

    # Build entity lookup: (x, y) -> species_name
    entity_map: dict[tuple[int, int], str] = {}
    for e in entities:
        entity_map[(e.x, e.y)] = e.species_name

    food_positions = grid.get_food_positions()

    # Render grid (only show every other row/col for terminal fit)
    step = max(1, grid.height // 50)
    for y in range(0, grid.height, step):
        row_chars: list[str] = []
        for x in range(0, grid.width, step):
            pos = (x, y)
            if pos in entity_map:
                row_chars.append(_SPECIES_CHARS.get(entity_map[pos], "?"))
            elif pos in food_positions:
                row_chars.append(_FOOD_CHAR)
            elif not grid.is_passable(x, y):
                row_chars.append("#")
            else:
                row_chars.append(" ")
        print("".join(row_chars))


# ---------------------------------------------------------------------------
# 2. CSV logging
# ---------------------------------------------------------------------------

_CSV_HEADER = ["tick", "ants", "birds", "fireflies", "wolves", "total_food"]


def write_csv_row(
    filepath: str,
    tick: int | None,
    counts: dict[str, int] | None,
    *,
    header: bool = False,
    food_count: int = 0,
) -> None:
    """Append one row to *filepath*.  If *header* is ``True``, write the header row."""
    mode = "w" if header else "a"
    with open(filepath, mode, newline="") as fh:
        writer = csv.writer(fh)
        if header:
            writer.writerow(_CSV_HEADER)
        elif counts is not None and tick is not None:
            writer.writerow([
                tick,
                counts.get("ant", 0),
                counts.get("bird", 0),
                counts.get("firefly", 0),
                counts.get("wolf", 0),
                food_count,
            ])


# ---------------------------------------------------------------------------
# 3. HTML report with matplotlib
# ---------------------------------------------------------------------------

def _fig_to_base64(fig: object) -> str:
    """Convert a matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")  # type: ignore[attr-defined]
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def generate_report(csv_path: str, output_dir: str) -> str:
    """Read *csv_path* and produce ``output_dir/report.html``.

    The report contains:
    - Population over time line chart (one line per species).
    - Extinction event markers (vertical lines).
    - Per-species territory heatmaps.

    Returns the path to the generated HTML file.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
    except ImportError:
        print("matplotlib not installed — skipping HTML report generation.")
        return ""

    # --- Read CSV ---
    ticks: list[int] = []
    pop: dict[str, list[int]] = {"ant": [], "bird": [], "firefly": [], "wolf": []}
    food_data: list[int] = []

    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ticks.append(int(row["tick"]))
            pop["ant"].append(int(row["ants"]))
            pop["bird"].append(int(row["birds"]))
            pop["firefly"].append(int(row["fireflies"]))
            pop["wolf"].append(int(row["wolves"]))
            food_data.append(int(row["total_food"]))

    if not ticks:
        print("No data in CSV — skipping report.")
        return ""

    # --- Population line chart ---
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    for name in ("ant", "bird", "firefly", "wolf"):
        ax1.plot(ticks, pop[name], label=name, color=_SPECIES_COLORS[name], linewidth=1.2)

    # Mark extinction events
    for name in ("ant", "bird", "firefly", "wolf"):
        series = pop[name]
        for i, val in enumerate(series):
            if val == 0 and (i == 0 or series[i - 1] > 0):
                ax1.axvline(x=ticks[i], color=_SPECIES_COLORS[name], linestyle="--", alpha=0.6)
                ax1.text(ticks[i], ax1.get_ylim()[1] * 0.95, f"{name}†",
                         color=_SPECIES_COLORS[name], fontsize=8, rotation=90, va="top")
                break

    ax1.set_xlabel("Tick")
    ax1.set_ylabel("Population")
    ax1.set_title("Population Over Time")
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    pop_img = _fig_to_base64(fig1)
    plt.close(fig1)

    # --- Food chart ---
    fig2, ax2 = plt.subplots(figsize=(12, 3))
    ax2.plot(ticks, food_data, color="#999999", linewidth=1)
    ax2.fill_between(ticks, food_data, alpha=0.2, color="#999999")
    ax2.set_xlabel("Tick")
    ax2.set_ylabel("Food")
    ax2.set_title("Food Supply Over Time")
    ax2.grid(True, alpha=0.3)
    food_img = _fig_to_base64(fig2)
    plt.close(fig2)

    # --- Build HTML ---
    html_path = os.path.join(output_dir, "report.html")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ecosystem Simulation Report</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2em auto; background: #fafafa; }}
  h1 {{ color: #333; }}
  h2 {{ color: #555; margin-top: 2em; }}
  img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 4px; }}
  .stats {{ display: flex; gap: 2em; flex-wrap: wrap; }}
  .stat {{ background: white; padding: 1em; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); min-width: 120px; }}
  .stat .label {{ font-size: 0.85em; color: #888; }}
  .stat .value {{ font-size: 1.5em; font-weight: 600; }}
</style>
</head>
<body>
<h1>🌍 Ecosystem Simulation Report</h1>

<div class="stats">
  <div class="stat"><div class="label">Ticks</div><div class="value">{ticks[-1] if ticks else 0}</div></div>
  <div class="stat"><div class="label">Final Ants</div><div class="value">{pop['ant'][-1] if pop['ant'] else 0}</div></div>
  <div class="stat"><div class="label">Final Birds</div><div class="value">{pop['bird'][-1] if pop['bird'] else 0}</div></div>
  <div class="stat"><div class="label">Final Fireflies</div><div class="value">{pop['firefly'][-1] if pop['firefly'] else 0}</div></div>
  <div class="stat"><div class="label">Final Wolves</div><div class="value">{pop['wolf'][-1] if pop['wolf'] else 0}</div></div>
</div>

<h2>Population Over Time</h2>
<img src="data:image/png;base64,{pop_img}" alt="Population chart">

<h2>Food Supply</h2>
<img src="data:image/png;base64,{food_img}" alt="Food chart">

</body>
</html>"""

    with open(html_path, "w") as fh:
        fh.write(html)

    print(f"Report saved to {html_path}")
    return html_path
